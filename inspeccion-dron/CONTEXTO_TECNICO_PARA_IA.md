# Auditoría técnica y contexto del proyecto

**Fecha de revisión:** 2026-10-29  
**Proyecto:** `inspeccion-dron`  
**Objetivo de este documento:** servir como contexto verificable para otra IA que deba entender, mantener o ampliar este proyecto.

## 1. Resumen ejecutivo

Este es un prototipo local en Python que procesa un video de dron, muestrea fotogramas, detecta objetos, alinea cada fotograma con telemetría usando marcas de tiempo, resume resultados por tramo de vuelo y redacta un informe Markdown mediante un LLM remoto (Gemini o Groq).

El proyecto tiene dos etapas ejecutables:

1. `01_procesar_video.py`: video + telemetría + metadatos → `resultados_frames.csv`, `info_corrida.json` e imágenes anotadas opcionales.
2. `02_generar_reporte.py`: CSV → resumen por tramo → LLM → `reporte.md`.

**Estado real de los modelos:** no están instalados los modelos propios que configura el proyecto (`modelos/detector_obstaculos.pt` y `modelos/clasificador_terreno.pt`). La ejecución de muestra declara `detector_propio=false` y `clasificador_propio=false`, así que usa el archivo local `yolov8n.pt` (modelo general COCO) para detección y una heurística de color HSV para terreno. La heurística solo etiqueta `arenoso` u `otro`; no detecta terreno inestable. El detector COCO estándar no incluye una clase “roca”, por lo que las detecciones de rocas configuradas por el proyecto no pueden darse por validadas con este modelo.

**Ejecución de muestra observada:** 60 fotogramas a 1 FPS, 3 tramos, 0 fotogramas con obstáculos, 0 con personas, 0 fuera de rango y 60 clasificados como `arenoso` por método `heuristico`. El generador de datos sintéticos dibuja formas grises como rocas entre los segundos 25 y 45; que el CSV tenga cero obstáculos es coherente con la limitación del modelo COCO, no evidencia de que no hubiera objetos en el video.

El proyecto no incluye pruebas automatizadas, README, empaquetado formal ni configuración de CI observados. La carpeta `modelos/` está vacía; la carpeta `venv/` contiene el entorno instalado y no forma parte del código fuente que conviene enviar a otra IA.

## 2. Estructura del proyecto

```text
inspeccion-dron/
├── 01_procesar_video.py            # etapa 1: inferencia visual y fusión con telemetría
├── 02_generar_reporte.py            # etapa 2: agregación y redacción con LLM
├── config.py                        # rutas, umbrales, modelos y proveedores
├── requirements.txt                 # versiones fijadas del entorno Python
├── .env.example                     # nombres de variables requeridas; claves de ejemplo
├── .env                             # existe localmente; no inspeccionado ni incluido aquí
├── .gitignore                       # excluye .env, venv, caches, salida y videos MP4
├── yolov8n.pt                       # pesos YOLOv8n general, usado como fallback
├── data/
│   └── entrada/
│       ├── vuelo_demo.mp4           # video sintético de ejemplo (~119 MiB)
│       ├── vuelo_demo_telemetria.csv
│       └── vuelo_demo_meta.json
├── modelos/                         # carpeta vacía en la revisión
├── salida/
│   └── vuelo_demo/
│       ├── info_corrida.json        # parámetros/resultados de selección de modelos
│       ├── resultados_frames.csv    # una fila por fotograma muestreado
│       ├── resumen_tramos.json      # agregado determinista de la etapa 2
│       ├── reporte.md               # no presente en la muestra revisada
│       └── frames/                  # imágenes anotadas, si existen detecciones
├── src/
│   ├── __init__.py
│   ├── frames.py                    # apertura de video y muestreo
│   ├── telemetria.py                # parseo e interpolación por timestamp
│   ├── vision.py                    # YOLO y clasificación/heurística del terreno
│   ├── agregacion.py                # métricas y reglas de riesgo por tramo
│   └── reporte.py                   # prompts e integración Gemini/Groq
├── tools/
│   ├── generar_datos_prueba.py      # crea video sintético, telemetría y metadatos
│   └── generar_resultados_falsos.py # archivo vacío (0 bytes)
└── CONTEXTO_TECNICO_PARA_IA.md      # esta auditoría
```

`.gitignore` excluye `salida/`, `data/entrada/*.mp4`, `.env`, `venv/`, `__pycache__/` y `*.pyc`. Por tanto, resultados y video pueden existir localmente, pero no necesariamente llegarán al repositorio o a un paquete compartido. La presencia de `.env` se verificó sin leer sus valores; `.env.example` contiene solo marcadores de posición.

## 3. Flujo de ejecución

### Etapa 1: procesar video

Entrada:

- `--video`: archivo de video requerido.
- `--telemetria`: CSV o JSON requerido.
- `--meta`: JSON opcional con `video_start_epoch_ms`.
- `--inicio-ms`: alternativa explícita para el inicio del video en epoch milisegundos.
- `--offset-ms`: corrección manual de sincronía; predeterminado `0`.
- `--salida`: carpeta destino opcional; por defecto `salida/<nombre-base-del-video>`.

Comando para la muestra:

```bash
python 01_procesar_video.py \
  --video data/entrada/vuelo_demo.mp4 \
  --telemetria data/entrada/vuelo_demo_telemetria.csv \
  --meta data/entrada/vuelo_demo_meta.json
```

La función `instante_inicio_video` prioriza `--inicio-ms`, luego el `video_start_epoch_ms` del meta JSON. Si ninguno existe, usa la primera muestra de telemetría e imprime una advertencia. Para cada fotograma seleccionado, calcula `ts_ms = inicio_video + t_video_s * 1000 + offset_ms`, obtiene latitud/longitud/altitud/tramo de `LineaTemporal`, llama a `Analizador.analizar`, agrega una fila y guarda una imagen anotada solo si el analizador devuelve una.

`src/frames.py` calcula el paso aproximado como `round(fps_video / FPS_MUESTREO)` y toma cada N-ésimo fotograma. La configuración actual es 1 FPS. La marca de tiempo del fotograma se calcula con `índice / fps_video`; no se usa el timestamp interno de cada paquete de video.

### Etapa 2: resumir y redactar

Comando:

```bash
python 02_generar_reporte.py --resultados salida/vuelo_demo/resultados_frames.csv
```

`src/agregacion.py` agrupa por `tramo_id`, calcula posición de inicio/fin, rango de altitud, conteos, porcentaje por clase de terreno y hasta cinco hallazgos ordenados por puntuación. Clasifica cada tramo como `alto`, `medio` o `bajo` con reglas deterministas. Después `src/reporte.py` manda un prompt por tramo y otro para el resumen ejecutivo al proveedor configurado; los informes recibidos se escriben en `reporte.md`.

## 4. Módulos y responsabilidades

### `01_procesar_video.py`

- Orquesta argumentos CLI, carga de telemetría, sincronización, lectura de video, inferencia y escritura de artefactos.
- Produce estas columnas en `resultados_frames.csv`: `frame_idx`, `t_video_s`, `ts_ms`, `lat`, `lon`, `alt_m`, `tramo_id`, `telemetria_fuera_de_rango`, `brecha_ms`, `n_obstaculos`, `n_personas`, `aglomeracion`, `conf_max`, `conteo`, `terreno`, `terreno_conf`, `terreno_metodo`, `imagen`.
- `conteo` se serializa como JSON dentro de la celda CSV.
- `info_corrida.json` registra video, FPS, duración, origen temporal, offset y si se usaron modelos propios.

### `src/frames.py`

- `info_video(ruta)`: abre el video con OpenCV y devuelve FPS, número de fotogramas y duración calculada.
- `extraer_frames(ruta, fps_muestreo)`: generador `(índice, segundo, imagen_BGR)`; avanza con `grab()` y decodifica los seleccionados con `retrieve()`.
- Libera el capturador en `finally`.

### `src/telemetria.py`

- Acepta `.csv` mediante `csv.DictReader` o `.json` como lista directa, `{"telemetria": [...]}` o `{"data": [...]}`.
- Campos de tiempo aceptados: `timestamp_ms` o `timestamp`; altitud: `alt_m` o `altitud`; exige `lat`, `lon` y `tramo_id`.
- `_a_ms` interpreta valores menores a `1e11` como segundos y los convierte a milisegundos; de otro modo los considera ya milisegundos.
- Ordena las muestras por timestamp y exige al menos dos.
- `LineaTemporal.en(ts_ms)` interpola latitud, longitud y altitud linealmente entre muestras. `tramo_id` no se interpola: toma el de la muestra anterior.
- Antes o después de la cobertura telemétrica devuelve la primera/última posición (sin extrapolar) y marca `fuera_de_rango=True`, además de informar la distancia temporal en `brecha_ms`.

### `src/vision.py`

- `Analizador` usa `modelos/detector_obstaculos.pt` si existe; de lo contrario carga `yolov8n.pt` desde la raíz.
- Si no existe `modelos/clasificador_terreno.pt`, clasifica el terreno por umbral de color HSV.
- La detección cuenta nombres que coincidan exactamente (minúsculas) con los conjuntos de `config.py`.
- Las cajas anotadas solo se guardan si el conteo de obstáculos o personas es mayor a cero.
- La heurística HSV define `arenoso` cuando al menos 45% de los píxeles cae en el rango HSV configurado; en caso contrario devuelve `otro`. La confianza devuelta es una proporción de píxeles, no una probabilidad calibrada.
- Si se aporta clasificador propio, el código espera salida de clasificación (`r.probs.top1` y `top1conf`).

### `src/agregacion.py`

- Riesgo `alto` si hubo alguna aglomeración, si el máximo de obstáculos en un fotograma alcanza el umbral, o si la proporción de terreno `inestable` alcanza el umbral.
- Riesgo `medio` si hubo algún obstáculo total o cualquier proporción `inestable` mayor que cero.
- En otro caso, `bajo`.
- Las detecciones se agregan por tramo; `hallazgos` solo considera fotogramas con obstáculos o aglomeración. Por tanto, una clasificación de terreno por sí sola puede cambiar el nivel de riesgo sin aparecer como hallazgo puntual.

### `src/reporte.py`

- Proveedores disponibles: Google Gemini y Groq.
- Configuración predeterminada: `LLM_PROVIDER=gemini`, modelo Gemini `gemini-2.5-flash`; modelo Groq `llama-3.3-70b-versatile`.
- Instrucciones del prompt: español, usar solo el JSON/textos enviados, no inventar y respetar nivel de riesgo determinista.
- Se espera una clave `GEMINI_API_KEY` o `GROQ_API_KEY`, según el proveedor.
- Reintenta hasta cuatro veces atrapando cualquier excepción, con espera exponencial de 5, 10, 20 y 40 segundos. Hay además una pausa fija de 5 segundos entre llamadas de tramo.

### Herramientas de muestra

- `tools/generar_datos_prueba.py` crea un video sintético de 60 s a 30 FPS, resolución 640×480, telemetría de 5 Hz con cobertura extendida dos segundos antes y después, tres tramos y metadatos de inicio. Inserta elipses grises en los segundos 25–45.
- `tools/generar_resultados_falsos.py` existe pero está vacío; no proporciona un generador de resultados.

## 5. Datos de entrada y salida

### Telemetría de muestra

El CSV usa:

```csv
timestamp_ms,lat,lon,alt_m,tramo_id
1759999998000,-12.0,-77.0,30.0,1
```

El timestamp es epoch en milisegundos. La muestra generada contiene 320 observaciones (5 Hz durante 64 s), ordenadas por tiempo. El meta JSON contiene:

```json
{"video_start_epoch_ms": 1760000000000}
```

### Resultado observado de muestra

- Video: `vuelo_demo.mp4`, 30 FPS, 60 s.
- 60 fotogramas de análisis (1 por segundo).
- Telemetría válida para los 60 fotogramas; no hay filas fuera de rango.
- Los tres tramos tienen 20 fotogramas cada uno.
- Todos los conteos de obstáculos y personas son cero.
- El terreno es `arenoso` en 100% de los fotogramas, con método `heuristico`.
- Los tres tramos quedan con riesgo `bajo`.
- No se generaron rutas de imágenes en las filas de muestra.

Este resultado no demuestra capacidad de reconocer rocas/personas en condiciones reales: el input es sintético y el modelo por defecto no posee una clase de roca. Los valores del CSV y JSON son resultados existentes, no una nueva ejecución realizada durante esta auditoría.

## 6. Modelos y reglas de negocio

| Componente | Ruta/configuración | Uso efectivo observado | Límite principal |
|---|---|---|---|
| Detector de objetos | `modelos/detector_obstaculos.pt` | No existe; `info_corrida.json` informa `detector_propio=false` | El modelo propio no está incluido |
| Detector fallback | `yolov8n.pt` en raíz; Ultralytics YOLOv8n, clases COCO | Sí, se selecciona cuando falta detector propio | Modelo general COCO; no detecta la clase “roca” configurada por el proyecto |
| Clasificador de terreno | `modelos/clasificador_terreno.pt` | No existe; `clasificador_propio=false` | No hay pesos/clases propios disponibles |
| Terreno fallback | Heurística HSV en `src/vision.py` | Sí, `terreno_metodo=heuristico` | Solo `arenoso`/`otro`; no puede detectar `inestable` |
| Redactor de informe | Gemini o Groq mediante API | Configuración predeterminada Gemini; no se confirma ejecución de la etapa LLM en los artefactos revisados | Requiere Internet y credencial; salida generativa no se valida contra un esquema |

`config.py` define:

- `FPS_MUESTREO = 1.0`, `CONF_MIN = 0.25`, `IMG_SIZE = 640`.
- Obstáculos: `roca`, `rock`, `stone`, `boulder`, `debris`, `escombro`.
- Personas: `person`, `persona`.
- Aglomeración: 3 o más personas detectadas en un fotograma.
- Riesgo alto: al menos 5 obstáculos en un fotograma, alguna aglomeración o 30% o más del terreno `inestable`.

Las clases se comparan por nombre exacto en minúsculas. Un modelo propio con otras etiquetas no contará como obstáculo/persona hasta que se adapte la configuración o se normalicen sus nombres. Un modelo de terreno debe ser de clasificación, no de detección, debido al acceso a `r.probs`.

## 7. Librerías y entorno

### Entorno verificado

- Python `3.14.4`, entorno virtual local `venv/`.
- Versiones observadas: `ultralytics 8.4.191`, `torch 2.14.1+cpu`, `torchvision 0.29.1+cpu`, `opencv-python 5.0.0.93`, `opencv-python-headless 5.0.0.93`, `pandas 3.1.0`, `numpy 2.5.2`, `python-dotenv 1.2.4`, `google-genai 2.33.0`, `groq 1.7.0`.
- El entorno instala PyTorch CPU; no hay evidencia de uso de aceleración GPU en la configuración fijada.

### Dependencias que el código importa directamente

| Paquete/importación | Responsabilidad |
|---|---|
| `opencv-python` / `cv2` | Captura, lectura y escritura de video/frames; color HSV |
| `pandas` | Construcción, lectura, escritura y agrupación de tablas |
| `numpy` | Máscara y proporciones HSV; datos sintéticos |
| `ultralytics` | Inferencia YOLO y carga de pesos |
| `python-dotenv` / `dotenv` | Lectura local de `.env` desde `config.py` |
| `google-genai` / `google.genai` | Llamadas a Gemini |
| `groq` | Llamadas al proveedor Groq |
| Biblioteca estándar | `argparse`, `json`, `csv`, `bisect`, `dataclasses`, `pathlib`, `datetime`, `time`, `os`, `collections` |

`requirements.txt` fija versiones de dependencias directas y transitivas. Incluye simultáneamente `opencv-python` y `opencv-python-headless`, que instalan el mismo namespace `cv2`; conviene elegir una sola variante para reducir conflictos y ambigüedad de instalación. El archivo lista también paquetes de infraestructura/transitivos (por ejemplo PyTorch, torchvision, Pillow, requests, httpx, pydantic, PyYAML, matplotlib, polars y dependencias de Google/Groq). Para sus versiones completas y exactas, consultar el propio `requirements.txt`.

## 8. Hallazgos y riesgos técnicos observados

1. **Los pesos especializados no están presentes.** `modelos/` está vacía y el estado de la corrida confirma los fallbacks. La aplicación se ejecuta, pero no tiene los modelos específicos de obstáculos ni terreno que su configuración sugiere.
2. **El fallback no satisface la taxonomía de obstáculos.** `yolov8n.pt` COCO no incluye roca/escombro; así que esos contadores no sirven como validación del caso de uso. No se debe interpretar el riesgo bajo de la muestra como una inspección fiable de peligros.
3. **La estimación del terreno es muy limitada.** HSV detecta un rango de color, no propiedades físicas del terreno. Etiquetas como `inestable` solo pueden aparecer con un clasificador propio y etiquetas exactamente compatibles.
4. **No se validan exhaustivamente entradas.** Se exige un mínimo de dos muestras, pero no se verifica explícitamente que campos numéricos sean finitos, que los timestamps sean únicos, que la telemetría cubra el vuelo, ni que el video contenga fotogramas decodificables antes de crear resultados. Un video vacío podría llevar a un DataFrame sin columnas y fallar después al indexar.
5. **La calidad temporal se reporta pero no limita el riesgo.** Si un fotograma queda fuera de rango, se le asigna la coordenada del extremo más cercano y se marca la fila; la agregación no descarta esos datos ni ajusta el nivel de riesgo según la distancia temporal.
6. **Errores LLM se reintentan de forma indiscriminada.** `con_reintentos` captura cualquier excepción, incluyendo potencialmente errores no transitorios como credencial ausente o modelo inválido. Esto retrasa el fallo y puede complicar el diagnóstico. El proveedor desconocido tampoco se valida: cualquier valor distinto de `gemini` elige Groq.
7. **No hay validación estructurada de la respuesta generativa.** El prompt pide una estructura y límite de palabras, pero el código concatena el texto retornado sin comprobar formato, longitud, inventos o ausencia de contenido.
8. **La selección de hallazgos no incorpora confianza.** Se utiliza aglomeración y conteo para puntuación; `conf_max` no participa en el cálculo de riesgo ni en la selección de los cinco hallazgos.
9. **La prueba sintética no cubre el resultado objetivo.** El video dibuja “rocas”, pero no hay modelo compatible ni aserciones; el generador de resultados falsos está vacío y no hay suite de tests.
10. **Instalación poco mínima.** Hay dos distribuciones OpenCV y un archivo de requirements que parece exportado como freeze completo. Para reproducibilidad portable conviene definir y probar una versión de Python objetivo, dependencias directas explícitas y una instalación limpia.
11. **Trazabilidad incompleta de modelos.** `info_corrida.json` registra banderas de modelo propio, pero no el nombre/versión/hash del peso, etiquetas, parámetros efectivos ni versiones del entorno.
12. **No se confirmó ejecución de informes externos.** El código requiere credenciales y red; esta auditoría no leyó `.env`, no llamó a servicios externos ni incurrió en cargos de API.

## 9. Qué conviene priorizar

1. Proveer y versionar/entregar por separado los pesos entrenados para obstáculos y terreno, con licencia, origen, clases, tamaño de imagen, umbrales y métricas de evaluación.
2. Añadir una validación de configuración de clases para asegurar que las etiquetas del detector coincidan con las categorías utilizadas por las reglas.
3. Crear pruebas pequeñas de telemetría (interpolación, límites y transiciones de tramo), extracción de frames, agregación de riesgo y fallbacks; incluir una prueba de integración sintética con resultados esperados realistas.
4. Validar CSV/JSON y video antes de inferir: columnas, tipo/rango de datos, timestamps, FPS, fotogramas decodificables y cobertura temporal.
5. Manejar errores LLM por clase, validar proveedor/credenciales al inicio y validar el resultado final antes de escribir el informe.
6. Eliminar una de las variantes OpenCV y reducir/organizar los pins de dependencias; probar instalación limpia en un Python de soporte declarado.
7. Registrar en `info_corrida.json` versiones de paquetes, identificador y hash de cada modelo, parámetros de inferencia y cobertura/calidad telemétrica.
8. Definir si un dato fuera de cobertura invalida la georreferenciación o debe excluirse/rebajar la confianza del riesgo.

## 10. Guía para la siguiente IA

Al trabajar en este proyecto:

- No asumir que hay modelos de detección de rocas o terreno entrenados; verificar `modelos/` y `info_corrida.json`.
- No interpretar el resultado `bajo` ni cero obstáculos como evidencia fiable de seguridad: el fallback COCO no detecta roca y la heurística no reconoce inestabilidad.
- Mantener la separación entre inferencia visual, sincronización, agregación determinista y redacción generativa.
- Mantener los niveles de riesgo deterministas en `src/agregacion.py`; el LLM está instruido para describirlos, no recalcularlos.
- No leer, copiar, imprimir ni añadir al repositorio los valores de `.env`. Usar `.env.example` para nombres de variables y nunca registrar claves.
- Antes de modificar esquemas de salida, buscar los consumidores en ambos scripts y el reporte.
- Los artefactos bajo `salida/` y los videos MP4 están ignorados por Git. Si una evaluación necesita estos archivos, adjuntarlos explícitamente o regenerarlos.
- No considerar `tools/generar_resultados_falsos.py` como funcional: es un archivo vacío.
- No se identificaron pruebas automatizadas; ejecutar validaciones nuevas y reportar claramente qué parte del pipeline se ejecutó. No llamar al proveedor LLM sin autorización/credenciales.

## 11. Alcance y método de esta auditoría

Se revisaron los scripts principales, todos los módulos de `src/`, la configuración, dependencias, ejemplo de entorno, generadores, metadatos y resultados de muestra. También se inspeccionó la estructura excluyendo internamente el contenido masivo de `venv/`, el tamaño/tipo de los artefactos binarios, los imports resueltos por Pylance y el entorno virtual instalado. Pylance no reportó diagnósticos de workspace. No se inspeccionaron secretos, no se cargó el checkpoint para ejecutar pickle, no se ejecutó inferencia de nuevo y no se llamaron APIs externas. En consecuencia, los resultados y versiones se describen según artefactos existentes y metadatos locales, no como una validación de precisión del modelo en terreno.
