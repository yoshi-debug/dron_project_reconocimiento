"""Resumen por tramo y nivel de riesgo (reglas deterministas)."""
import math

import config


def nivel_riesgo(t):
    inestable = t["pct_terreno"].get("inestable", 0.0)
    if (t["frames_aglomeracion"] > 0
            or t["max_obstaculos_por_frame"] >= config.RIESGO_ALTO_ROCAS_MAX
            or inestable >= config.RIESGO_ALTO_PCT_INESTABLE):
        return "alto"
    if t["total_obstaculos"] > 0 or inestable > 0:
        return "medio"
    return "bajo"


def _f(x, n=7):
    """float redondeado, o None si falta (NaN) — así el JSON nunca lleva NaN."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else round(x, n)


def _pos(fila):
    return {"lat": _f(fila.lat), "lon": _f(fila.lon)}


def resumir_por_tramo(df):
    df = df.copy()
    for col, defecto in (("n_vehiculos", 0), ("sin_gps", False), ("video", ""), ("t_vuelo_s", None)):
        if col not in df:
            df[col] = df["t_video_s"] if col == "t_vuelo_s" else defecto
    tramos = []
    for tramo_id, g in df.groupby("tramo_id"):
        g = g.sort_values("ts_ms").copy()
        con_gps = g[g.lat.notna() & g.lon.notna()]
        t = {"tramo_id": int(tramo_id), "n_fotogramas": len(g),
             "t_vuelo_s": {"desde": _f(g.t_vuelo_s.min(), 1), "hasta": _f(g.t_vuelo_s.max(), 1)},
             "inicio": _pos(con_gps.iloc[0]) if len(con_gps) else {"lat": None, "lon": None},
             "fin": _pos(con_gps.iloc[-1]) if len(con_gps) else {"lat": None, "lon": None},
             "pct_sin_gps": round(100 * (1 - len(con_gps) / len(g)), 1),
             "altitud_m": {"min": _f(g.alt_m.min(), 2), "max": _f(g.alt_m.max(), 2)},
             "total_obstaculos": int(g.n_obstaculos.sum()),
             "max_obstaculos_por_frame": int(g.n_obstaculos.max()),
             "frames_con_personas": int((g.n_personas > 0).sum()),
             "max_personas_por_frame": int(g.n_personas.max()),
             "frames_aglomeracion": int(g.aglomeracion.sum()),
             "total_vehiculos": int(g.n_vehiculos.sum()),
             "pct_terreno": (g.terreno.value_counts(normalize=True) * 100).round(1).to_dict(),
             "metodo_terreno": g.terreno_metodo.mode()[0]}
        g["puntaje"] = (g.aglomeracion.astype(int) * 100 + g.n_obstaculos * 10
                        + g.n_vehiculos + g.n_personas)
        c = g[(g.n_obstaculos > 0) | g.aglomeracion | (g.n_vehiculos > 0) | (g.n_personas > 0)]
        t["hallazgos"] = [{"video": f.video if isinstance(f.video, str) else "",
                           "t_video_s": float(f.t_video_s), "t_vuelo_s": _f(f.t_vuelo_s, 1),
                           "lat": _f(f.lat), "lon": _f(f.lon),
                           "n_obstaculos": int(f.n_obstaculos), "n_personas": int(f.n_personas),
                           "n_vehiculos": int(f.n_vehiculos),
                           "imagen": f.imagen if isinstance(f.imagen, str) else ""}
                          for f in c.sort_values("puntaje", ascending=False).head(5).itertuples()]
        t["nivel_riesgo"] = nivel_riesgo(t)
        tramos.append(t)
    return tramos
