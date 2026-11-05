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
             "pct_terreno": (g.terreno.value_counts(normalize=True) * 100).round(1).to_dict(),
             "metodo_terreno": g.terreno_metodo.mode()[0]}
        c = g[(g.n_obstaculos > 0) | g.aglomeracion].copy()
        c["puntaje"] = c.aglomeracion.astype(int) * 100 + c.n_obstaculos
        t["hallazgos"] = [{"t_video_s": float(f.t_video_s), "lat": float(f.lat),
                           "lon": float(f.lon), "n_obstaculos": int(f.n_obstaculos),
                           "n_personas": int(f.n_personas),
                           "imagen": "" if f.imagen != f.imagen else f.imagen}
                          for f in c.sort_values("puntaje", ascending=False).head(5).itertuples()]
        t["nivel_riesgo"] = nivel_riesgo(t)
        tramos.append(t)
    return tramos
