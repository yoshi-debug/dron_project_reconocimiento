"""Paso 2: resultados_frames.csv -> agregación por tramo -> LLM -> reporte.md"""
import argparse
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd

import config
from src.agregacion import resumir_por_tramo
from src.reporte import redactar_resumen, redactar_tramo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultados", required=True)
    args = ap.parse_args()

    ruta = Path(args.resultados)
    dir_salida = ruta.parent
    df = pd.read_csv(ruta)

    tramos = resumir_por_tramo(df)
    (dir_salida / "resumen_tramos.json").write_text(
        json.dumps(tramos, ensure_ascii=False, indent=2), encoding="utf-8")

    ruta_info = dir_salida / "info_corrida.json"
    info = json.loads(ruta_info.read_text(encoding="utf-8")) if ruta_info.exists() else {}

    textos = []
    for t in tramos:
        print(f"Redactando tramo {t['tramo_id']} (riesgo {t['nivel_riesgo']})...")
        textos.append(redactar_tramo(t))
        time.sleep(config.PAUSA_ENTRE_LLAMADAS_S)
    print("Redactando resumen ejecutivo...")
    resumen = redactar_resumen(textos)

    cabecera = (f"# Informe de inspección con dron\n\n- Fecha: {date.today()}\n"
                f"- Video: {info.get('video', 'sin dato')}\n"
                f"- Fotogramas analizados: {len(df)}\n- Tramos: {len(tramos)}")
    md = "\n\n".join([cabecera, "## Resumen ejecutivo", resumen] + textos)
    (dir_salida / "reporte.md").write_text(md, encoding="utf-8")
    print("Listo:", dir_salida / "reporte.md")


if __name__ == "__main__":
    main()
