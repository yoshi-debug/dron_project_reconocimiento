"""Procesa una misión grabada por la app (carpetas tierra_*/vuelo_*) y genera un informe por vuelo.

    venv/bin/python 03_procesar_mision.py --mision vuelos/no_way_points
    venv/bin/python 03_procesar_mision.py --mision vuelos/no_way_points --vuelo vuelo_20261112_140256 --sin-llm

Los informes quedan en salida/vuelos/<mision>__<vuelo>/reporte.md y se ven también en el servidor web.
"""
import argparse
import shutil
from pathlib import Path

import config
from servidor import trabajos
from src.pipeline import TIPOS_RUTA


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mision", required=True, help="Carpeta de la misión (contiene tierra_*/vuelo_*)")
    ap.add_argument("--vuelo", action="append", help="Procesar solo este vuelo (se puede repetir)")
    ap.add_argument("--tipo-ruta", choices=sorted(TIPOS_RUTA), default="general")
    ap.add_argument("--sin-llm", action="store_true", help="Informe con plantillas, sin IA generativa")
    ap.add_argument("--solo-informe", action="store_true",
                    help="Rehace solo la redacción, reutilizando el análisis de video anterior")
    args = ap.parse_args()

    origen = Path(args.mision).resolve()
    nombre = origen.name
    destino = (config.DIR_MISIONES / nombre).resolve()
    if origen != destino:                      # el servidor busca las misiones en vuelos/<mision>
        print(f"Copiando misión a {destino} ...")
        shutil.copytree(origen, destino, dirs_exist_ok=True)

    listos = dict(trabajos.vuelos_listos(nombre))
    elegidos = args.vuelo or list(listos)
    if not elegidos:
        raise SystemExit("No hay vuelos con video en la misión.")
    resumen = []
    for vuelo in elegidos:
        if vuelo not in listos:
            print(f"- {vuelo}: sin video que lo cubra, se omite")
            continue
        jid = trabajos.id_mision(nombre, vuelo)
        trabajos.dir_vuelo(jid).mkdir(parents=True, exist_ok=True)
        trabajos.crear(jid, {"tipo": "mision", "mision": nombre, "vuelo": vuelo,
                             "tipo_ruta": args.tipo_ruta, "usar_llm": not args.sin_llm,
                             "solo_informe": args.solo_informe,
                             "nombre": f"{nombre} / {vuelo}"})
        print(f"\n=== {vuelo} ({', '.join(listos[vuelo])})")
        est = trabajos.procesar_ahora(jid)
        ruta = trabajos.dir_vuelo(jid) / "reporte.md"
        resumen.append((vuelo, est["estado"], est.get("metodo_informe"), est.get("niveles_riesgo"),
                        est.get("error"), ruta))

    print("\nResumen:")
    for vuelo, estado, metodo, niveles, error, ruta in resumen:
        if estado == "listo":
            print(f"  {vuelo}: {metodo}, riesgos {niveles} -> {ruta}")
        else:
            print(f"  {vuelo}: ERROR {error}")


if __name__ == "__main__":
    main()
