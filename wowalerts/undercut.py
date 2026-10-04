"""Deteccion de undercuts sobre tus propias subastas.

La regla vive aqui y es pura: recibe las subastas de un reino ya descargadas y
tus publicaciones ya leidas, y devuelve quien te ha adelantado. Igual que
`scanner.find_deals`, eso permite probarla entera sin tocar la red.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from .config import COPPER_PER_GOLD
from .ilvl import int_list, resolve_ilvl
from .misubastas import MyAuction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Rival:
    """Una subasta ajena del mismo objeto, con lo que hace falta para comparar."""

    auction_id: int
    price_copper: int
    bonus_ids: frozenset
    ilvl: int | None


def _compite_con(rival: _Rival, mine: MyAuction) -> bool:
    """Decide si esa subasta ajena es el mismo producto que la tuya.

    Dos vias, y basta con una:

    - Si el ilvl del rival se puede determinar, tiene que ser el tuyo. Un ilvl
      distinto es otro producto por mucho que el objeto sea el mismo.
    - Si no se puede determinar, se exige que los bonus ids coincidan. Los bonus
      ids describen la version exacta del objeto, asi que dos subastas que los
      comparten son intercambiables aunque no sepamos que ilvl tienen.

    Lo que queda fuera es justo lo que generaba las falsas alarmas: un rival de
    ilvl desconocido y bonus distintos, que sobre datos reales resulto ser
    chatarra de 100 g compitiendo contra subastas de 10.000.
    """
    if rival.ilvl is not None:
        return rival.ilvl == mine.ilvl
    return rival.bonus_ids == frozenset(mine.bonus_ids)


def _va_por_delante(rival: _Rival, mine: MyAuction) -> bool:
    """Decide si esa subasta te ha adelantado a ti, y no al reves.

    Mas barata siempre adelanta, se publicara cuando se publicara. Al mismo
    precio, en cambio, solo te adelanta la que se publico *despues* de la tuya:
    si ya estaba ahi cuando tu publicaste, no te ha quitado el sitio, es que
    llegaste tu segundo y lo sabias.

    El orden se deduce del id de subasta, que crece con el tiempo dentro de un
    mismo reino.
    """
    if rival.price_copper < mine.buyout_copper:
        return True
    return (
        rival.price_copper == mine.buyout_copper
        and rival.auction_id > mine.auction_id
    )


@dataclass(frozen=True)
class Undercut:
    """Una subasta tuya con al menos un rival a su precio o por debajo."""

    mine: MyAuction
    rival_auction_id: int
    rival_price_copper: int
    rivals_ahead: int
    # El reino conectado donde se ha visto. Lo necesita la memoria de avisos,
    # porque los ids de subasta solo son unicos dentro de su reino.
    realm_id: int = 0

    @property
    def my_price_gold(self) -> int:
        return self.mine.buyout_copper // COPPER_PER_GOLD

    @property
    def rival_price_gold(self) -> int:
        return self.rival_price_copper // COPPER_PER_GOLD

    @property
    def gap_copper(self) -> int:
        """Cuanto mas barato esta el rival. Cero si te ha igualado."""
        return self.mine.buyout_copper - self.rival_price_copper

    @property
    def gap_gold(self) -> int:
        return self.gap_copper // COPPER_PER_GOLD

    @property
    def tied(self) -> bool:
        return self.gap_copper == 0


def find_undercuts(
    auctions: Sequence[Mapping],
    my_auctions: Sequence[MyAuction],
    bonus_ilvl_map: Mapping[int, int],
    realm_id: int = 0,
) -> list[Undercut]:
    """Devuelve una entrada por cada subasta tuya que alguien haya adelantado.

    Un rival cuenta si vende exactamente el mismo producto: mismo objeto y
    mismos bonus ids. Si los bonus ids no coinciden pero ambos ilvl se pueden
    determinar y son iguales, tambien cuenta. Cuando no se puede saber, no se
    avisa: sobre datos reales, comparar contra rivales de ilvl desconocido
    generaba solo falsas alarmas (chatarra de 100 g contra subastas de 10.000).

    Las comparaciones de precio van siempre en cobre: convertir a oro antes de
    comparar redondearia hacia abajo y colaria como empate un precio que no lo es.
    """
    if not my_auctions:
        return []

    mias_por_id = {m.auction_id: m for m in my_auctions}
    objetos_vigilados = {m.item_id for m in my_auctions}

    # Solo interesa saber si siguen vivas las tuyas, no las 30.000 del reino.
    vivas: set[int] = set()
    rivales: dict[int, list[_Rival]] = defaultdict(list)

    for auction in auctions:
        auction_id = auction.get("id")
        if not isinstance(auction_id, int) or isinstance(auction_id, bool):
            continue

        if auction_id in mias_por_id:
            vivas.add(auction_id)
            continue

        item_obj = auction.get("item") or {}
        item_id = item_obj.get("id")
        if item_id not in objetos_vigilados:
            continue

        # Sin compra directa no compite en precio con la tuya.
        price = auction.get("buyout")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            continue

        rivales[item_id].append(
            _Rival(
                auction_id=auction_id,
                price_copper=price,
                bonus_ids=frozenset(int_list(item_obj.get("bonus_lists"))),
                ilvl=resolve_ilvl(item_obj, bonus_ilvl_map).value,
            )
        )

    undercuts: list[Undercut] = []

    for mine in my_auctions:
        if mine.auction_id not in vivas:
            log.debug(
                "Tu subasta %s de %s ya no esta en la casa de subastas: "
                "vendida, caducada o cancelada.",
                mine.auction_id,
                mine.item_name,
            )
            continue

        delante = [
            rival
            for rival in rivales.get(mine.item_id, [])
            if _va_por_delante(rival, mine) and _compite_con(rival, mine)
        ]
        if not delante:
            continue

        mejor = min(delante, key=lambda r: r.price_copper)
        auction_id, precio = mejor.auction_id, mejor.price_copper

        undercuts.append(
            Undercut(
                mine=mine,
                rival_auction_id=auction_id,
                rival_price_copper=precio,
                rivals_ahead=len(delante),
                realm_id=realm_id,
            )
        )

    undercuts.sort(key=lambda u: u.gap_copper, reverse=True)
    return undercuts
