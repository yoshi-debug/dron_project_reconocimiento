"""Paso 1: video + telemetría -> resultados_frames.csv (+ imágenes anotadas)."""
import argparse
import json
from pathlib import Path

import cv2
import pandas as pd

import config
from src.frames import extraer_frames, info_video
from src.telemetria import LineaTemporal, cargar_telemetria
from src.vision import Analizador


def instante_inicio_video(ruta_meta, inicio_cli, linea):
    """Decide cuándo empezó el video (en ms epoch) y dice de dónde salió el dato."""
    if inicio_cli is not None:
        return inicio_cli, "argumento --inicio-ms"
    if ruta_meta and Path(ruta_meta).exists():
        meta = json.loads(Path(ruta_meta).read_text(encoding="utf-8"))
        return int(meta["video_start_epoch_ms"]), "archivo meta.json"
    print("AVISO: no hay video_start_epoch_ms; se SUPONE que el video empieza con la 1.ª muestra "
          "de telemetría. Verifica la sincronización o usa --offset-ms.")
    return linea.inicio_ms, "supuesto: primera muestra de telemetría"


def main():
    ap = argparse.ArgumentParser(description="Procesa un video de dron y lo fusiona con su telemetría")
    ap.add_argument("--video", required=True)
    ap.add_argument("--telemetria", required=True)
    ap.add_argument("--meta", help="JSON con video_start_epoch_ms")
    ap.add_argument("--inicio-ms", type=int, help="Instante de inicio del video (epoch ms)")
    ap.add_argument("--offset-ms", type=int, default=0, help="Corrección manual de sincronía (+/- ms)")
    ap.add_argument("--salida", help="Carpeta de salida (por defecto salida/<nombre_video>)")
    args = ap.parse_args()

    video = Path(args.video)
    dir_salida = Path(args.salida) if args.salida else config.DIR_SALIDA / video.stem
    (dir_salida / "frames").mkdir(parents=True, exist_ok=True)

    linea = LineaTemporal(cargar_telemetria(args.telemetria))
    inicio_ms, origen_inicio = instante_inicio_video(args.meta, args.inicio_ms, linea)
    fps, total, duracion = info_video(video)
    print(f"Video: {fps:.1f} fps, {total} frames, {duracion:.1f} s | inicio por: {origen_inicio}")
    print(f"Telemetría: {len(linea.muestras)} muestras | video = {inicio_ms + args.offset_ms} ms "
          f"(telemetría cubre {linea.inicio_ms} → {linea.fin_ms})")

    analizador = Analizador()
    filas = []
    for idx, t_s, frame in extraer_frames(video, config.FPS_MUESTREO):
        ts_ms = inicio_ms + int(t_s * 1000) + args.offset_ms     # ← LA FUSIÓN POR TIMESTAMP
        tel = linea.en(ts_ms)
        res = analizador.analizar(frame)

        ruta_img = ""
        if res["anotado"] is not None:
            ruta_img = f"frames/f{idx:06d}.jpg"
            cv2.imwrite(str(dir_salida / ruta_img), res["anotado"])

        filas.append({
            "frame_idx": idx, "t_video_s": round(t_s, 2), "ts_ms": ts_ms,
            "lat": round(tel["lat"], 7), "lon": round(tel["lon"], 7),
            "alt_m": round(tel["alt_m"], 2), "tramo_id": tel["tramo_id"],
            "telemetria_fuera_de_rango": tel["fuera_de_rango"], "brecha_ms": tel["brecha_ms"],
            "n_obstaculos": res["n_obstaculos"], "n_personas": res["n_personas"],
            "aglomeracion": res["aglomeracion"], "conf_max": round(res["conf_max"], 3),
            "conteo": json.dumps(res["conteo"], ensure_ascii=False),
            "terreno": res["terreno"], "terreno_conf": round(res["terreno_conf"], 3),
            "terreno_metodo": res["terreno_metodo"], "imagen": ruta_img,
        })
        if len(filas) % 10 == 0:
            print(f"  {len(filas)} fotogramas analizados (t = {t_s:.0f} s)")

    df = pd.DataFrame(filas)
    df.to_csv(dir_salida / "resultados_frames.csv", index=False, encoding="utf-8")
    json.dump({"video": video.name, "fps": fps, "duracion_s": duracion,
               "origen_inicio_video": origen_inicio, "offset_ms": args.offset_ms,
               "detector_propio": analizador.detector_propio,
               "clasificador_propio": analizador.clasificador is not None},
              open(dir_salida / "info_corrida.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    fuera = int(df["telemetria_fuera_de_rango"].sum())
    print(f"\nListo: {len(df)} filas -> {dir_salida / 'resultados_frames.csv'}")
    if fuera:
        print(f"AVISO: {fuera} fotogramas caen FUERA del rango de telemetría: revisa --offset-ms.")
    print(df[["t_video_s", "lat", "lon", "tramo_id", "n_obstaculos", "terreno"]].head())


if __name__ == "__main__":
    main()