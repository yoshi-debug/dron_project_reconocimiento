"""Paso 2: resultados_frames.csv -> agregación por tramo -> LLM -> reporte.md"""
import argparse
from pathlib import Path

from src.pipeline import TIPOS_RUTA, generar_reporte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resultados", required=True)
    ap.add_argument("--tipo-ruta", choices=sorted(TIPOS_RUTA), default="general")
    ap.add_argument("--sin-llm", action="store_true", help="Informe con plantillas, sin IA generativa")
    args = ap.parse_args()

    dir_salida = Path(args.resultados).parent
    r = generar_reporte(dir_salida, args.tipo_ruta, usar_llm=not args.sin_llm,
                        progreso=lambda f, m: print(f"  {m}"))
    print(f"Listo ({r['metodo_informe']}):", dir_salida / "reporte.md")


if __name__ == "__main__":
    main()
