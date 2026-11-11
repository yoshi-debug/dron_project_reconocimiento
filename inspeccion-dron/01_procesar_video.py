"""Paso 1: video + telemetría -> resultados_frames.csv (+ imágenes anotadas)."""
import argparse
from pathlib import Path

import config
from src.pipeline import procesar_video


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
    info = procesar_video(video, args.telemetria, dir_salida, meta=args.meta,
                          inicio_ms=args.inicio_ms, offset_ms=args.offset_ms,
                          progreso=lambda f, m: print(f"  {m} ({f:.0%})"))
    print(f"\nListo: {info['fotogramas_analizados']} filas -> {dir_salida / 'resultados_frames.csv'}")


if __name__ == "__main__":
    main()
