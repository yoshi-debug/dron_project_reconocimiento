"""Genera un video de 60 s y su telemetría (3 tramos de 20 s) con un desfase intencional
de 2 s entre telemetría y video, para comprobar que la sincronización funciona."""
import csv, json, sys
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

config.DIR_ENTRADA.mkdir(parents=True, exist_ok=True)
NOMBRE = "vuelo_demo"
DURACION_S, FPS, ANCHO, ALTO = 60, 30, 640, 480
INICIO_VIDEO_MS = 1_760_000_000_000           # instante en que "empezó" el video

# ---------- 1) Video sintético ----------
rng = np.random.default_rng(42)
escritor = cv2.VideoWriter(str(config.DIR_ENTRADA / f"{NOMBRE}.mp4"),
                           cv2.VideoWriter_fourcc(*"mp4v"), FPS, (ANCHO, ALTO))
for i in range(DURACION_S * FPS):
    t = i / FPS
    # Fondo arenoso (BGR) con ruido para que no sea plano
    fondo = np.full((ALTO, ANCHO, 3), (150, 190, 215), np.uint8)
    ruido = rng.integers(-12, 12, (ALTO, ANCHO, 1), dtype=np.int16)
    cuadro = np.clip(fondo.astype(np.int16) + ruido, 0, 255).astype(np.uint8)
    # "Rocas" grises entre los segundos 25 y 45 (tramos 2 y parte del 3)
    if 25 <= t <= 45:
        for k in range(4):
            cx = int((120 + 140 * k + 20 * t) % ANCHO)
            cv2.ellipse(cuadro, (cx, 240 + 30 * (k % 2)), (28, 20), 0, 0, 360, (110, 110, 110), -1)
    escritor.write(cuadro)
escritor.release()

# ---------- 2) Telemetría a 5 Hz, empezando 2 s ANTES que el video ----------
INICIO_TEL_MS = INICIO_VIDEO_MS - 2000
filas = []
for n in range((DURACION_S + 4) * 5):
    ts = INICIO_TEL_MS + n * 200
    seg_video = (ts - INICIO_VIDEO_MS) / 1000
    tramo = int(min(max(seg_video, 0) // 20, 2)) + 1          # 1, 2 ó 3
    filas.append({"timestamp_ms": ts,
                  "lat": round(-12.000000 - 0.000010 * n, 6),
                  "lon": round(-77.000000 + 0.000004 * n, 6),
                  "alt_m": round(30 + 0.5 * np.sin(n / 10), 2),
                  "tramo_id": tramo})
with open(config.DIR_ENTRADA / f"{NOMBRE}_telemetria.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=filas[0].keys())
    w.writeheader(); w.writerows(filas)

# ---------- 3) Metadatos ----------
json.dump({"video_start_epoch_ms": INICIO_VIDEO_MS},
          open(config.DIR_ENTRADA / f"{NOMBRE}_meta.json", "w"))
print("Datos de prueba creados en", config.DIR_ENTRADA)