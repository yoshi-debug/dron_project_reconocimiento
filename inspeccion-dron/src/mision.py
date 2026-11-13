"""Misiones grabadas por la app del celular.

Estructura (una carpeta por misión, una subcarpeta por sesión):

    vuelos/<mision>/
        tierra_YYYYMMDD_HHMMSS/   dron en el suelo (antes/después de volar)
            resumen.json          flight_id, started_at_ms, last_seen_ms, ended, videos[...]
            telemetria.csv        timestamp_ms,event,latitude,longitude,altitude_m,...
            video.mp4, video_2.mp4
        vuelo_YYYYMMDD_HHMMSS/    dron en el aire (FLIGHT_START ... FLIGHT_END)
            resumen.json
            telemetria.csv

Sincronía: cada video tiene un par de eventos VIDEO_START / VIDEO_STOP en la telemetría de la
sesión donde empezó a grabarse; el n-ésimo VIDEO_START de una sesión corresponde al n-ésimo
archivo de `resumen.json["videos"]`. Como la grabación suele empezar antes del despegue, el
video de un vuelo normalmente está en la carpeta `tierra_*` anterior: por eso la misión se trata
como una sola línea de tiempo y a cada vuelo se le asignan los videos que se solapan con él.
"""
import json
import re
from pathlib import Path

from src.frames import info_video
from src.telemetria import leer_filas, muestras_desde_filas, asignar_tramos

NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_.-]+$")
MARGEN_MS = 5000          # telemetría extra a cada lado del vuelo (para interpolar en los bordes)


def _eventos(filas):
    return [{"ts_ms": int(float(f["timestamp_ms"])), "evento": f.get("event", ""),
             "detalle": f.get("details", "") or ""}
            for f in filas if f.get("event") not in (None, "", "TELEMETRY")]


def cargar_sesion(d: Path) -> dict:
    resumen = json.loads((d / "resumen.json").read_text(encoding="utf-8"))
    filas = leer_filas(d / "telemetria.csv") if (d / "telemetria.csv").exists() else []
    eventos = _eventos(filas)
    starts = [e for e in eventos if e["evento"] == "VIDEO_START"]
    stops = {e["detalle"]: e["ts_ms"] for e in eventos if e["evento"] == "VIDEO_STOP"}
    videos = []
    for n, item in enumerate(resumen.get("videos", [])):
        # "video.mp4"  o  {"archivo": "video.mp4", "inicio_ms": 1794509121560}
        nombre = item.get("archivo", "") if isinstance(item, dict) else item
        ruta = d / Path(nombre).name
        if not nombre or not ruta.exists():
            continue
        fps, total, dur = info_video(ruta)
        if isinstance(item, dict) and item.get("inicio_ms"):
            inicio, origen = int(item["inicio_ms"]), "inicio_ms de resumen.json"
        elif n < len(starts):
            inicio, origen = starts[n]["ts_ms"], f"evento VIDEO_START ({starts[n]['detalle']})"
        else:   # sin evento: se estima con la fecha del archivo (menos preciso)
            inicio, origen = int(ruta.stat().st_mtime * 1000 - dur * 1000), "estimado por fecha del archivo"
        videos.append({"ruta": ruta, "nombre": f"{d.name}/{nombre}", "inicio_ms": inicio,
                       "fin_ms": inicio + int(dur * 1000), "duracion_s": round(dur, 1),
                       "origen_inicio": origen,
                       "fin_registrado_ms": stops.get(starts[n]["detalle"]) if n < len(starts) else None})
    return {"id": resumen.get("flight_id", d.name), "dir": d, "resumen": resumen,
            "filas": filas, "eventos": eventos, "videos": videos,
            "es_vuelo": d.name.startswith("vuelo_") or any(e["evento"] == "FLIGHT_START" for e in eventos)}


def cargar_mision(dir_mision) -> list[dict]:
    dir_mision = Path(dir_mision)
    sesiones = [cargar_sesion(d) for d in sorted(dir_mision.iterdir())
                if d.is_dir() and (d / "resumen.json").exists()]
    return sorted(sesiones, key=lambda s: s["resumen"].get("started_at_ms", 0))


def intervalo_vuelo(s) -> tuple[int, int]:
    ev = {e["evento"]: e["ts_ms"] for e in s["eventos"]}
    return (ev.get("FLIGHT_START", s["resumen"].get("started_at_ms")),
            ev.get("FLIGHT_END", s["resumen"].get("last_seen_ms")))


def preparar_vuelo(sesiones, vuelo_id) -> dict:
    """Junta lo necesario para analizar un vuelo: ventana, telemetría, videos que lo cubren, datos."""
    s = next(x for x in sesiones if x["id"] == vuelo_id)
    ini, fin = intervalo_vuelo(s)
    todas = [f for x in sesiones for f in x["filas"]]
    muestras = asignar_tramos([m for m in muestras_desde_filas(todas)
                               if ini - MARGEN_MS <= m.ts_ms <= fin + MARGEN_MS])

    videos = [v for x in sesiones for v in x["videos"] if v["inicio_ms"] < fin and v["fin_ms"] > ini]
    cubierto = sum(min(v["fin_ms"], fin) - max(v["inicio_ms"], ini) for v in videos)

    vuelo_filas = [f for f in s["filas"] if f.get("event") == "TELEMETRY"]

    def num(f, k):
        try:
            return float(f.get(k) or "nan")
        except ValueError:
            return float("nan")

    bat = [num(f, "battery_pct") for f in vuelo_filas]
    bat = [b for b in bat if b == b]
    alts = [num(f, "altitude_m") for f in vuelo_filas]
    alts = [a for a in alts if a == a]
    vel = [num(f, "speed_mps") for f in vuelo_filas]
    vel = [v for v in vel if v == v]
    con_gps = sum(1 for f in vuelo_filas if f.get("latitude") not in (None, ""))
    datos = {
        "vuelo_id": vuelo_id, "modelo_dron": s["resumen"].get("drone_model"),
        "inicio_ms": ini, "fin_ms": fin, "duracion_s": round((fin - ini) / 1000, 1),
        "terminado": s["resumen"].get("ended"),
        "altitud_max_m": round(max(alts), 1) if alts else None,
        "velocidad_max_mps": round(max(vel), 2) if vel else None,
        "bateria_inicio_pct": bat[0] if bat else None, "bateria_fin_pct": bat[-1] if bat else None,
        "muestras_telemetria": len(vuelo_filas),
        "pct_muestras_con_gps": round(100 * con_gps / len(vuelo_filas), 1) if vuelo_filas else 0.0,
        "pct_vuelo_con_video": round(100 * cubierto / max(fin - ini, 1), 1),
        "videos": [{k: v[k] for k in ("nombre", "inicio_ms", "duracion_s", "origen_inicio")} for v in videos],
        "eventos": [{"t_vuelo_s": round((e["ts_ms"] - ini) / 1000, 1), "evento": e["evento"],
                     "detalle": e["detalle"]} for e in s["eventos"]],
        "errores_app": s["resumen"].get("errors", []),
    }
    return {"sesion": s, "ventana": (ini, fin), "muestras": muestras, "videos": videos, "datos": datos}


EVENTOS_ALERTA = {"LANDING_ERROR", "MANUAL_STOP", "MISSION_STOPPED"}


def seccion_markdown(d) -> str:
    """Bloque 'Datos del vuelo' del informe (sin LLM: datos tal cual)."""
    def v(x, suf=""):
        return "sin dato" if x is None else f"{x}{suf}"
    lineas = [
        "## Datos del vuelo",
        f"- Vuelo: `{d['vuelo_id']}` · dron {v(d['modelo_dron'])}",
        f"- Duración en el aire: {d['duracion_s']} s · altitud máx. {v(d['altitud_max_m'], ' m')}"
        f" · velocidad máx. {v(d['velocidad_max_mps'], ' m/s')}",
        f"- Batería: {v(d['bateria_inicio_pct'], ' %')} → {v(d['bateria_fin_pct'], ' %')}",
        f"- Telemetría: {d['muestras_telemetria']} muestras, {d['pct_muestras_con_gps']} % con GPS",
        f"- Video que cubre el vuelo: {d['pct_vuelo_con_video']} % "
        f"({', '.join(x['nombre'] for x in d['videos']) or 'ninguno'})",
    ]
    alertas = [e for e in d["eventos"] if e["evento"] in EVENTOS_ALERTA]
    if alertas:
        lineas.append("- **Incidencias registradas por la app:**")
        lineas += [f"  - t={e['t_vuelo_s']} s · {e['evento']} {e['detalle']}".rstrip() for e in alertas]
    if d["pct_muestras_con_gps"] < 50:
        lineas.append("\n> Sin GPS en la mayor parte del vuelo: las posiciones de los hallazgos "
                      "figuran como \"sin dato\".")
    if d["pct_vuelo_con_video"] < 90:
        lineas.append("\n> El video no cubre todo el vuelo: los tramos sin video no se evaluaron.")
    return "\n".join(lineas)
