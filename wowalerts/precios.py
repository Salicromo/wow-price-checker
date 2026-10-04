"""El precio a batir en cada reino, para la app del movil.

Responde a la pregunta que la cobertura sola no contesta: vale, a Garona le
falta este objeto, pero ¿a cuanto tendria que ponerlo? Con el minimo del reino
delante se decide en el sitio si merece la pena entrar.

El dato solo existe durante la pasada: el volcado de un reino son decenas de
miles de subastas que se miran y se tiran. Aqui se guarda lo unico que hace
falta --el mas barato de cada objeto e ilvl-- para poder publicarlo.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .ilvl import resolve_ilvl

log = logging.getLogger(__name__)

VERSION = 1

# Clave de los objetos que no escalan, donde el ilvl no significa nada.
SIN_ILVL = "plano"


def minimos_del_reino(
    auctions: Iterable[Mapping[str, Any]],
    vigilados: set[int],
    bonus_ilvl_map: Mapping[int, int],
) -> dict[tuple[int, int | None], tuple[int, int]]:
    """El mas barato y cuantos hay, por objeto e ilvl, en un volcado de reino.

    El precio es SIEMPRE por unidad: un lote de cinco a 500.000 compite contra
    una suelta a 100.000, no a 500.000, y comparar el precio del lote con el de
    la unidad haria parecer caro lo que es barato.
    """
    minimos: dict[tuple[int, int | None], tuple[int, int]] = {}

    for auction in auctions:
        item = auction.get("item") or {}
        item_id = item.get("id")
        if item_id not in vigilados:
            continue

        # Sin compra directa no hay precio que batir: una puja no se puede
        # comprar y no marca el suelo del mercado.
        buyout = auction.get("buyout")
        if not isinstance(buyout, int) or buyout <= 0:
            continue

        cantidad = auction.get("quantity")
        if not isinstance(cantidad, int) or cantidad <= 0:
            cantidad = 1
        unidad = buyout // cantidad

        clave = (item_id, resolve_ilvl(item, bonus_ilvl_map).value)
        anterior = minimos.get(clave)
        if anterior is None:
            minimos[clave] = (unidad, 1)
        else:
            minimos[clave] = (min(anterior[0], unidad), anterior[1] + 1)

    return minimos


def reinos_a_vigilar(
    reino_por_personaje: Mapping[str, str], orden: Sequence[str]
) -> set[str]:
    """Los reinos donde de verdad vendes.

    Solo los de los personajes del `orden_personajes`: bajarse los 92 reinos de
    la region para mirar veinte seria tirar tiempo y cuota de la API.
    """
    reinos = set()
    for personaje in orden:
        reino = reino_por_personaje.get(personaje)
        if reino:
            reinos.add(reino)
    return reinos


def _precios_json(
    minimos: Mapping[tuple[int, int | None], tuple[int, int]],
) -> dict[str, dict[str, Any]]:
    precios: dict[str, dict[str, Any]] = {}
    for (item_id, ilvl), (minimo, cuantas) in minimos.items():
        clave_ilvl = SIN_ILVL if ilvl is None else str(ilvl)
        precios.setdefault(str(item_id), {})[clave_ilvl] = {
            "min": minimo,
            "n": cuantas,
        }
    return precios


def construir_precios(
    por_reino: Mapping[str, tuple[Mapping[tuple[int, int | None], tuple[int, int]], int]],
    generado: int,
) -> dict[str, Any]:
    """El fichero que se publica, listo para escribir.

    Cada reino lleva su propio `visto`. Es lo que permite distinguir en el movil
    entre "ahi no lo vende nadie" --que es justo donde quieres entrar-- y "ese
    reino no se ha podido mirar esta hora", que no dice nada. Sin esa marca las
    dos cosas se verian igual: sin precio.
    """
    reinos: dict[str, Any] = {}
    for slug, (minimos, visto) in por_reino.items():
        reinos[slug] = {"visto": visto, "precios": _precios_json(minimos)}

    return {"version": VERSION, "generado": generado, "reinos": reinos}
