"""Deduccion del nivel de objeto (ilvl) de una subasta.

Blizzard no publica el ilvl de una subasta de equipo directamente: lo codifica
en una lista de "bonus ids". Este modulo intenta tres vias, de la mas fiable a
la menos fiable, y dice por cual lo ha sacado para poder depurarlo.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

# Los modificadores de subasta comparten el tipo 9 para varias cosas segun el
# objeto (nivel de escalado, ilvl...). Un valor por debajo de esto casi seguro
# que es un nivel de personaje, no un ilvl, asi que no nos fiamos.
MIN_PLAUSIBLE_ILVL = 100

# Tipo de modificador que en el equipo escalable lleva el ilvl.
MODIFIER_TYPE_ILVL = 9


@dataclass(frozen=True)
class IlvlResult:
    """Resultado de intentar deducir el ilvl.

    `value` es None cuando no se ha podido determinar; `source` sirve para los
    logs, de modo que se vea que via ha funcionado (o que no ha funcionado
    ninguna).
    """

    value: int | None
    source: str

    @property
    def confirmed(self) -> bool:
        return self.value is not None


def resolve_ilvl(item_obj: Mapping, bonus_ilvl_map: Mapping[int, int]) -> IlvlResult:
    """Deduce el ilvl del objeto de una subasta.

    Se prueba en este orden:

    1. El mapa `bonus_ilvl_map` del config. Es la tabla curada a mano, y la
       unica que distingue con precision entre normal/heroico/mitico.
    2. El campo `item_level`, si Blizzard lo incluye.
    3. El modificador de tipo 9, descartando valores implausibles.
    """
    for bonus_id in int_list(item_obj.get("bonus_lists")):
        if bonus_id in bonus_ilvl_map:
            return IlvlResult(bonus_ilvl_map[bonus_id], f"bonus_id:{bonus_id}")

    item_level = item_obj.get("item_level")
    if isinstance(item_level, int) and not isinstance(item_level, bool) and item_level > 0:
        return IlvlResult(item_level, "item_level")

    modifiers = item_obj.get("modifiers")
    if isinstance(modifiers, list):
        for modifier in modifiers:
            if not isinstance(modifier, Mapping):
                continue
            if modifier.get("type") != MODIFIER_TYPE_ILVL:
                continue
            value = modifier.get("value")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= MIN_PLAUSIBLE_ILVL
            ):
                return IlvlResult(value, "modifier:9")

    return IlvlResult(None, "desconocido")


def int_list(value: object) -> list[int]:
    """Los enteros de una lista, ignorando lo que no lo sea."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, int) and not isinstance(item, bool)]
