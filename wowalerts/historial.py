"""El precio de tus objetos vigilados, dia a dia, en los ultimos 30 dias.

Cada pasada ve el mas barato de ahora en toda la region, y el volcado se tira
al acabar. Aqui se apunta el minimo de cada dia --el mas bajo de todas las
pasadas de ese dia-- y en que reino estaba, para que la app pueda decir si el
precio de hoy es bueno o si hace una semana estaba a la mitad.

Solo tus objetos: son los que compras, y guardar la region entera durante un
mes seria un fichero que el movil no tiene por que bajar.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from .buscador import COBRE_POR_ORO, Oferta
from .mercado import Clave

DIAS = 30

# Lo que no escala no tiene ilvl, y una clave de JSON tiene que ser texto.
SIN_VARIANTE = "-"

# {id: {variante: {"AAAA-MM-DD": [oro, reino]}}}
Historial = dict[str, dict[str, dict[str, list]]]


def minimos_de_ahora(
    ofertas: Mapping[Clave, Sequence[Oferta]],
    vigilados: Collection[int],
    nombres_de_grupo: Sequence[str],
) -> dict[tuple[int, int | None], tuple[int, str]]:
    """El mas barato de cada objeto vigilado y variante, en oro, y donde."""
    minimos = {}
    for clave, lista in ofertas.items():
        if clave.es_mascota or clave.id not in vigilados or not lista:
            continue
        grupo, cobre, _ = min(lista, key=lambda o: o[1])
        minimos[(clave.id, clave.variante)] = (cobre // COBRE_POR_ORO, nombres_de_grupo[grupo])
    return minimos


def apuntar(
    historial: Historial,
    dia: date,
    minimos: Mapping[tuple[int, int | None], tuple[int, str]],
) -> None:
    """Suma una pasada al dia: se queda el precio si es el mas bajo visto hoy."""
    hoy = dia.isoformat()
    for (item_id, variante), (oro, reino) in minimos.items():
        dias = historial.setdefault(str(item_id), {}).setdefault(
            SIN_VARIANTE if variante is None else str(variante), {}
        )
        previo = dias.get(hoy)
        if previo is None or oro < previo[0]:
            dias[hoy] = [oro, reino]


def recortar(historial: Historial, hoy: date, vigilados: Collection[int], dias: int = DIAS) -> None:
    """Fuera lo de hace mas de `dias` dias y los objetos que ya no vigilas."""
    desde = (hoy - timedelta(days=dias - 1)).isoformat()
    for item_id in list(historial):
        if int(item_id) not in vigilados:
            del historial[item_id]
            continue
        variantes = historial[item_id]
        for variante in list(variantes):
            variantes[variante] = {d: v for d, v in variantes[variante].items() if d >= desde}
            if not variantes[variante]:
                del variantes[variante]
        if not variantes:
            del historial[item_id]


def construir_historial(historial: Historial, generado: int) -> dict[str, Any]:
    """El fichero que baja la app: cada variante, del dia mas viejo al de hoy."""
    return {
        "version": 1,
        "generado": generado,
        "dias": DIAS,
        "objetos": {
            item_id: {
                variante: [[d, oro, reino] for d, (oro, reino) in sorted(dias.items())]
                for variante, dias in variantes.items()
            }
            for item_id, variantes in historial.items()
        },
    }
