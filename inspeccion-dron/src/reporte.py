"""Prompts y llamada al LLM gratuito (Gemini o Groq), más un informe de respaldo sin LLM."""
import json
import os
import time

import config


class ErrorLLM(RuntimeError):
    """El LLM no está disponible (sin clave, proveedor inválido o sin respuesta)."""


SYSTEM_PROMPT = """Eres un informante técnico que evalúa rutas con imágenes de dron, en español.
Tu lector quiere decidir si recorrer una ruta {tipo_ruta}.
REGLAS:
1. Usa EXCLUSIVAMENTE los datos del JSON recibido. Si falta un dato, escribe "sin dato".
2. No inventes causas, cifras ni coordenadas. Coordenadas con 6 decimales.
3. Las detecciones son automáticas y pueden contener falsos positivos o negativos;
   si "metodo_terreno" es "heuristico", indica que el terreno es una estimación por color.
4. Respeta el "nivel_riesgo" entregado; no lo recalcules.
5. Responde en Markdown con EXACTAMENTE esta estructura y máximo 200 palabras:
## Tramo {{tramo_id}} - Riesgo: {{nivel_riesgo}}
**Resumen:** (2 a 3 frases)
**Hallazgos:** (viñetas con segundo del video, lat/lon y cantidad detectada)
**Terreno:** (distribución en porcentaje)
**Transitabilidad {tipo_ruta}:** (qué implica para quien recorra este tramo así)
**Recomendación:** (1 a 2 acciones concretas)
**Confianza de los datos:** (limitaciones observadas)"""

SYSTEM_RESUMEN = """Eres un informante técnico. Recibes los informes por tramo de un vuelo de dron
sobre una ruta que alguien quiere recorrer {tipo_ruta}.
Escribe un RESUMEN EJECUTIVO en español de máximo 170 palabras: ordena los tramos de mayor a menor
riesgo, destaca los hallazgos críticos, termina con una conclusión clara sobre si la ruta parece
recomendable {tipo_ruta} y con qué precauciones. No agregues información que no esté en los textos."""


def llamar_gemini(sistema, usuario):
    from google import genai
    from google.genai import types
    cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    opciones = dict(system_instruction=sistema, temperature=0.2, max_output_tokens=4096)
    if "2.5-flash" in config.MODELO_GEMINI:      # sin "razonamiento": gasta tokens y corta la respuesta
        opciones["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    r = cliente.models.generate_content(model=config.MODELO_GEMINI, contents=usuario,
                                        config=types.GenerateContentConfig(**opciones))
    fin = str(r.candidates[0].finish_reason) if r.candidates else ""
    if "MAX_TOKENS" in fin:
        raise ValueError("respuesta truncada por límite de tokens")
    return r.text


def llamar_groq(sistema, usuario):
    from groq import Groq
    cliente = Groq(api_key=os.environ["GROQ_API_KEY"])
    r = cliente.chat.completions.create(
        model=config.MODELO_GROQ, temperature=0.2, max_tokens=2048,
        messages=[{"role": "system", "content": sistema},
                  {"role": "user", "content": usuario}])
    if r.choices[0].finish_reason == "length":
        raise ValueError("respuesta truncada por límite de tokens")
    return r.choices[0].message.content


PROVEEDORES = {"gemini": (llamar_gemini, "GEMINI_API_KEY"),
               "groq": (llamar_groq, "GROQ_API_KEY")}


def _proveedor():
    if config.LLM_PROVIDER not in PROVEEDORES:
        raise ErrorLLM(f"LLM_PROVIDER desconocido: {config.LLM_PROVIDER!r}")
    fn, var = PROVEEDORES[config.LLM_PROVIDER]
    clave = os.getenv(var, "")
    if not clave or clave.startswith("pega-tu"):
        raise ErrorLLM(f"falta {var} en .env")
    return fn


def con_reintentos(fn, intentos=4):
    for i in range(intentos):
        try:
            texto = fn()
            if texto and texto.strip():
                return texto
            raise ValueError("respuesta vacía")
        except Exception as e:
            if i == intentos - 1:
                raise ErrorLLM(f"la API no respondió tras {intentos} intentos: {e}") from e
            espera = 5 * 2 ** i
            print(f"Fallo de la API ({e}); reintento en {espera} s")
            time.sleep(espera)


def _llamar(sistema, usuario):
    f = _proveedor()
    return con_reintentos(lambda: f(sistema, usuario))


def redactar_tramo(tramo, tipo_ruta="general"):
    return _llamar(SYSTEM_PROMPT.format(tipo_ruta=tipo_ruta),
                   "Datos del tramo:\n" + json.dumps(tramo, ensure_ascii=False, indent=2))


def redactar_resumen(textos, tipo_ruta="general", contexto=""):
    cuerpo = "\n\n".join(textos)
    if contexto:
        cuerpo = "Datos generales del vuelo:\n" + contexto + "\n\nInformes por tramo:\n" + cuerpo
    return _llamar(SYSTEM_RESUMEN.format(tipo_ruta=tipo_ruta), cuerpo)


# ---------------------------------------------------------------- respaldo sin LLM
def _pos(d):
    if d.get("lat") is None or d.get("lon") is None:
        return "(posición sin dato)"
    return f"({d['lat']:.6f}, {d['lon']:.6f})"


def informe_determinista(tramos, tipo_ruta):
    """Informe con plantillas fijas: se usa cuando el LLM no está disponible."""
    orden = {"alto": 0, "medio": 1, "bajo": 2}
    textos = []
    for t in tramos:
        terreno = ", ".join(f"{k} {v}%" for k, v in t["pct_terreno"].items()) or "sin dato"
        if t["metodo_terreno"] == "heuristico":
            terreno += " (estimación por color)"
        hall = "\n".join(
            f"- t={h['t_video_s']:.0f} s en {_pos(h)}: "
            f"{h['n_obstaculos']} obstáculos, {h['n_personas']} personas, "
            f"{h.get('n_vehiculos', 0)} vehículos"
            for h in t["hallazgos"]) or "- Sin hallazgos puntuales."
        textos.append(
            f"## Tramo {t['tramo_id']} - Riesgo: {t['nivel_riesgo']}\n"
            f"**Resumen:** {t['n_fotogramas']} fotogramas entre "
            f"{_pos(t['inicio'])} y {_pos(t['fin'])}"
            f"{' (sin GPS en ' + str(t['pct_sin_gps']) + '% de los fotogramas)' if t.get('pct_sin_gps') else ''}; "
            f"{t['total_obstaculos']} obstáculos, {t.get('total_vehiculos', 0)} vehículos y "
            f"{t['frames_aglomeracion']} fotogramas con aglomeración.\n\n"
            f"**Hallazgos:**\n{hall}\n\n**Terreno:** {terreno}\n\n"
            f"**Confianza de los datos:** detecciones automáticas; pueden existir falsos "
            f"positivos o negativos.")
    criticos = sorted(tramos, key=lambda t: orden[t["nivel_riesgo"]])
    lista = ", ".join(f"tramo {t['tramo_id']} ({t['nivel_riesgo']})" for t in criticos)
    peor = criticos[0]["nivel_riesgo"] if criticos else "sin dato"
    conclusion = {"alto": "No se recomienda la ruta sin verificar antes en campo los tramos de riesgo alto.",
                  "medio": "La ruta parece transitable con precaución en los tramos de riesgo medio.",
                  "bajo": "No se detectaron riesgos relevantes; la ruta parece transitable."}.get(peor, "")
    resumen = f"Ruta evaluada {tipo_ruta}. Tramos de mayor a menor riesgo: {lista}. {conclusion}"
    return resumen, textos
