"""Aplica a config.yaml la pausa o reanudacion de avisos que pide una issue.

    py aplicar_avisos.py < cuerpo.md         # el cuerpo de la issue por stdin
    py aplicar_avisos.py --dry-run < x.md    # sin escribir nada

Es el interruptor de avisos de la app. Como con los topes, la app no escribe
config.yaml: abre una issue titulada "Avisos: ..." y el workflow avisos.yml
llama a esto. Por stdout sale el comentario para la issue, vaya bien o mal; el
codigo de salida le dice al workflow si commitear y cerrar (0) o no (1).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from aplicar_tope import SIN_RESPUESTA, _campos
from wowalerts.avisos import AvisosError, poner_pausa
from wowalerts.config import ConfigError, load_config

EXIT_OK = 0
EXIT_ERROR = 1

# La etiqueta del campo: el contrato con la app y con la plantilla de la issue.
CAMPO_AVISOS = "Avisos"
PAUSAR = "pausar"
REANUDAR = "reanudar"


def parsear(cuerpo: str) -> bool:
    """True si la issue pide pausar, False si pide reanudar."""
    orden = _campos(cuerpo).get(CAMPO_AVISOS, "").strip().lower()
    if orden == PAUSAR:
        return True
    if orden == REANUDAR:
        return False
    if not orden or orden == SIN_RESPUESTA.lower():
        raise AvisosError(f"Falta el campo '{CAMPO_AVISOS}'.")
    raise AvisosError(
        f"'{CAMPO_AVISOS}' tiene que ser Pausar o Reanudar, no {orden!r}."
    )


def verificar(nuevo: str, pausar: bool) -> None:
    """Recarga el resultado: si la edicion lo ha roto, no se commitea."""
    ruta = Path(tempfile.mkdtemp()) / "config.yaml"
    ruta.write_text(nuevo, encoding="utf-8")
    try:
        quedo = load_config(ruta).settings.avisos_pausados
    except ConfigError as fallo:
        raise AvisosError(
            f"El config.yaml resultante no es valido, asi que no lo toco: {fallo}"
        ) from fallo
    if quedo is not pausar:
        raise AvisosError("La pausa no ha quedado como se pedia. No cambio nada.")


def _ok(pausar: bool) -> str:
    if pausar:
        return (
            "⏸️ **Avisos pausados.**\n\n"
            "Desde la pasada siguiente sigo vigilando pero no mando nada a "
            "Discord. Al reanudar te llega lo que siga vigente."
        )
    return (
        "▶️ **Avisos reanudados.**\n\n"
        "La pasada siguiente vuelve a avisar, y trae lo que siga vigente de lo "
        "que se callo durante la pausa."
    )


def _error(fallo: Exception) -> str:
    return (
        "❌ **No he cambiado nada.**\n\n"
        f"{fallo}\n\n"
        "Esta issue se queda abierta para que puedas verla."
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pausa o reanuda los avisos en config.yaml.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribe el fichero: solo dice que haria.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    ruta = Path(args.config)

    try:
        pausar = parsear(sys.stdin.read())
        texto = ruta.read_text(encoding="utf-8")
        nuevo = poner_pausa(texto, pausar)
        verificar(nuevo, pausar)
    except (AvisosError, OSError) as fallo:
        print(_error(fallo))
        return EXIT_ERROR

    if not args.dry_run:
        ruta.write_text(nuevo, encoding="utf-8")

    print(_ok(pausar))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
