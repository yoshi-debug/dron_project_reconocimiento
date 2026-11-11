# Reconocimiento de rutas con dron

Video + telemetría del dron → detección con YOLO + cruce con la posición GPS → informe por tramos
para decidir si una ruta es recomendable a pie o en vehículo. El celular conectado al dron envía los
datos a un servidor HTTP (contrato en [API_CELULAR.md](API_CELULAR.md)).

## Demo con datos sintéticos

Desde `inspeccion-dron/`:

```bash
venv/bin/python tools/generar_escenario_demo.py
```
Crea `data/demo/ruta_demo.mp4` (60 s, 4 tramos) y su telemetría (`.csv`, `.json`) y meta.

```bash
venv/bin/uvicorn servidor.app:app --host 0.0.0.0 --port 8000
```
Levanta el servidor (déjalo corriendo en esa terminal).

```bash
venv/bin/python tools/simular_celular.py --tipo-ruta a_pie
```
En otra terminal: hace lo mismo que la app del celular (sube, espera, imprime el informe y su URL).

Después abre `http://localhost:8000/` en el navegador para ver la lista de vuelos y el informe con los
fotogramas anotados, o súbelo a mano desde esa misma página (también desde el celular en la misma Wi‑Fi).

Resultado esperado del escenario: tramo 3 en riesgo **alto** (aglomeración de personas junto a un bus),
tramos 1, 2 y 4 en **bajo**. El tramo 4 tiene rocas que `yolov8n.pt` no detecta: muestra la limitación
del modelo general hasta tener un detector propio en `modelos/`.

Para probar sin gastar la API del LLM (informe con plantillas):
```bash
LLM_PROVIDER=ninguno venv/bin/uvicorn servidor.app:app --host 0.0.0.0 --port 8000
```

## Sin servidor (línea de comandos)

```bash
venv/bin/python 01_procesar_video.py --video data/demo/ruta_demo.mp4 --telemetria data/demo/ruta_demo_telemetria.csv --meta data/demo/ruta_demo_meta.json
```
```bash
venv/bin/python 02_generar_reporte.py --resultados salida/ruta_demo/resultados_frames.csv --tipo-ruta a_pie
```
