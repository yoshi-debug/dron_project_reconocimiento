"""Genera un vuelo sintético de demostración: video + telemetría (CSV y JSON) + meta.

Ruta de 60 s dividida en 4 tramos de 15 s, pensada para que el sistema muestre resultados distintos:
  Tramo 1 (0-15 s)   sendero arenoso despejado               -> riesgo bajo
  Tramo 2 (15-30 s)  pasa un peatón (con un trozo de bus)     -> 1 persona + vehículo, riesgo bajo
  Tramo 3 (30-45 s)  grupo de personas junto a un bus         -> aglomeración + vehículo, riesgo ALTO
  Tramo 4 (45-60 s)  suelo pedregoso gris con rocas           -> terreno 'otro'; COCO NO detecta las rocas

Las personas y el bus salen de la imagen de ejemplo que trae Ultralytics (bus.jpg),
porque YOLO-COCO no detecta figuras dibujadas a mano. Es un escenario de prueba, no un vuelo real.

Uso (desde inspeccion-dron/):
    venv/bin/python tools/generar_escenario_demo.py
Salida: data/demo/ruta_demo.mp4, ruta_demo_telemetria.csv, ruta_demo_telemetria.json, ruta_demo_meta.json
"""
import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
DIR = RAIZ / "data" / "demo"
NOMBRE = "ruta_demo"
DURACION_S, FPS, ANCHO, ALTO = 60, 30, 640, 480
INICIO_VIDEO_MS = 1_762_000_000_000            # instante (epoch ms) en que "empieza" a grabar
TRAMO_S = 15


def imagen_ultralytics(nombre):
    import ultralytics
    ruta = Path(ultralytics.__file__).parent / "assets" / nombre
    img = cv2.imread(str(ruta))
    if img is None:
        sys.exit(f"No se encontró {ruta}; reinstala ultralytics.")
    return img


def ajustar(img, alto):
    return cv2.resize(img, (int(img.shape[1] * alto / img.shape[0]), alto))


def pegar(fondo, img, x, y):
    """Pega img en fondo con esquina superior izquierda (x, y), recortando bordes."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, ANCHO), min(y + h, ALTO)
    if x0 < x1 and y0 < y1:
        fondo[y0:y1, x0:x1] = img[y0 - y:y1 - y, x0 - x:x1 - x]


def textura(color, semilla, gruesa=False):
    rng = np.random.default_rng(semilla)
    base = np.full((ALTO * 2, ANCHO, 3), color, np.int16)
    ruido = rng.integers(-14, 14, (ALTO * 2 // 4, ANCHO // 4, 1)).astype(np.int16)
    ruido = cv2.resize(ruido.astype(np.float32), (ANCHO, ALTO * 2))[..., None].astype(np.int16)
    if gruesa:
        ruido = ruido * 2
    return np.clip(base + ruido, 0, 255).astype(np.uint8)


def generar_video(ruta):
    arena = textura((140, 185, 215), 1)          # BGR arenoso
    tierra = textura((112, 118, 116), 2, True)   # tramo de rocas: suelo gris pedregoso
    foto = imagen_ultralytics("bus.jpg")
    peaton = ajustar(foto[380:910, 655:810], 260)  # recorte de un solo peatón
    bus = ajustar(foto, 440)
    rng = np.random.default_rng(7)
    rocas = [(int(rng.integers(30, ANCHO - 30)), int(rng.integers(0, ALTO * 2)),
              int(rng.integers(14, 34))) for _ in range(14)]

    tmp = ruta.with_suffix(".tmp.mp4")
    out = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (ANCHO, ALTO))
    for i in range(DURACION_S * FPS):
        t = i / FPS
        tramo = int(t // TRAMO_S) + 1
        desp = int(t * 40) % ALTO                       # el "dron" avanza: el suelo se desplaza
        fondo = (tierra if tramo == 4 else arena)[desp:desp + ALTO].copy()
        cv2.line(fondo, (ANCHO // 2, 0), (ANCHO // 2, ALTO), (120, 160, 190), 60)   # sendero

        local = t - (tramo - 1) * TRAMO_S               # segundo dentro del tramo
        if tramo == 2 and 2 <= local <= 13:
            pegar(fondo, peaton, ANCHO // 2 + 40, int(-260 + local * 45))
        elif tramo == 3 and 1 <= local <= 14:
            pegar(fondo, bus, ANCHO // 2 - bus.shape[1] // 2, int(-200 + local * 35))
        elif tramo == 4:
            for (x, y, r) in rocas:
                yy = (y + desp) % (ALTO * 2) - ALTO // 2
                cv2.ellipse(fondo, (x, yy), (r, int(r * .7)), 0, 0, 360, (105, 105, 105), -1)
        cv2.putText(fondo, f"t={t:4.1f}s tramo {tramo}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, .6, (30, 30, 30), 2)
        out.write(fondo)
    out.release()

    # Re-codifica a H.264 si hay ffmpeg (archivo mucho más pequeño y reproducible en el celular)
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(tmp), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "26", "-movflags", "+faststart", str(ruta)])
        if r.returncode == 0:
            tmp.unlink()
            return
    tmp.replace(ruta)


def generar_telemetria():
    """5 Hz, empieza 2 s antes y termina 2 s después del video. Ruta curva con subida leve."""
    filas, inicio = [], INICIO_VIDEO_MS - 2000
    for n in range((DURACION_S + 4) * 5):
        ts = inicio + n * 200
        s = (ts - INICIO_VIDEO_MS) / 1000
        sc = min(max(s, 0), DURACION_S - 0.001)
        filas.append({
            "timestamp_ms": ts,
            "lat": round(-16.398800 - 0.0000250 * s, 7),                       # Arequipa aprox.
            "lon": round(-71.536900 + 0.0000180 * s + 0.00012 * math.sin(s / 12), 7),
            "alt_m": round(40 + 0.15 * s + 0.6 * math.sin(s / 5), 2),
            "tramo_id": int(sc // TRAMO_S) + 1,
        })
    return filas


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    print("Generando video (unos segundos)...")
    generar_video(DIR / f"{NOMBRE}.mp4")
    filas = generar_telemetria()
    with open(DIR / f"{NOMBRE}_telemetria.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=filas[0].keys())
        w.writeheader()
        w.writerows(filas)
    (DIR / f"{NOMBRE}_telemetria.json").write_text(json.dumps(filas), encoding="utf-8")
    (DIR / f"{NOMBRE}_meta.json").write_text(
        json.dumps({"video_start_epoch_ms": INICIO_VIDEO_MS}), encoding="utf-8")
    mb = (DIR / f"{NOMBRE}.mp4").stat().st_size / 1e6
    print(f"Listo en {DIR}: video {mb:.1f} MB, {len(filas)} muestras de telemetría, 4 tramos.")


if __name__ == "__main__":
    main()
