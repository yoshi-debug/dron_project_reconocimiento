"""Prompts y llamada al LLM gratuito (Gemini o Groq)."""
import json
import os
import time

import config

SYSTEM_PROMPT = """Eres un ingeniero de inspección que redacta informes técnicos en español.
REGLAS:
1. Usa EXCLUSIVAMENTE los datos del JSON recibido. Si falta un dato, escribe "sin dato".
2. No inventes causas, cifras ni coordenadas. Coordenadas con 6 decimales.
3. Las detecciones son automáticas y pueden contener falsos positivos o negativos;
   si "metodo_terreno" es "heuristico", indica que el terreno es una estimación por color.
4. Respeta el "nivel_riesgo" entregado; no lo recalcules.
5. Responde en Markdown con EXACTAMENTE esta estructura y máximo 180 palabras:
## Tramo {tramo_id} - Riesgo: {nivel_riesgo}
**Resumen:** (2 a 3 frases)
**Hallazgos:** (viñetas con segundo del video, lat/lon y cantidad detectada)
**Terreno:** (distribución en porcentaje)
**Recomendación:** (1 a 2 acciones concretas)
**Confianza de los datos:** (limitaciones observadas)"""

SYSTEM_RESUMEN = """Eres un ingeniero de inspección. Recibes los informes por tramo de un vuelo.
Escribe un RESUMEN EJECUTIVO en español de máximo 150 palabras: ordena los tramos de mayor a
menor riesgo, destaca los hallazgos críticos y no agregues información que no esté en los textos."""


def llamar_gemini(sistema, usuario):
    from google import genai
    from google.genai import types
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    r = cliente.models.generate_content(
        model=config.MODELO_GEMINI, contents=usuario,
        config=types.GenerateContentConfig(system_instruction=sistema,
                                           temperature=0.2, max_output_tokens=1500))
    return r.text


def llamar_groq(sistema, usuario):
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    r = cliente.chat.completions.create(
        model=config.MODELO_GROQ, temperature=0.2, max_tokens=1500,
        messages=[{"role": "system", "content": sistema},
                  {"role": "user", "content": usuario}])
    return r.choices[0].message.content


def con_reintentos(fn, intentos=4):
    for i in range(intentos):
        try:
            return fn()
        except Exception as e:
            espera = 5 * 2 ** i
            print(f"Fallo de la API ({e}); reintento en {espera} s")
            time.sleep(espera)
    raise RuntimeError("La API no respondió tras varios intentos")


def _llamar(sistema, usuario):
    f = llamar_gemini if config.LLM_PROVIDER == "gemini" else llamar_groq
    return con_reintentos(lambda: f(sistema, usuario))


def redactar_tramo(tramo):
    return _llamar(SYSTEM_PROMPT, "Datos del tramo:\n" + json.dumps(tramo, ensure_ascii=False, indent=2))


def redactar_resumen(textos):
    return _llamar(SYSTEM_RESUMEN, "\n\n".join(textos))
