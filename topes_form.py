"""Genera el formulario de desplegables para ajustar un tope.

    py topes_form.py            # reescribe .github/ISSUE_TEMPLATE/tope.yml
    py topes_form.py --check    # solo dice si esta al dia (para los tests)

Las opciones de un desplegable de GitHub son estaticas dentro del fichero de
plantilla, asi que se quedan atras en cuanto anades o quitas un objeto de
config.yaml. Por eso se generan desde ahi, y por eso tests/test_topes_form.py
falla si la plantilla en disco no coincide: asi te enteras al pasar los tests y
no con el desplegable delante.

No se regenera en la pasada horaria a proposito. Eso ensuciaria main con un
commit por hora, que es justo lo que el proyecto evita publicando los datos de
la app en la rama 'datos'.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wowalerts.config import Config, load_config

EXIT_OK = 0
EXIT_DESACTUALIZADO = 1

DESTINO = Path(".github/ISSUE_TEMPLATE/tope.yml")

# La opcion para los objetos que no escalan. aplicar_tope.py la reconoce por su
# principio ("sin ilvl"), asi que el parentesis es solo para el que lee.
SIN_ILVL = "sin ilvl (precio unico)"

CABECERA = """\
# ============================================================================
#  GENERADO POR topes_form.py -- NO LO EDITES A MANO
# ----------------------------------------------------------------------------
#  Las opciones salen de config.yaml. Si anades o quitas un objeto alli, vuelve
#  a generarlo:
#      .venv\\Scripts\\python.exe topes_form.py
#  tests/test_topes_form.py falla mientras no lo hagas.
# ============================================================================
"""


def _cita(texto: str) -> str:
    """Un escalar YAML entrecomillado, que los nombres llevan apostrofos."""
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def construir(config: Config) -> str:
    """El fichero de plantilla entero, a partir de los objetos vigilados."""
    objetos = sorted(regla.name for regla in config.items)

    ilvls = sorted({
        ilvl for regla in config.items for ilvl in regla.max_price_by_ilvl
    })

    lineas = [
        CABECERA,
        "name: Ajustar un tope",
        "description: Cambia el precio maximo de un objeto que ya vigilas.",
        'title: "Tope: "',
        "labels: [tope]",
        "body:",
        "  - type: markdown",
        "    attributes:",
        "      value: |",
        "        Cambia el tope de un objeto que **ya** vigilas. Para empezar a",
        "        vigilar uno nuevo, usa la plantilla 'Anadir un objeto'. Para un",
        "        ilvl que no esta en su tabla, tambien: con una pieza que ya",
        "        vigilas, anade esos ilvl a su tabla.",
        "",
        "  - type: dropdown",
        "    id: objeto",
        "    attributes:",
        "      label: Objeto",
        "      options:",
    ]
    lineas += [f"        - {_cita(nombre)}" for nombre in objetos]
    lineas += [
        "    validations:",
        "      required: true",
        "",
        "  - type: dropdown",
        "    id: ilvl",
        "    attributes:",
        "      label: ilvl",
        "      description: >-",
        "        Los patrones, monturas y mascotas no escalan: para esos, elige",
        "        la ultima opcion.",
        "      options:",
    ]
    lineas += [f'        - "{ilvl}"' for ilvl in ilvls]
    lineas += [
        f"        - {_cita(SIN_ILVL)}",
        "    validations:",
        "      required: true",
        "",
        "  - type: input",
        "    id: tope",
        "    attributes:",
        "      label: Tope nuevo, en oro",
        "      placeholder: \"4000\"",
        "    validations:",
        "      required: true",
        "",
    ]
    return "\n".join(lineas)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera el formulario de issue para ajustar un tope.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--destino", default=str(DESTINO))
    parser.add_argument(
        "--check",
        action="store_true",
        help="No escribe: sale con 1 si la plantilla esta desactualizada.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    esperado = construir(load_config(args.config))
    destino = Path(args.destino)

    if args.check:
        actual = destino.read_text(encoding="utf-8") if destino.is_file() else None
        if actual == esperado:
            return EXIT_OK
        print(
            f"{destino} no coincide con config.yaml. Regeneralo con:\n"
            "    .venv\\Scripts\\python.exe topes_form.py",
            file=sys.stderr,
        )
        return EXIT_DESACTUALIZADO

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(esperado, encoding="utf-8")
    print(f"Escrito {destino}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
