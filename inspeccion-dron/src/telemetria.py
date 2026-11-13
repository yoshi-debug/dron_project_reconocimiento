"""Carga de telemetría y búsqueda por tiempo con interpolación lineal (hecha a mano).

Formatos aceptados (CSV o JSON):
- Simple:   timestamp_ms, lat, lon, alt_m, tramo_id
- App dron: timestamp_ms, event, latitude, longitude, altitude_m, ... (filas event != TELEMETRY se ignoran)
lat/lon pueden venir vacíos (sin señal GPS); tramo_id es opcional (se calcula con asignar_tramos).
"""
import bisect
import csv
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

import config


@dataclass
class Muestra:
    ts_ms: int                 # instante UTC en milisegundos (epoch)
    lat: float | None
    lon: float | None
    alt_m: float | None
    tramo_id: int | None

    @property
    def tiene_gps(self):
        return self.lat is not None and self.lon is not None


def _a_ms(valor) -> int:
    """Acepta segundos (1.7e9) o milisegundos (1.7e12) y devuelve siempre milisegundos."""
    v = float(valor)
    return int(v * 1000) if v < 1e11 else int(v)


def _num(fila, *claves):
    for c in claves:
        v = fila.get(c)
        if v not in (None, ""):
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(x):
                return x
    return None


def leer_filas(ruta) -> list[dict]:
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".json":
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos.get("telemetria", datos.get("data", [])) if isinstance(datos, dict) else datos
    if ruta.suffix.lower() == ".csv":
        with open(ruta, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    raise ValueError(f"Formato de telemetría no soportado: {ruta.suffix}")


def muestras_desde_filas(filas) -> list[Muestra]:
    por_ts = {}
    for f in filas:
        if f.get("event") not in (None, "", "TELEMETRY"):
            continue                                   # eventos (VIDEO_START, LANDED...) no son muestras
        ts = f.get("timestamp_ms", f.get("timestamp"))
        if ts in (None, ""):
            continue
        lat, lon = _num(f, "lat", "latitude"), _num(f, "lon", "longitude")
        if lat == 0 and lon == 0:                      # algunos SDK reportan 0,0 sin fix
            lat = lon = None
        tramo = _num(f, "tramo_id")
        por_ts[_a_ms(ts)] = Muestra(_a_ms(ts), lat, lon, _num(f, "alt_m", "altitude_m", "altitud"),
                                    int(tramo) if tramo is not None else None)
    return [por_ts[k] for k in sorted(por_ts)]        # orden por tiempo y sin timestamps repetidos


def cargar_telemetria(ruta) -> list[Muestra]:
    muestras = muestras_desde_filas(leer_filas(ruta))
    if len(muestras) < 2:
        raise ValueError("La telemetría necesita al menos 2 muestras.")
    if not any(m.tiene_gps for m in muestras):
        print("AVISO: la telemetría no tiene ninguna posición GPS válida.")
    if any(m.tramo_id is None for m in muestras):
        muestras = asignar_tramos(muestras)
    return muestras


def distancia_m(a: Muestra, b: Muestra) -> float:
    """Distancia aproximada (equirectangular) en metros entre dos muestras con GPS."""
    x = math.radians(b.lon - a.lon) * math.cos(math.radians((a.lat + b.lat) / 2))
    y = math.radians(b.lat - a.lat)
    return 6_371_000 * math.hypot(x, y)


def asignar_tramos(muestras, max_s=None, max_m=None) -> list[Muestra]:
    """Rutas sin waypoints: nuevo tramo cada `max_s` segundos o cada `max_m` metros recorridos."""
    max_s = max_s or config.TRAMO_MAX_S
    max_m = max_m or config.TRAMO_MAX_M
    out, tramo, t0, recorrido, previa = [], 1, None, 0.0, None
    for m in muestras:
        if t0 is None:
            t0 = m.ts_ms
        if previa is not None and previa.tiene_gps and m.tiene_gps:
            recorrido += distancia_m(previa, m)
        if m.ts_ms - t0 >= max_s * 1000 or recorrido >= max_m:
            tramo, t0, recorrido = tramo + 1, m.ts_ms, 0.0
        if m.tiene_gps:
            previa = m
        out.append(replace(m, tramo_id=tramo))
    # un último tramo muy corto (< 1/3 del máximo) se une al anterior
    if tramo > 1 and out[-1].ts_ms - min(m.ts_ms for m in out if m.tramo_id == tramo) < max_s * 1000 / 3:
        out = [replace(m, tramo_id=tramo - 1) if m.tramo_id == tramo else m for m in out]
    return out


class LineaTemporal:
    """Responde: ¿dónde estaba el dron en el instante ts_ms?"""

    def __init__(self, muestras: list[Muestra]):
        self.muestras = muestras
        self.tiempos = [m.ts_ms for m in muestras]
        self.gps = [m for m in muestras if m.tiene_gps]
        self.t_gps = [m.ts_ms for m in self.gps]

    @property
    def inicio_ms(self) -> int:
        return self.tiempos[0]

    @property
    def fin_ms(self) -> int:
        return self.tiempos[-1]

    @staticmethod
    def _interp(tiempos, serie, ts_ms, campos):
        """Interpola `campos` de `serie` en ts_ms. Devuelve (valores, fuera_de_rango, brecha_ms)."""
        i = bisect.bisect_right(tiempos, ts_ms)
        if i == 0 or i == len(serie):                   # antes de la 1.ª o después de la última
            m = serie[0] if i == 0 else serie[-1]
            return {c: getattr(m, c) for c in campos}, True, abs(ts_ms - m.ts_ms)
        a, b = serie[i - 1], serie[i]
        f = (ts_ms - a.ts_ms) / (b.ts_ms - a.ts_ms)
        vals = {}
        for c in campos:
            x, y = getattr(a, c), getattr(b, c)
            vals[c] = x if y is None else y if x is None else x + (y - x) * f
        return vals, False, b.ts_ms - a.ts_ms

    def en(self, ts_ms: int) -> dict:
        base, fuera, brecha = self._interp(self.tiempos, self.muestras, ts_ms, ["alt_m"])
        i = max(bisect.bisect_right(self.tiempos, ts_ms) - 1, 0)
        r = {"alt_m": base["alt_m"], "tramo_id": self.muestras[i].tramo_id,   # categoría: NO se interpola
             "fuera_de_rango": fuera, "brecha_ms": brecha,
             "lat": None, "lon": None, "gps_brecha_ms": None, "sin_gps": True}
        if self.gps:
            pos, _, _ = self._interp(self.t_gps, self.gps, ts_ms, ["lat", "lon"])
            j = bisect.bisect_left(self.t_gps, ts_ms)
            cercana = min(abs(self.t_gps[k] - ts_ms) for k in (j - 1, j) if 0 <= k < len(self.t_gps))
            r.update(lat=pos["lat"], lon=pos["lon"], gps_brecha_ms=cercana,
                     sin_gps=cercana > config.GPS_MAX_BRECHA_MS)
            if r["sin_gps"]:                             # posición demasiado lejana en el tiempo
                r.update(lat=None, lon=None)
        return r
