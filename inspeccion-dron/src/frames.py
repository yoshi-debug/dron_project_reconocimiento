"""Extracción de fotogramas a una tasa fija (por defecto 1 por segundo)."""
import cv2


def info_video(ruta):
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {ruta}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, total, total / fps


def extraer_frames(ruta, fps_muestreo=1.0):
    """Generador: entrega (índice_de_frame, segundo_dentro_del_video, imagen_BGR)."""
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise FileNotFoundError(f"No se pudo abrir el video: {ruta}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    paso = max(1, round(fps / fps_muestreo))     # cada cuántos frames tomar uno (30 fps -> 30)
    idx = 0
    try:
        while True:
            if not cap.grab():                   # avanza un frame SIN decodificarlo (rápido)
                break
            if idx % paso == 0:
                ok, frame = cap.retrieve()       # solo decodificamos los que usamos
                if ok:
                    yield idx, idx / fps, frame
            idx += 1
    finally:
        cap.release()