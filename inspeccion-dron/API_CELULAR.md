# API para el celular (envío de vuelos y obtención del informe)

El celular conectado al dron envía **un video + su telemetría** y el servidor responde con un `id`.
El análisis (YOLO + telemetría + redacción del informe) corre en segundo plano; el celular consulta
el estado hasta que esté `listo` y entonces descarga el informe.

```
celular ──POST /api/vuelos (video, telemetría)──► servidor ──► cola ──► análisis ──► informe
celular ◄──────── GET /api/vuelos/{id} (estado) ─┘
celular ◄──────── GET /api/vuelos/{id}/informe (Markdown)  o  /vuelos/{id} (página HTML)
```

## 1. Levantar el servidor

Desde `inspeccion-dron/`:

```bash
venv/bin/uvicorn servidor.app:app --host 0.0.0.0 --port 8000
```

- **Misma red Wi‑Fi:** el celular usa `http://<IP-de-la-PC>:8000` (la IP sale con `hostname -I`).
  Si no conecta, abre el puerto: `sudo ufw allow 8000/tcp`.
- **Desde fuera (datos móviles, en campo):** expón el puerto con un túnel, por ejemplo
  `cloudflared tunnel --url http://localhost:8000` o `ngrok http 8000`, y usa la URL `https://…` que imprime.
  En ese caso **define `API_TOKEN` en `.env`** para que nadie más pueda subir vuelos.
- Página de prueba (sirve también desde el navegador del celular): `http://<servidor>:8000/`
- Documentación interactiva automática: `http://<servidor>:8000/docs`

## 2. Enviar un vuelo — `POST /api/vuelos`

`multipart/form-data`. Si el servidor tiene `API_TOKEN`, añadir la cabecera `X-API-Key: <token>`.

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `video` | archivo | sí | `.mp4 .mov .avi .mkv .m4v .3gp` |
| `telemetria` | archivo | uno de los dos | CSV o JSON (formato abajo) |
| `telemetria_json` | texto | uno de los dos | La misma telemetría como texto JSON (cómodo desde la app) |
| `video_start_epoch_ms` | entero | recomendado | Instante (epoch ms, UTC) en que empezó a grabar el video |
| `meta` | archivo | no | JSON `{"video_start_epoch_ms": ...}` (alternativa al campo anterior) |
| `offset_ms` | entero | no | Corrección manual de sincronía video/telemetría (por defecto 0) |
| `tipo_ruta` | texto | no | `a_pie`, `vehiculo` o `general` (por defecto) — orienta el informe |
| `nombre` | texto | no | Nombre libre de la ruta |

**Importante para la sincronía:** el informe ubica cada fotograma con
`timestamp = video_start_epoch_ms + segundo_del_video`. Si no se envía `video_start_epoch_ms`,
se supone que el video empieza con la primera muestra de telemetría (menos preciso).

### Formato de la telemetría

CSV:
```csv
timestamp_ms,lat,lon,alt_m,tramo_id
1760000000000,-12.000100,-76.999960,30.0,1
1760000000200,-12.000110,-76.999956,30.1,1
```

JSON (lista, o `{"telemetria": [...]}`):
```json
[{"timestamp_ms": 1760000000000, "lat": -12.0001, "lon": -76.99996, "alt_m": 30.0, "tramo_id": 1}]
```

- `timestamp_ms` (o `timestamp`): epoch en ms; también acepta segundos.
- `alt_m` (o `altitud`): metros.
- `tramo_id`: entero que divide la ruta en tramos (p. ej. cada waypoint o cada N metros). Si la app
  no lo calcula, enviar `1` en todas las filas: el informe tendrá un solo tramo.
- Mínimo 2 muestras. Recomendado ≥ 1 Hz.

### Respuesta `202 Accepted`
```json
{"id": "20261111-165136-70f342", "estado": "en_cola",
 "urls": {"estado": "/api/vuelos/20261111-165136-70f342",
          "informe_md": "/api/vuelos/20261111-165136-70f342/informe",
          "informe_html": "/vuelos/20261111-165136-70f342",
          "resumen_json": "/api/vuelos/20261111-165136-70f342/resumen"}}
```
Errores: `401` token incorrecto · `413` video demasiado grande · `422` datos inválidos
(el campo `detail` explica el motivo, p. ej. `"Telemetría inválida: KeyError: 'lon'"`).
La telemetría se valida **antes** de guardar el video.

## 3. Consultar el estado — `GET /api/vuelos/{id}`

Consultar cada 3–5 s. Campos útiles:

```json
{"estado": "procesando_video", "progreso": 0.42, "mensaje": "20 fotogramas analizados",
 "posicion_en_cola": null, "error": null}
```

`estado`: `en_cola` → `procesando_video` → `generando_informe` → `listo` | `error`.

## 4. Obtener el informe

- `GET /api/vuelos/{id}/informe` → Markdown (`text/markdown`), para mostrar en la app.
- `GET /vuelos/{id}` → página HTML lista para abrir en un WebView o navegador
  (con token: `/vuelos/{id}?token=<token>`).
- `GET /api/vuelos/{id}/resumen` → JSON por tramo: riesgo, coordenadas, conteos, hallazgos.
- `GET /api/vuelos/{id}/frames/{archivo}` → fotogramas anotados citados en los hallazgos.

Devuelven `409` si el informe aún no está listo.

## 5. Otros

- `GET /api/vuelos` → lista de vuelos recibidos.
- `POST /api/vuelos/{id}/reintentar` → vuelve a procesar un vuelo con estado `error` sin re-subirlo.
- `GET /api/salud` → `{"ok": true, "requiere_token": ...}` para comprobar conexión.

## 6. Ejemplos

### curl
```bash
curl -X POST http://192.168.1.50:8000/api/vuelos \
  -H "X-API-Key: $TOKEN" \
  -F video=@vuelo.mp4 \
  -F telemetria=@telemetria.csv \
  -F video_start_epoch_ms=1760000000000 \
  -F tipo_ruta=a_pie -F nombre="Ruta al mirador"
```

### Android (Kotlin + OkHttp)
```kotlin
val cuerpo = MultipartBody.Builder().setType(MultipartBody.FORM)
    .addFormDataPart("video", archivoVideo.name, archivoVideo.asRequestBody("video/mp4".toMediaType()))
    .addFormDataPart("telemetria_json", telemetriaJson)          // String con la lista JSON
    .addFormDataPart("video_start_epoch_ms", inicioVideoMs.toString())
    .addFormDataPart("tipo_ruta", "a_pie")
    .build()
val req = Request.Builder().url("$BASE/api/vuelos")
    .header("X-API-Key", TOKEN).post(cuerpo).build()
val cliente = OkHttpClient.Builder()
    .writeTimeout(10, TimeUnit.MINUTES)      // videos grandes
    .build()
cliente.newCall(req).execute().use { r -> /* r.code == 202 -> leer "id" del JSON */ }
```

Si el servidor se usa por `http://` (sin túnel https), Android exige
`android:usesCleartextTraffic="true"` en el `AndroidManifest.xml` (o una `network_security_config`).

## 7. Qué hace el servidor con cada vuelo

1. Guarda los archivos en `salida/vuelos/<id>/`.
2. Etapa 1 (`src/pipeline.procesar_video`): 1 fotograma por segundo → YOLO (obstáculos, personas,
   vehículos) + terreno → se cruza con la telemetría por timestamp.
3. Etapa 2 (`src/pipeline.generar_reporte`): agregación por tramo con riesgo determinista
   (`alto/medio/bajo`) → redacción con Gemini/Groq orientada al `tipo_ruta`.
   Si no hay clave de API o el LLM falla, se genera un informe con plantillas fijas y se indica en el propio informe.
4. Los vuelos se procesan de uno en uno; si el servidor se reinicia, los pendientes se re-encolan.
