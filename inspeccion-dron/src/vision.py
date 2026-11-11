"""Visión: detección de obstáculos/personas con YOLOv8 y clasificación del terreno."""
from collections import Counter

import cv2
import numpy as np
from ultralytics import YOLO

import config


def terreno_heuristico(frame):
    """Plan B sin modelo entrenado: % de píxeles con color de arena (HSV).
    Solo distingue 'arenoso' de 'otro'. NO puede detectar 'inestable'."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # En OpenCV el matiz va de 0 a 179: 10-35 ≈ amarillo/anaranjado (arena)
    mascara = cv2.inRange(hsv, (10, 30, 100), (35, 160, 255))
    proporcion = float(np.count_nonzero(mascara)) / mascara.size
    if proporcion >= 0.45:
        return "arenoso", proporcion, "heuristico"
    return "otro", 1.0 - proporcion, "heuristico"


class Analizador:
    def __init__(self):
        if config.RUTA_DETECTOR.exists():
            self.detector = YOLO(str(config.RUTA_DETECTOR))
            self.detector_propio = True
        else:
            print("AVISO: no hay detector propio; se usa yolov8n.pt (COCO: solo personas, vehículos...).")
            self.detector = YOLO("yolov8n.pt")        # se descarga solo la primera vez (~6 MB)
            self.detector_propio = False

        self.clasificador = None
        if config.RUTA_CLASIFICADOR.exists():
            self.clasificador = YOLO(str(config.RUTA_CLASIFICADOR))
        else:
            print("AVISO: no hay clasificador de terreno; se usa la heurística de color.")

    def analizar(self, frame) -> dict:
        r = self.detector.predict(frame, imgsz=config.IMG_SIZE,
                                  conf=config.CONF_MIN, verbose=False)[0]
        conteo, conf_max = Counter(), 0.0
        for caja in r.boxes:
            nombre = r.names[int(caja.cls[0])].lower()
            conteo[nombre] += 1
            conf_max = max(conf_max, float(caja.conf[0]))

        n_obst = sum(n for c, n in conteo.items() if c in config.CLASES_OBSTACULO)
        n_pers = sum(n for c, n in conteo.items() if c in config.CLASES_PERSONA)
        n_veh = sum(n for c, n in conteo.items() if c in config.CLASES_VEHICULO)
        terreno, t_conf, metodo = self._terreno(frame)
        hay_algo = (n_obst + n_pers + n_veh) > 0
        return {
            "conteo": dict(conteo),
            "n_obstaculos": n_obst,
            "n_personas": n_pers,
            "n_vehiculos": n_veh,
            "aglomeracion": n_pers >= config.UMBRAL_AGLOMERACION,   # regla de negocio
            "conf_max": conf_max,
            "terreno": terreno, "terreno_conf": t_conf, "terreno_metodo": metodo,
            "anotado": r.plot() if hay_algo else None,   # imagen con cajas (solo si hay hallazgos)
        }

    def _terreno(self, frame):
        if self.clasificador is None:
            return terreno_heuristico(frame)
        r = self.clasificador.predict(frame, imgsz=224, verbose=False)[0]
        return r.names[int(r.probs.top1)].lower(), float(r.probs.top1conf), "modelo"