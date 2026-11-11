"""Servidor HTTP: el celular sube (video, telemetría) y luego consulta el informe.

Arranque (desde inspeccion-dron/):
    venv/bin/uvicorn servidor.app:app --host 0.0.0.0 --port 8000
Contrato completo de la API en API_CELULAR.md
"""
import html
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import markdown
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

import config
from servidor import trabajos
from src.pipeline import TIPOS_RUTA
from src.telemetria import cargar_telemetria

EXT_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp"}
EXT_TELEMETRIA = {".csv", ".json"}
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    trabajos.iniciar_trabajador()
    yield


app = FastAPI(title="Reconocimiento de rutas con dron", version="1.0", lifespan=lifespan)


def autorizar(x_api_key: str | None = Header(None), token: str | None = Query(None)):
    """Si API_TOKEN está en .env, exige la cabecera X-API-Key (o ?token= en el navegador)."""
    if config.API_TOKEN and config.API_TOKEN not in (x_api_key, token):
        raise HTTPException(401, "Falta o es incorrecta la cabecera X-API-Key")


def _guardar(subida: UploadFile, destino: Path, limite_mb: int):
    limite, total = limite_mb * 1024 * 1024, 0
    with open(destino, "wb") as f:
        while bloque := subida.file.read(1024 * 1024):
            total += len(bloque)
            if total > limite:
                raise HTTPException(413, f"Archivo mayor a {limite_mb} MB")
            f.write(bloque)
    if total == 0:
        raise HTTPException(422, f"El archivo {subida.filename!r} llegó vacío")
    return total


def _urls(vuelo_id):
    base = f"/api/vuelos/{vuelo_id}"
    return {"estado": base, "informe_md": f"{base}/informe",
            "informe_html": f"/vuelos/{vuelo_id}", "resumen_json": f"{base}/resumen"}


def _estado_o_404(vuelo_id):
    try:
        est = trabajos.leer_estado(vuelo_id)
    except ValueError:
        est = None
    if est is None:
        raise HTTPException(404, "Vuelo no encontrado")
    est["posicion_en_cola"] = trabajos.posicion_en_cola(vuelo_id)
    est["urls"] = _urls(vuelo_id)
    return est


# ------------------------------------------------------------------ API
@app.get("/api/salud")
def salud():
    return {"ok": True, "llm": config.LLM_PROVIDER, "requiere_token": bool(config.API_TOKEN)}


@app.post("/api/vuelos", status_code=202, dependencies=[Depends(autorizar)])
def subir_vuelo(
    video: UploadFile = File(..., description="Video del dron"),
    telemetria: UploadFile | None = File(None, description="CSV o JSON de telemetría"),
    telemetria_json: str | None = Form(None, description="Telemetría como texto JSON (alternativa)"),
    meta: UploadFile | None = File(None, description="JSON con video_start_epoch_ms (opcional)"),
    video_start_epoch_ms: int | None = Form(None, description="Inicio del video en epoch ms"),
    offset_ms: int = Form(0),
    tipo_ruta: str = Form("general", description="a_pie | vehiculo | general"),
    nombre: str | None = Form(None, description="Nombre libre de la ruta"),
):
    if tipo_ruta not in TIPOS_RUTA:
        raise HTTPException(422, f"tipo_ruta debe ser uno de {sorted(TIPOS_RUTA)}")
    ext_v = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext_v not in EXT_VIDEO:
        raise HTTPException(422, f"Extensión de video no soportada: {ext_v}")
    if telemetria is None and not telemetria_json:
        raise HTTPException(422, "Envía 'telemetria' (archivo) o 'telemetria_json' (texto)")

    vuelo_id = trabajos.nuevo_id()
    d = trabajos.dir_vuelo(vuelo_id)
    d.mkdir(parents=True)
    try:
        # telemetría primero: es pequeña y si está mal fallamos antes de recibir el video
        if telemetria is not None:
            ext_t = Path(telemetria.filename or "t.csv").suffix.lower()
            if ext_t not in EXT_TELEMETRIA:
                raise HTTPException(422, f"Telemetría debe ser .csv o .json, no {ext_t}")
            archivo_tel = f"telemetria{ext_t}"
            _guardar(telemetria, d / archivo_tel, 200)
        else:
            archivo_tel = "telemetria.json"
            (d / archivo_tel).write_text(telemetria_json, encoding="utf-8")
        try:
            muestras = cargar_telemetria(d / archivo_tel)
        except Exception as e:
            raise HTTPException(422, f"Telemetría inválida: {type(e).__name__}: {e}")

        meta_dict = None
        if meta is not None:
            try:
                meta_dict = json.loads(meta.file.read().decode("utf-8"))
            except Exception:
                raise HTTPException(422, "meta no es un JSON válido")

        archivo_video = f"video{ext_v}"
        bytes_video = _guardar(video, d / archivo_video, config.MAX_SUBIDA_MB)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise

    est = trabajos.crear(vuelo_id, {
        "nombre": nombre, "tipo_ruta": tipo_ruta, "offset_ms": offset_ms,
        "video_start_epoch_ms": video_start_epoch_ms, "meta": meta_dict,
        "archivo_video": archivo_video, "archivo_telemetria": archivo_tel,
        "video_original": video.filename, "bytes_video": bytes_video,
        "muestras_telemetria": len(muestras),
    })
    return {"id": vuelo_id, "estado": est["estado"], "urls": _urls(vuelo_id)}


@app.get("/api/vuelos", dependencies=[Depends(autorizar)])
def listar_vuelos():
    return [{k: e.get(k) for k in ("id", "estado", "progreso", "mensaje", "creado")}
            | {"nombre": e["parametros"].get("nombre"), "tipo_ruta": e["parametros"].get("tipo_ruta")}
            for e in trabajos.listar() if e]


@app.get("/api/vuelos/{vuelo_id}", dependencies=[Depends(autorizar)])
def estado_vuelo(vuelo_id: str):
    return _estado_o_404(vuelo_id)


@app.post("/api/vuelos/{vuelo_id}/reintentar", status_code=202, dependencies=[Depends(autorizar)])
def reintentar(vuelo_id: str):
    est = _estado_o_404(vuelo_id)
    if est["estado"] in trabajos.ESTADOS_PENDIENTES:
        raise HTTPException(409, "El vuelo ya está en proceso")
    trabajos.crear(vuelo_id, est["parametros"])
    return {"id": vuelo_id, "estado": "en_cola", "urls": _urls(vuelo_id)}


def _ruta_lista(vuelo_id, archivo):
    est = _estado_o_404(vuelo_id)
    ruta = trabajos.dir_vuelo(vuelo_id) / archivo
    if est["estado"] != "listo" or not ruta.exists():
        raise HTTPException(409, f"El informe aún no está listo (estado: {est['estado']})")
    return ruta


@app.get("/api/vuelos/{vuelo_id}/informe", response_class=PlainTextResponse,
         dependencies=[Depends(autorizar)])
def informe_md(vuelo_id: str):
    return PlainTextResponse(_ruta_lista(vuelo_id, "reporte.md").read_text(encoding="utf-8"),
                             media_type="text/markdown; charset=utf-8")


@app.get("/api/vuelos/{vuelo_id}/resumen", dependencies=[Depends(autorizar)])
def resumen(vuelo_id: str):
    return json.loads(_ruta_lista(vuelo_id, "resumen_tramos.json").read_text(encoding="utf-8"))


@app.get("/api/vuelos/{vuelo_id}/frames/{nombre}", dependencies=[Depends(autorizar)])
def frame(vuelo_id: str, nombre: str):
    _estado_o_404(vuelo_id)
    carpeta = (trabajos.dir_vuelo(vuelo_id) / "frames").resolve()
    ruta = (carpeta / nombre).resolve()
    if ruta.parent != carpeta or not ruta.exists():
        raise HTTPException(404, "Imagen no encontrada")
    return FileResponse(ruta)


# ------------------------------------------------------------------ páginas web
@app.get("/", response_class=HTMLResponse)
def inicio():
    return FileResponse(STATIC / "index.html")


@app.get("/vuelos/{vuelo_id}", response_class=HTMLResponse, dependencies=[Depends(autorizar)])
def informe_html(vuelo_id: str, token: str | None = None):
    md = _ruta_lista(vuelo_id, "reporte.md").read_text(encoding="utf-8")
    cuerpo = markdown.markdown(html.escape(md, quote=False), extensions=["tables"])
    q = f"?token={token}" if token else ""
    imgs = sorted((trabajos.dir_vuelo(vuelo_id) / "frames").glob("*.jpg"))[:24]
    galeria = "".join(f'<figure><img loading="lazy" src="/api/vuelos/{vuelo_id}/frames/{i.name}{q}">'
                      f"<figcaption>{i.stem}</figcaption></figure>" for i in imgs)
    if galeria:
        galeria = f"<h2>Fotogramas con detecciones</h2><div class=gal>{galeria}</div>"
    return f"""<!doctype html><html lang=es><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Informe {vuelo_id}</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:860px;margin:auto;padding:16px;
color:#1d2430;background:#fafbfc}}h1,h2{{line-height:1.25}}blockquote{{border-left:4px solid #e0a800;
margin:0;padding:4px 12px;background:#fff8e1}}.gal{{display:grid;gap:8px;
grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}img{{width:100%;border-radius:6px}}
figure{{margin:0}}figcaption{{font-size:12px;color:#667}}
@media(prefers-color-scheme:dark){{body{{background:#14171c;color:#e4e7eb}}
blockquote{{background:#2b2612}}}}</style>
<p><a href="/">← volver</a></p>{cuerpo}{galeria}</html>"""
