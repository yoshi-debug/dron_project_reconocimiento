# API para el celular (envío de misiones y obtención de informes)

La app del celular guarda cada **misión** como una carpeta con **sesiones** (`tierra_*` y `vuelo_*`).
Esa misma estructura es la que se envía al servidor. El servidor arma la línea de tiempo completa,
le asigna a cada vuelo los videos que lo cubren, analiza los fotogramas tomados en el aire y genera
**un informe por vuelo**.

```
celular ──POST /api/misiones/{mision}/sesiones (archivos de una sesión)──► servidor
        ──(o) POST /api/misiones/{mision}/zip (la misión entera)───────────► servidor
                                         └─► por cada vuelo con video: cola ─► análisis ─► informe
celular ◄── GET /api/misiones/{mision} (estado de cada vuelo) ──┘
celular ◄── GET /vuelos/{mision}__{vuelo} (informe HTML)
```

## 1. Levantar el servidor

Desde `inspeccion-dron/`:

```bash
venv/bin/uvicorn servidor.app:app --host 0.0.0.0 --port 8000
```

- **Misma red Wi‑Fi:** el celular usa `http://<IP-de-la-PC>:8000` (la IP sale con `hostname -I`).
  Si no conecta, abre el puerto: `sudo ufw allow 8000/tcp`. Si la red bloquea la conexión entre
  equipos (pasa en redes universitarias), usa el hotspot del celular.
- **Desde fuera (datos móviles, en campo):** `cloudflared tunnel --url http://localhost:8000` y usar la
  URL `https://…` que imprime. En ese caso **define `API_TOKEN` en `.env`**.
- Página web: `http://<servidor>:8000/` · Documentación interactiva: `http://<servidor>:8000/docs`

## 2. Formato de la misión (el que ya genera la app)

```
<mision>/                                  p. ej. no_way_points
├── tierra_20261112_134449/                dron en el suelo
│   ├── resumen.json
│   ├── telemetria.csv
│   ├── video.mp4                          grabaciones que EMPEZARON en esta sesión
│   └── video_2.mp4
├── vuelo_20261112_134631/                 dron en el aire (FLIGHT_START … FLIGHT_END)
│   ├── resumen.json
│   └── telemetria.csv
└── …
```

### `resumen.json`
```json
{"flight_id": "tierra_20261112_134449", "drone_model": "MAVIC_AIR",
 "started_at_ms": 1794509105822, "last_seen_ms": 1794509191674,
 "ended": false, "videos": ["video.mp4", "video_2.mp4"], "errors": []}
```
- `flight_id` = nombre de la carpeta de la sesión (solo letras, números, `_ - .`).
- `videos`: archivos de video de la sesión **en el orden en que se grabaron**.

### `telemetria.csv`
```csv
timestamp_ms,event,latitude,longitude,altitude_m,velocity_x,velocity_y,velocity_z,speed_mps,heading_deg,battery_pct,is_flying,motors_on,satellites,gps_level,flight_mode,details
1794509184448,VIDEO_START,,,,,,,,,,,,,,,tramo_20261112_134624
1794509191691,FLIGHT_START,,,0.0,,,,,,34,,,,,,Vuelo vuelo_20261112_134631
1794509192328,TELEMETRY,-16.4059847,-71.5245794,0.1,0.0,0.1,-0.2,0.1,-140.2,34,1,1,8,2,TakeOff,
1794509216772,FLIGHT_END,,,0.0,,,,,,31,,,,,,aterrizado
```
- `timestamp_ms`: epoch en milisegundos, **del mismo reloj** para telemetría y eventos de video.
- Filas `TELEMETRY` = muestras de posición (latitude/longitude pueden ir vacías si no hay GPS).
- Eventos que usa el servidor:

| Evento | Para qué sirve |
|---|---|
| `VIDEO_START` / `VIDEO_STOP` | **Sincronía.** El n‑ésimo `VIDEO_START` de una sesión = n‑ésimo archivo de `resumen.videos`. Sin este evento el inicio se estima con la fecha del archivo (impreciso). |
| `FLIGHT_START` / `FLIGHT_END` | Ventana del vuelo: solo se analizan fotogramas tomados en el aire. |
| `LANDING_ERROR`, `MANUAL_STOP`, `MISSION_STOPPED` | Aparecen como incidencias en el informe. |

**Recomendaciones para la app:**
1. Mantener siempre el evento `VIDEO_START` justo cuando empieza a grabarse cada archivo, y
   `VIDEO_STOP` al cerrarlo (hoy falta a veces el `VIDEO_STOP` del último video; no es grave).
2. Si es posible, guardar dentro de `resumen.json` el inicio de cada video:
   `"videos": [{"archivo": "video.mp4", "inicio_ms": 1794509121560}]` (todavía no es obligatorio).
3. La telemetría a ≥ 2 Hz y con GPS mejora la ubicación de los hallazgos. Dos de los vuelos de prueba
   (`vuelo_20261112_134631`, `vuelo_20261112_134807`) no tienen ninguna posición GPS.
4. Los tramos se calculan solos (cada 30 s o 25 m, ver `config.py`). Si la app usa waypoints, puede
   añadir una columna `tramo_id` y se respetará.

## 3. Enviar los datos

Con `API_TOKEN` configurado, añadir la cabecera `X-API-Key: <token>` en todas las llamadas.

### Opción A — una sesión cada vez (recomendado: al cerrar cada carpeta)
`POST /api/misiones/{mision}/sesiones` · `multipart/form-data`

| Campo | Descripción |
|---|---|
| `archivos` | **repetido**: todos los archivos de UNA carpeta de sesión, con su nombre original (`resumen.json`, `telemetria.csv`, `video.mp4`, …) |
| `tipo_ruta` | opcional: `a_pie`, `vehiculo` o `general` (se recuerda para toda la misión) |

Volver a enviar una sesión la sobrescribe (útil si la app actualiza `resumen.json` al terminar un video).
Cada vez que llega algo, el servidor revisa la misión y encola los vuelos que ya tienen video
(o cuyo video cambió).

```bash
curl -X POST http://<servidor>:8000/api/misiones/no_way_points/sesiones \
  -F archivos=@tierra_20261112_134449/resumen.json \
  -F archivos=@tierra_20261112_134449/telemetria.csv \
  -F archivos=@tierra_20261112_134449/video.mp4 \
  -F archivos=@tierra_20261112_134449/video_2.mp4 \
  -F tipo_ruta=a_pie
```

### Opción B — la misión completa en un ZIP
`POST /api/misiones/{mision}/zip` con el campo `archivo` (ZIP que contenga las carpetas de sesión).

```bash
cd vuelos && zip -r no_way_points.zip no_way_points
curl -X POST http://<servidor>:8000/api/misiones/no_way_points/zip -F archivo=@no_way_points.zip
```

Respuesta (`202`) de ambas:
```json
{"mision": "no_way_points", "sesiones_recibidas": ["tierra_20261112_134449"],
 "vuelos_encolados": ["no_way_points__vuelo_20261112_134631"],
 "urls": {"mision": "/api/misiones/no_way_points"}}
```

## 4. Seguimiento e informes

- `GET /api/misiones/{mision}` → cada vuelo con `estado` (`sin_video`, `en_cola`, `procesando_video`,
  `generando_informe`, `listo`, `error`), `progreso` y las URLs de su informe.
- `GET /vuelos/{mision}__{vuelo}` → informe en HTML (para un WebView).
- `GET /api/vuelos/{mision}__{vuelo}/informe` → informe en Markdown.
- `GET /api/vuelos/{mision}__{vuelo}/resumen` → JSON por tramo (riesgo, conteos, hallazgos).
- `POST /api/misiones/{mision}/procesar?forzar=true` → rehacer todos los informes de la misión.
- `GET /api/misiones` → lista de misiones.

### Android (Kotlin + OkHttp), subir una carpeta de sesión
```kotlin
val b = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("tipo_ruta", "a_pie")
carpetaSesion.listFiles()!!.forEach { f ->
    val tipo = if (f.extension == "mp4") "video/mp4" else "application/octet-stream"
    b.addFormDataPart("archivos", f.name, f.asRequestBody(tipo.toMediaType()))
}
val req = Request.Builder().url("$BASE/api/misiones/$mision/sesiones")
    .header("X-API-Key", TOKEN).post(b.build()).build()
OkHttpClient.Builder().writeTimeout(10, TimeUnit.MINUTES).build()
    .newCall(req).execute().use { r -> check(r.code == 202) }
```
Con `http://` (sin túnel) Android exige `android:usesCleartextTraffic="true"` en el manifiesto.

## 5. Desde la PC, sin celular

```bash
venv/bin/python 03_procesar_mision.py --mision vuelos/no_way_points
```
Genera un informe por vuelo en `salida/vuelos/<mision>__<vuelo>/` (también visibles en la web).
Opciones: `--vuelo <id>` (repetible), `--tipo-ruta a_pie|vehiculo|general`, `--sin-llm`.

## 6. Formato simple (un video + telemetría), sigue disponible

`POST /api/vuelos` con `video`, `telemetria` (CSV/JSON con `timestamp_ms, lat, lon, alt_m[, tramo_id]`)
o `telemetria_json`, `video_start_epoch_ms`, `tipo_ruta`, `nombre`. Devuelve un `id`;
estado en `GET /api/vuelos/{id}` e informe en `GET /vuelos/{id}`. Lo usa `tools/simular_celular.py`.

## 7. Qué hace el servidor con cada vuelo

1. Junta la telemetría de todas las sesiones de la misión en una sola línea de tiempo.
2. Toma la ventana `FLIGHT_START → FLIGHT_END` y busca los videos que la cubren (por `VIDEO_START` + duración).
3. Analiza 1 fotograma por segundo **dentro de la ventana**: YOLO (personas, vehículos, obstáculos) +
   terreno; a cada fotograma le pone la posición/altitud interpolada de la telemetría.
4. Divide el vuelo en tramos, calcula el riesgo de cada uno con reglas fijas y redacta el informe
   (Gemini/Groq; con plantillas si no hay LLM). Añade "Datos del vuelo": duración, altitud, batería,
   cobertura de GPS y de video, e incidencias registradas por la app.
