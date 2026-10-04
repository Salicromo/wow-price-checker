"""Las horas en las que no quieres que suene nada.

El silencio afecta al ENVIO, no a la deteccion: las pasadas siguen corriendo y
el estado sigue actualizandose. Eso importa mucho en las ventas, cuyo
seguimiento se apoya en ver la subasta hora tras hora; saltarse ocho pasadas
seguidas degradaria las cotas y se tragaria ventas de verdad.

Lo que se calla se recupera solo: los chollos y los undercuts no se marcan como
avisados hasta que salen, asi que a la hora de despertar se envia lo que siga
vivo. Las ventas se quedan pendientes y se deciden al terminar la ventana, con
la hora en la que la subasta desaparecio de verdad.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class HoraInvalida(Exception):
    """La ventana de silencio esta mal configurada."""


def zona(nombre: str) -> ZoneInfo:
    """La zona horaria pedida, o un error que se entienda."""
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HoraInvalida(
            f"No conozco la zona horaria {nombre!r}. Usa un nombre de la base "
            "de datos IANA, como 'Europe/Madrid' o 'America/New_York'."
        ) from exc


def hora_local(ahora: datetime, zona_horaria: str) -> int:
    """La hora del reloj en tu zona.

    Hace falta porque las pasadas corren en GitHub Actions, cuyo reloj va en
    UTC: en verano Madrid va dos horas por delante y en invierno una, asi que
    una ventana escrita en UTC se desplazaria sola con el cambio de hora.
    """
    return ahora.astimezone(zona(zona_horaria)).hour


def en_silencio(
    ahora: datetime, desde: int, hasta: int, zona_horaria: str
) -> bool:
    """Si a esa hora toca callarse.

    La hora de inicio entra y la de fin no: con 1 y 9, a las 09:00 ya suena.

    `desde == hasta` es una ventana vacia, no uno de 24 horas: apagar los avisos
    del todo se hace quitando la alerta, no configurandola.
    """
    hora = hora_local(ahora, zona_horaria)
    if desde == hasta:
        return False
    if desde < hasta:
        return desde <= hora < hasta
    # La ventana cruza la medianoche: de 22 a 6 son las horas >= 22 o < 6.
    return hora >= desde or hora < hasta
