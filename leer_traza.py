"""Dice donde se va el tiempo del reposteo, leyendo la traza del addon.

El addon apunta cada pulsacion y cada respuesta del juego con su marca de
tiempo. Esto lo lee y lo resume: cuanto tarda cada busqueda, cuanto dura un
escaneo entero, cuantas pulsaciones no hicieron nada y por que, y a que ritmo
se recogen las cartas del buzon.

Sirve para optimizar con numeros en vez de a ojo. Juega una sesion normal, haz
/reload (WoW solo escribe SavedVariables al recargar o al salir) y ejecutalo.

    py leer_traza.py                    # todas tus cuentas de WoW
    py leer_traza.py --fichero RUTA     # un SavedVariables concreto
    py leer_traza.py --lineas 40        # ademas, las ultimas lineas tal cual
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sync_subastas import detectar_wow_root
from wowalerts.misubastas import MisSubastasError, encontrar_savedvariables
from wowalerts.traza import analizar, formatear, leer_traza

log = logging.getLogger("traza")

EXIT_OK = 0
EXIT_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="leer_traza.py",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "--fichero",
        help="Un WowAlertsExport.lua concreto, en vez de buscarlos todos.",
    )
    parser.add_argument(
        "--wow-root",
        help="Carpeta _retail_ de WoW, si no esta donde suele.",
    )
    parser.add_argument(
        "--lineas",
        type=int,
        default=0,
        metavar="N",
        help="Ademas del resumen, las ultimas N lineas de la traza tal cual.",
    )
    return parser


def ficheros_a_leer(args: argparse.Namespace) -> list[Path]:
    """Los SavedVariables que hay que mirar, o una lista vacia si no hay."""
    if args.fichero:
        return [Path(args.fichero)]

    raiz = Path(args.wow_root) if args.wow_root else detectar_wow_root()
    if raiz is None:
        log.error(
            "❌ No encuentro la carpeta de WoW. Pasala con --wow-root, o el "
            "fichero directamente con --fichero."
        )
        return []
    return encontrar_savedvariables(raiz)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ficheros = ficheros_a_leer(args)
    if not ficheros:
        if not args.fichero and not args.wow_root:
            return EXIT_ERROR
        log.error("❌ No hay ningun WowAlertsExport.lua que leer.")
        return EXIT_ERROR

    for fichero in ficheros:
        try:
            lineas = leer_traza(fichero)
        except MisSubastasError as exc:
            log.error("❌ %s", exc)
            return EXIT_ERROR

        # El nombre de la carpeta de cuenta ('403840080#2') distingue un
        # fichero de otro mucho mejor que la ruta entera.
        titulo = fichero.parent.parent.name or str(fichero)
        print(formatear(analizar(lineas), titulo))

        if args.lineas and lineas:
            print()
            for linea in lineas[-args.lineas :]:
                print(f"   {linea.hora} {linea.reloj:10.1f}  {linea.texto}")
        print()

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
