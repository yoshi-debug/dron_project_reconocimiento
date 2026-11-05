"""Carga de telemetría y búsqueda por tiempo con interpolación lineal (hecha a mano)."""
import bisect
import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Muestra:
    ts_ms: int       # instante UTC en milisegundos (epoch)
    lat: float
    lon: float
    alt_m: float
    tramo_id: int


def _a_ms(valor) -> int:
    """Acepta segundos (1.7e9) o milisegundos (1.7e12) y devuelve siempre milisegundos."""
    v = float(valor)
    return int(v * 1000) if v < 1e11 else int(v)


def cargar_telemetria(ruta) -> list[Muestra]:
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".json":
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        # Acepta una lista directa o {"telemetria": [...]}
        filas = datos.get("telemetria", datos.get("data", [])) if isinstance(datos, dict) else datos
    elif ruta.suffix.lower() == ".csv":
        with open(ruta, newline="", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
    else:
        raise ValueError(f"Formato de telemetría no soportado: {ruta.suffix}")

    muestras = []
    for f in filas:
        ts = f.get("timestamp_ms", f.get("timestamp"))
        alt = f.get("alt_m", f.get("altitud"))
        muestras.append(Muestra(_a_ms(ts), float(f["lat"]), float(f["lon"]),
                                float(alt), int(f["tramo_id"])))
    muestras.sort(key=lambda m: m.ts_ms)          # la búsqueda binaria exige orden por tiempo
    if len(muestras) < 2:
        raise ValueError("La telemetría necesita al menos 2 muestras.")
    return muestras


class LineaTemporal:
    """Responde: ¿dónde estaba el dron en el instante ts_ms?"""

    def __init__(self, muestras: list[Muestra]):
        self.muestras = muestras
        self.tiempos = [m.ts_ms for m in muestras]

    @property
    def inicio_ms(self) -> int:
        return self.tiempos[0]

    @property
    def fin_ms(self) -> int:
        return self.tiempos[-1]

    def en(self, ts_ms: int) -> dict:
        # bisect_right devuelve el primer índice cuyo tiempo es MAYOR que ts_ms
        i = bisect.bisect_right(self.tiempos, ts_ms)

        # Caso borde: el instante cae antes de la primera o después de la última muestra
        if i == 0 or i == len(self.muestras):
            m = self.muestras[0] if i == 0 else self.muestras[-1]
            return {"lat": m.lat, "lon": m.lon, "alt_m": m.alt_m, "tramo_id": m.tramo_id,
                    "fuera_de_rango": True, "brecha_ms": abs(ts_ms - m.ts_ms)}

        a, b = self.muestras[i - 1], self.muestras[i]      # las dos muestras que rodean a ts_ms
        f = (ts_ms - a.ts_ms) / (b.ts_ms - a.ts_ms)        # fracción 0..1 entre a y b
        mezclar = lambda x, y: x + (y - x) * f             # interpolación lineal
        return {"lat": mezclar(a.lat, b.lat), "lon": mezclar(a.lon, b.lon),
                "alt_m": mezclar(a.alt_m, b.alt_m),
                "tramo_id": a.tramo_id,                    # categoría: NO se interpola
                "fuera_de_rango": False,
                "brecha_ms": b.ts_ms - a.ts_ms}            # separación entre muestras (calidad)    