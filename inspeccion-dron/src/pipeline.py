"""Pipeline completo como funciones reutilizables (lo usan los scripts CLI y el servidor).

Etapa 1  procesar_video():   video + telemetría -> resultados_frames.csv + info_corrida.json
Etapa 2  generar_reporte():  resultados_frames.csv -> resumen_tramos.json -> reporte.md
"""
import json
import time
from datetime import date
from pathlib import Path

import cv2
import pandas as pd

import config
from src.agregacion import resumir_por_tramo
from src.frames import extraer_frames, info_video
from src.reporte import (ErrorLLM, informe_determinista, redactar_resumen,
                         redactar_tramo)
from src.telemetria import LineaTemporal, cargar_telemetria

TIPOS_RUTA = {
    "a_pie": "a pie (peatonal)",
    "vehiculo": "en vehículo / transporte",
    "general": "general (a pie y en vehículo)",
}


def _nada(*_args, **_kw):
    pass


def instante_inicio_video(meta, inicio_ms, linea):
    """Decide cuándo empezó el video (ms epoch) y de dónde salió el dato.
    `meta` puede ser una ruta a JSON o un dict ya cargado."""
    if inicio_ms is not None:
        return int(inicio_ms), "valor explícito de inicio"
    if isinstance(meta, (str, Path)) and Path(meta).exists():
        meta = json.loads(Path(meta).read_text(encoding="utf-8"))
    if isinstance(meta, dict) and meta.get("video_start_epoch_ms") is not None:
        return int(meta["video_start_epoch_ms"]), "archivo meta.json"
    print("AVISO: no hay video_start_epoch_ms; se SUPONE que el video empieza con la 1.ª muestra "
          "de telemetría. Verifica la sincronización o usa offset.")
    return linea.inicio_ms, "supuesto: primera muestra de telemetría"


def _r(x, n):
    return None if x is None else round(x, n)


def procesar_segmentos(segmentos, muestras, dir_salida, ventana=None, analizador=None,
                       progreso=_nada, extra_info=None):
    """Etapa 1 general. `segmentos`: lista de {"ruta", "inicio_ms", "nombre", "origen_inicio"}.
    Cada video se sincroniza con su propio inicio. Si hay `ventana=(desde_ms, hasta_ms)` solo se
    analizan los fotogramas dentro de ella (p. ej. solo mientras el dron está en el aire)."""
    from src.vision import Analizador          # import tardío: carga torch/ultralytics

    dir_salida = Path(dir_salida)
    (dir_salida / "frames").mkdir(parents=True, exist_ok=True)
    linea = LineaTemporal(muestras)
    analizador = analizador or Analizador()

    infos, esperados = [], 0
    for s in segmentos:
        fps, total, dur = info_video(s["ruta"])
        if total <= 0:
            raise ValueError(f"El video {s['nombre']} no tiene fotogramas legibles.")
        ini, fin = s["inicio_ms"], s["inicio_ms"] + dur * 1000
        if ventana:
            ini, fin = max(ini, ventana[0]), min(fin, ventana[1])
        esperados += max(0, int((fin - ini) / 1000 * config.FPS_MUESTREO))
        infos.append({"video": s["nombre"], "fps": fps, "duracion_s": round(dur, 2),
                      "inicio_ms": s["inicio_ms"], "origen_inicio": s.get("origen_inicio", "")})
        print(f"Video {s['nombre']}: {fps:.1f} fps, {dur:.1f} s | inicio por: {s.get('origen_inicio')}")
    esperados = max(esperados, 1)

    filas = []
    for s in segmentos:
        pref = Path(s["nombre"]).stem
        for idx, t_s, frame in extraer_frames(s["ruta"], config.FPS_MUESTREO):
            ts_ms = s["inicio_ms"] + int(t_s * 1000)         # ← LA FUSIÓN POR TIMESTAMP
            if ventana and not (ventana[0] <= ts_ms <= ventana[1]):
                continue
            tel = linea.en(ts_ms)
            res = analizador.analizar(frame)
            ruta_img = ""
            if res["anotado"] is not None:
                ruta_img = f"frames/{pref}_f{idx:06d}.jpg"
                cv2.imwrite(str(dir_salida / ruta_img), res["anotado"])
            filas.append({
                "video": s["nombre"], "frame_idx": idx, "t_video_s": round(t_s, 2), "ts_ms": ts_ms,
                "t_vuelo_s": round((ts_ms - ventana[0]) / 1000, 1) if ventana else round(t_s, 1),
                "lat": _r(tel["lat"], 7), "lon": _r(tel["lon"], 7),
                "alt_m": _r(tel["alt_m"], 2), "tramo_id": tel["tramo_id"],
                "telemetria_fuera_de_rango": tel["fuera_de_rango"], "brecha_ms": tel["brecha_ms"],
                "sin_gps": tel["sin_gps"],
                "n_obstaculos": res["n_obstaculos"], "n_personas": res["n_personas"],
                "n_vehiculos": res["n_vehiculos"],
                "aglomeracion": res["aglomeracion"], "conf_max": round(res["conf_max"], 3),
                "conteo": json.dumps(res["conteo"], ensure_ascii=False),
                "terreno": res["terreno"], "terreno_conf": round(res["terreno_conf"], 3),
                "terreno_metodo": res["terreno_metodo"], "imagen": ruta_img,
            })
            if len(filas) % 10 == 0:
                progreso(min(len(filas) / esperados, 0.99), f"{len(filas)} fotogramas analizados")

    if not filas:
        raise ValueError("Ningún fotograma del video cae dentro del vuelo (revisa la sincronía).")

    df = pd.DataFrame(filas)
    df.to_csv(dir_salida / "resultados_frames.csv", index=False, encoding="utf-8")
    fuera = int(df["telemetria_fuera_de_rango"].sum())
    info = {"video": ", ".join(i["video"] for i in infos), "videos": infos,
            "fotogramas_analizados": len(df), "fotogramas_fuera_de_telemetria": fuera,
            "fotogramas_sin_gps": int(df["sin_gps"].sum()),
            "detector_propio": analizador.detector_propio,
            "clasificador_propio": analizador.clasificador is not None, **(extra_info or {})}
    (dir_salida / "info_corrida.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    if fuera:
        print(f"AVISO: {fuera} fotogramas caen FUERA del rango de telemetría: revisa el offset.")
    progreso(1.0, f"{len(df)} fotogramas analizados")
    return info


def procesar_video(video, telemetria, dir_salida, meta=None, inicio_ms=None, offset_ms=0,
                   analizador=None, progreso=_nada, nombre_video=None):
    """Etapa 1 para un solo video + telemetría (formato simple)."""
    video = Path(video)
    muestras = cargar_telemetria(telemetria)
    inicio, origen = instante_inicio_video(meta, inicio_ms, LineaTemporal(muestras))
    seg = {"ruta": video, "inicio_ms": inicio + offset_ms, "nombre": nombre_video or video.name,
           "origen_inicio": origen}
    return procesar_segmentos([seg], muestras, dir_salida, analizador=analizador, progreso=progreso,
                              extra_info={"offset_ms": offset_ms, "origen_inicio_video": origen})


def generar_reporte(dir_salida, tipo_ruta="general", usar_llm=True, progreso=_nada,
                    titulo=None, seccion_vuelo=""):
    """Etapa 2. Si el LLM falla o no hay clave, escribe un informe determinista (sin IA generativa).
    `seccion_vuelo`: Markdown con datos del vuelo (eventos, batería...) que se añade al informe."""
    dir_salida = Path(dir_salida)
    df = pd.read_csv(dir_salida / "resultados_frames.csv")
    tramos = resumir_por_tramo(df)
    (dir_salida / "resumen_tramos.json").write_text(
        json.dumps(tramos, ensure_ascii=False, indent=2), encoding="utf-8")

    ruta_info = dir_salida / "info_corrida.json"
    info = json.loads(ruta_info.read_text(encoding="utf-8")) if ruta_info.exists() else {}
    desc_ruta = TIPOS_RUTA.get(tipo_ruta, TIPOS_RUTA["general"])

    metodo, aviso = "llm", ""
    try:
        if not usar_llm:
            raise ErrorLLM("LLM desactivado")
        textos = []
        for n, t in enumerate(tramos, 1):
            progreso((n - 1) / (len(tramos) + 1), f"Redactando tramo {t['tramo_id']}")
            textos.append(redactar_tramo(t, desc_ruta))
            if n < len(tramos):
                time.sleep(config.PAUSA_ENTRE_LLAMADAS_S)
        progreso(len(tramos) / (len(tramos) + 1), "Redactando resumen ejecutivo")
        resumen = redactar_resumen(textos, desc_ruta, contexto=seccion_vuelo)
    except ErrorLLM as e:
        metodo, aviso = "determinista", str(e)
        print(f"AVISO: informe sin LLM ({e}).")
        resumen, textos = informe_determinista(tramos, desc_ruta)

    cabecera = (f"# {titulo or 'Informe de reconocimiento de ruta con dron'}\n\n"
                f"- Fecha del informe: {date.today()}\n"
                f"- Tipo de ruta evaluada: {desc_ruta}\n"
                f"- Video: {info.get('video', 'sin dato')}\n"
                f"- Fotogramas analizados: {len(df)}\n- Tramos: {len(tramos)}")
    if metodo == "determinista":
        cabecera += ("\n\n> Nota: este informe se generó con reglas automáticas, sin redacción por IA "
                     f"generativa ({aviso}).")
    partes = [cabecera, "## Resumen ejecutivo", resumen]
    if seccion_vuelo:
        partes.append(seccion_vuelo)
    md = "\n\n".join(partes + textos)
    (dir_salida / "reporte.md").write_text(md, encoding="utf-8")
    progreso(1.0, "Informe listo")
    return {"metodo_informe": metodo, "aviso_informe": aviso,
            "niveles_riesgo": {t["tramo_id"]: t["nivel_riesgo"] for t in tramos}}
