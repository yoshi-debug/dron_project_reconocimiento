"""Configuración central del proyecto. Si quieres cambiar un umbral, se cambia aquí."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()                                   # lee el archivo .env

RAIZ = Path(__file__).resolve().parent
DIR_ENTRADA = RAIZ / "data" / "entrada"
DIR_SALIDA = RAIZ / "salida"
DIR_MODELOS = RAIZ / "modelos"

# ---------- Muestreo ----------
FPS_MUESTREO = 1.0            # fotogramas por segundo que se analizan

# ---------- Modelos ----------
# Si el archivo no existe, el detector usa yolov8n.pt (COCO) y el terreno una heurística de color.
RUTA_DETECTOR = DIR_MODELOS / "detector_obstaculos.pt"
RUTA_CLASIFICADOR = DIR_MODELOS / "clasificador_terreno.pt"
CONF_MIN = 0.25               # confianza mínima para aceptar una detección
IMG_SIZE = 640                # tamaño de entrada de YOLO

# ---------- Qué cuenta como obstáculo / persona (nombres de clase en minúsculas) ----------
CLASES_OBSTACULO = {"roca", "rock", "stone", "boulder", "debris", "escombro"}
CLASES_PERSONA = {"person", "persona"}
UMBRAL_AGLOMERACION = 3       # >= N personas en un fotograma = aglomeración

# ---------- Reglas de riesgo por tramo ----------
RIESGO_ALTO_ROCAS_MAX = 5     # rocas en un solo fotograma
RIESGO_ALTO_PCT_INESTABLE = 30.0   # % de fotogramas con terreno inestable

# ---------- LLM ----------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
MODELO_GEMINI = os.getenv("MODELO_GEMINI", "gemini-2.5-flash")
MODELO_GROQ = os.getenv("MODELO_GROQ", "llama-3.3-70b-versatile")
PAUSA_ENTRE_LLAMADAS_S = 5    # respeta los límites por minuto del plan gratuito