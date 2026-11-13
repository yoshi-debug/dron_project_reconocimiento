"""Cola de vuelos: cada envío del celular es un trabajo que se procesa en segundo plano.

Estado persistente en salida/vuelos/<id>/estado.json, así sobrevive a reinicios del servidor.
Un solo hilo procesa los vuelos de uno en uno (YOLO en CPU no se beneficia de paralelizar).
"""
import json
import queue
import shutil
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config
from src.mision import cargar_mision, preparar_vuelo, seccion_markdown
from src.pipeline import generar_reporte, procesar_segmentos, procesar_video

ESTADOS_PENDIENTES = {"en_cola", "procesando_video", "generando_informe"}
_lock = threading.Lock()
_cola: "queue.Queue[str]" = queue.Queue()
_analizador = None   # el modelo YOLO se carga una vez y se reutiliza


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nuevo_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def dir_vuelo(vuelo_id: str) -> Path:
    d = (config.DIR_VUELOS / vuelo_id).resolve()
    if d.parent != config.DIR_VUELOS.resolve():          # evita ../ en el id
        raise ValueError("id inválido")
    return d


def leer_estado(vuelo_id: str) -> dict | None:
    ruta = dir_vuelo(vuelo_id) / "estado.json"
    if not ruta.exists():
        return None
    with _lock:
        return json.loads(ruta.read_text(encoding="utf-8"))


def actualizar(vuelo_id: str, **campos):
    ruta = dir_vuelo(vuelo_id) / "estado.json"
    with _lock:
        estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
        estado.update(campos, actualizado=_ahora())
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ruta)
    return estado


def crear(vuelo_id: str, parametros: dict) -> dict:
    previo = leer_estado(vuelo_id) or {}
    estado = actualizar(vuelo_id, id=vuelo_id, estado="en_cola", progreso=0.0,
                        mensaje="Esperando turno", creado=previo.get("creado", _ahora()),
                        parametros=parametros, error=None)
    _cola.put(vuelo_id)
    return estado


def listar() -> list[dict]:
    if not config.DIR_VUELOS.exists():
        return []
    out = []
    for d in sorted(config.DIR_VUELOS.iterdir(), reverse=True):
        if (d / "estado.json").exists():
            out.append(leer_estado(d.name))
    return out


def _procesar(vuelo_id: str):
    global _analizador
    d = dir_vuelo(vuelo_id)
    est = leer_estado(vuelo_id)
    p = est["parametros"]
    try:
        actualizar(vuelo_id, estado="procesando_video", progreso=0.0, mensaje="Cargando modelos")
        if _analizador is None:
            from src.vision import Analizador
            _analizador = Analizador()

        def prog_video(f, m):     # la etapa 1 ocupa el 0-80 % de la barra
            actualizar(vuelo_id, progreso=round(0.8 * f, 3), mensaje=m)

        extra = {}
        previo = d / "info_corrida.json"
        if p.get("solo_informe") and (d / "resultados_frames.csv").exists() and previo.exists():
            info = json.loads(previo.read_text(encoding="utf-8"))   # reusa el análisis de video
            if info.get("datos_vuelo"):
                extra = {"titulo": f"Informe del vuelo {p['vuelo']} (misión {p['mision']})",
                         "seccion_vuelo": seccion_markdown(info["datos_vuelo"])}
            est_prev = leer_estado(vuelo_id) or {}
            if est_prev.get("videos_procesados"):
                actualizar(vuelo_id, videos_procesados=est_prev["videos_procesados"])
        elif p.get("tipo") == "mision":
            shutil.rmtree(d / "frames", ignore_errors=True)     # imágenes de una corrida anterior
            prep = preparar_vuelo(cargar_mision(config.DIR_MISIONES / p["mision"]), p["vuelo"])
            if not prep["videos"]:
                raise ValueError("Ningún video de la misión cubre este vuelo.")
            info = procesar_segmentos(prep["videos"], prep["muestras"], d, ventana=prep["ventana"],
                                      analizador=_analizador, progreso=prog_video,
                                      extra_info={"datos_vuelo": prep["datos"]})
            extra = {"titulo": f"Informe del vuelo {p['vuelo']} (misión {p['mision']})",
                     "seccion_vuelo": seccion_markdown(prep["datos"])}
            actualizar(vuelo_id, videos_procesados=[v["nombre"] for v in prep["videos"]])
        else:
            shutil.rmtree(d / "frames", ignore_errors=True)
            info = procesar_video(d / p["archivo_video"], d / p["archivo_telemetria"], d,
                                  meta=p.get("meta"), inicio_ms=p.get("video_start_epoch_ms"),
                                  offset_ms=p.get("offset_ms", 0), analizador=_analizador,
                                  progreso=prog_video, nombre_video=p.get("video_original"))

        actualizar(vuelo_id, estado="generando_informe", progreso=0.8,
                   mensaje="Redactando informe", info_corrida=info)

        def prog_inf(f, m):
            actualizar(vuelo_id, progreso=round(0.8 + 0.2 * f, 3), mensaje=m)

        r = generar_reporte(d, p.get("tipo_ruta", "general"), usar_llm=p.get("usar_llm", True),
                            progreso=prog_inf, **extra)
        actualizar(vuelo_id, estado="listo", progreso=1.0, mensaje="Informe listo", **r)
    except Exception as e:
        traceback.print_exc()
        actualizar(vuelo_id, estado="error", mensaje="Falló el procesamiento",
                   error=f"{type(e).__name__}: {e}")


def _bucle():
    while True:
        vuelo_id = _cola.get()
        try:
            _procesar(vuelo_id)
        finally:
            _cola.task_done()


def iniciar_trabajador():
    """Arranca el hilo y re-encola lo que quedó a medias si el servidor se reinició."""
    config.DIR_VUELOS.mkdir(parents=True, exist_ok=True)
    for est in reversed(listar()):
        if est and est.get("estado") in ESTADOS_PENDIENTES:
            actualizar(est["id"], estado="en_cola", progreso=0.0,
                       mensaje="Re-encolado tras reinicio del servidor")
            _cola.put(est["id"])
    threading.Thread(target=_bucle, name="procesador-vuelos", daemon=True).start()


def posicion_en_cola(vuelo_id: str) -> int | None:
    with _cola.mutex:
        pendientes = list(_cola.queue)
    return pendientes.index(vuelo_id) + 1 if vuelo_id in pendientes else None


# ------------------------------------------------------------------ misiones (carpetas de la app)
def id_mision(mision: str, vuelo: str) -> str:
    return f"{mision}__{vuelo}"


def vuelos_listos(mision: str) -> list[tuple[str, list[str]]]:
    """Vuelos de la misión que ya tienen video que los cubra: [(vuelo_id, [videos])]."""
    sesiones = cargar_mision(config.DIR_MISIONES / mision)
    out = []
    for s in sesiones:
        if s["es_vuelo"]:
            vids = preparar_vuelo(sesiones, s["id"])["videos"]
            if vids:
                out.append((s["id"], [v["nombre"] for v in vids]))
    return out


def encolar_mision(mision: str, tipo_ruta="general", forzar=False, usar_llm=True) -> list[str]:
    """Encola los vuelos nuevos o cuyos videos cambiaron (p. ej. llegó un video más tarde)."""
    encolados = []
    for vuelo, videos in vuelos_listos(mision):
        jid = id_mision(mision, vuelo)
        dir_vuelo(jid).mkdir(parents=True, exist_ok=True)
        est = leer_estado(jid) or {}
        if est.get("estado") in ESTADOS_PENDIENTES:
            continue
        if not forzar and est.get("estado") == "listo" and est.get("videos_procesados") == videos:
            continue
        crear(jid, {"tipo": "mision", "mision": mision, "vuelo": vuelo, "tipo_ruta": tipo_ruta,
                    "usar_llm": usar_llm, "nombre": f"{mision} / {vuelo}"})
        encolados.append(jid)
    return encolados


def procesar_ahora(jid: str):
    """Procesa un trabajo ya creado en este mismo hilo (lo usa la línea de comandos)."""
    _cola.queue.remove(jid) if jid in _cola.queue else None
    _procesar(jid)
    return leer_estado(jid)
