"""Resumen por tramo y nivel de riesgo (reglas deterministas)."""
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


def resumir_por_tramo(df):
    tramos = []
    for tramo_id, g in df.groupby("tramo_id"):
        g = g.sort_values("ts_ms")
        t = {"tramo_id": int(tramo_id), "n_fotogramas": len(g),
             "inicio": {"lat": float(g.iloc[0].lat), "lon": float(g.iloc[0].lon)},
             "fin": {"lat": float(g.iloc[-1].lat), "lon": float(g.iloc[-1].lon)},
             "altitud_m": {"min": float(g.alt_m.min()), "max": float(g.alt_m.max())},
             "total_obstaculos": int(g.n_obstaculos.sum()),
             "max_obstaculos_por_frame": int(g.n_obstaculos.max()),
             "frames_aglomeracion": int(g.aglomeracion.sum()),
             "total_vehiculos": int(g.n_vehiculos.sum()) if "n_vehiculos" in g else 0,
             "pct_terreno": (g.terreno.value_counts(normalize=True) * 100).round(1).to_dict(),
             "metodo_terreno": g.terreno_metodo.mode()[0]}
        g = g.copy()
        if "n_vehiculos" not in g:
            g["n_vehiculos"] = 0
        g["puntaje"] = g.aglomeracion.astype(int) * 100 + g.n_obstaculos * 10 + g.n_vehiculos
        c = g[(g.n_obstaculos > 0) | g.aglomeracion | (g.n_vehiculos > 0)]
        t["hallazgos"] = [{"t_video_s": float(f.t_video_s), "lat": float(f.lat),
                           "lon": float(f.lon), "n_obstaculos": int(f.n_obstaculos),
                           "n_personas": int(f.n_personas),
                           "n_vehiculos": int(f.n_vehiculos),
                           "imagen": "" if f.imagen != f.imagen else f.imagen}
                          for f in c.sort_values("puntaje", ascending=False).head(5).itertuples()]
        t["nivel_riesgo"] = nivel_riesgo(t)
        tramos.append(t)
    return tramos
