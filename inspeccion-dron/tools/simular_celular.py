"""Simula lo que hará la app del celular: sube un vuelo al servidor, espera y descarga el informe.

Uso (desde inspeccion-dron/, con el servidor ya levantado):
    venv/bin/python tools/simular_celular.py
    venv/bin/python tools/simular_celular.py --servidor http://192.168.1.50:8000 --tipo-ruta vehiculo
Por defecto usa el escenario de data/demo/ (generar antes con tools/generar_escenario_demo.py).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor", default="http://localhost:8000")
    ap.add_argument("--video", default=DEMO / "ruta_demo.mp4", type=Path)
    ap.add_argument("--telemetria", default=DEMO / "ruta_demo_telemetria.json", type=Path)
    ap.add_argument("--meta", default=DEMO / "ruta_demo_meta.json", type=Path)
    ap.add_argument("--tipo-ruta", default="a_pie", choices=["a_pie", "vehiculo", "general"])
    ap.add_argument("--nombre", default="Ruta demo sintética")
    ap.add_argument("--token", default="", help="Valor de API_TOKEN si el servidor lo exige")
    a = ap.parse_args()

    base = a.servidor.rstrip("/")
    h = {"X-API-Key": a.token} if a.token else {}
    if not a.video.exists():
        sys.exit(f"No existe {a.video}. Ejecuta primero: venv/bin/python tools/generar_escenario_demo.py")

    datos = {"tipo_ruta": a.tipo_ruta, "nombre": a.nombre,
             # como haría la app: la telemetría va como texto JSON y el inicio como campo
             "telemetria_json": a.telemetria.read_text(encoding="utf-8")}
    if a.meta.exists():
        datos["video_start_epoch_ms"] = json.loads(a.meta.read_text())["video_start_epoch_ms"]

    print(f"Subiendo {a.video.name} ({a.video.stat().st_size / 1e6:.1f} MB) a {base} ...")
    with open(a.video, "rb") as fv:
        r = requests.post(f"{base}/api/vuelos", headers=h, data=datos,
                          files={"video": (a.video.name, fv, "video/mp4")}, timeout=600)
    if r.status_code != 202:
        sys.exit(f"Error {r.status_code}: {r.text}")
    vid = r.json()["id"]
    print("Vuelo aceptado, id:", vid)

    ultimo = None
    while True:
        e = requests.get(f"{base}/api/vuelos/{vid}", headers=h, timeout=30).json()
        linea = f"  [{e['estado']}] {e['progreso']:.0%} {e['mensaje']}"
        if linea != ultimo:
            print(linea)
            ultimo = linea
        if e["estado"] in ("listo", "error"):
            break
        time.sleep(2)
    if e["estado"] == "error":
        sys.exit(f"Falló: {e['error']}")

    informe = requests.get(f"{base}/api/vuelos/{vid}/informe", headers=h, timeout=30).text
    print("\n" + "=" * 70 + "\n" + informe + "\n" + "=" * 70)
    q = f"?token={a.token}" if a.token else ""
    print(f"Informe en el navegador: {base}/vuelos/{vid}{q}")


if __name__ == "__main__":
    main()
