"""Pausar o reanudar los avisos dentro de config.yaml, sin tocar nada mas.

Como en topes.py, se edita el texto y no se pasa por PyYAML: cargar y volcar el
fichero se llevaria por delante todos sus comentarios. El cambio es una sola
linea, `avisos_pausados:`, dentro del bloque `settings:`.

La red de seguridad esta en aplicar_avisos.py, que recarga el resultado con
load_config() antes de dejar que se commitee.
"""

from __future__ import annotations

import re

__all__ = ["AvisosError", "poner_pausa"]


class AvisosError(Exception):
    """No se puede aplicar el cambio. El mensaje explica por que."""


# La linea que ya existe, con su sangria y un posible comentario detras.
_LINEA = re.compile(
    r"^(?P<sangria>[ \t]+)avisos_pausados:[ \t]*(?:true|false)(?P<resto>[ \t]*(?:#.*)?)$",
    re.MULTILINE,
)
_SETTINGS = re.compile(r"^settings:[ \t]*(?:#.*)?$", re.MULTILINE)

_COMENTARIO = (
    "  # Lo cambia el interruptor de avisos de la app (ver aplicar_avisos.py).\n"
    "  # En pausa se sigue vigilando, pero no se envia nada a Discord.\n"
)


def poner_pausa(texto: str, pausar: bool) -> str:
    """El config.yaml con los avisos pausados o no, y el resto igual."""
    valor = "true" if pausar else "false"

    if _LINEA.search(texto):
        return _LINEA.sub(
            lambda m: f"{m['sangria']}avisos_pausados: {valor}{m['resto']}",
            texto,
            count=1,
        )

    nueva = f"{_COMENTARIO}  avisos_pausados: {valor}\n"
    settings = _SETTINGS.search(texto)
    if settings:
        # Justo debajo de 'settings:', antes de sus demas claves.
        corte = settings.end() + 1
        return texto[:corte] + nueva + texto[corte:]

    if texto and not texto.endswith("\n"):
        texto += "\n"
    return texto + "\nsettings:\n" + nueva
