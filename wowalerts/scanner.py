"""Deteccion de chollos en las subastas de un reino.

La regla de negocio vive aqui y es pura: recibe subastas ya descargadas y
devuelve chollos. Eso permite probarla entera sin tocar la red.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from .blizzard import BlizzardClient, BlizzardError
from .config import COPPER_PER_GOLD, Config, ItemRule
from .ilvl import resolve_ilvl

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Deal:
    """Una subasta cuyo precio de compra directa esta bajo el umbral."""

    auction_id: int
    item_id: int
    item_name: str
    ilvl: int | None
    ilvl_confirmed: bool
    price_copper: int
    threshold_copper: int
    realm_id: int
    quantity: int = 1
    time_left: str = ""
    # El objeto no depende del ilvl (un patron es un patron), asi que no hay
    # ilvl que confirmar ni que ensenar.
    sin_ilvl: bool = False
    # Especie, cuando el chollo es una mascota. Hace falta para enlazarla: por
    # item_id todas serian la misma jaula.
    pet_species_id: int | None = None

    @property
    def price_gold(self) -> int:
        return self.price_copper // COPPER_PER_GOLD

    @property
    def threshold_gold(self) -> int:
        return self.threshold_copper // COPPER_PER_GOLD

    @property
    def discount_pct(self) -> float:
        """Cuanto por debajo del umbral esta, en porcentaje."""
        if self.threshold_copper <= 0:
            return 0.0
        return (1 - self.price_copper / self.threshold_copper) * 100


@dataclass
class ScanResult:
    """Resumen de una pasada completa."""

    deals: list[Deal] = field(default_factory=list)
    realms_ok: int = 0
    realms_failed: list[int] = field(default_factory=list)
    auctions_seen: int = 0
    # Hora del volcado de datos de Blizzard. Toda la region comparte volcado,
    # asi que basta con quedarse con el mas reciente que se haya visto.
    snapshot_at: datetime | None = None

    @property
    def realms_total(self) -> int:
        return self.realms_ok + len(self.realms_failed)

    @property
    def failure_ratio(self) -> float:
        return len(self.realms_failed) / self.realms_total if self.realms_total else 0.0


def find_deals(
    auctions: Sequence[Mapping],
    realm_id: int,
    rules_by_item_id: Mapping[int, ItemRule],
    bonus_ilvl_map: Mapping[int, int],
    alert_on_unconfirmed_ilvl: bool = True,
    rules_by_species: Mapping[int, ItemRule] | None = None,
) -> list[Deal]:
    """Filtra las subastas de un reino y devuelve los chollos."""
    deals: list[Deal] = []
    rules_by_species = rules_by_species or {}

    for auction in auctions:
        item_obj = auction.get("item") or {}
        item_id = item_obj.get("id")
        if not isinstance(item_id, int):
            continue

        # Las mascotas se casan por especie: todas comparten el objeto 82800, y
        # buscarlas por item_id daria la misma regla para cualquiera de ellas.
        especie = item_obj.get("pet_species_id")
        if isinstance(especie, int) and not isinstance(especie, bool):
            rule = rules_by_species.get(especie)
        else:
            especie = None
            rule = rules_by_item_id.get(item_id)
        if rule is None:
            continue

        # Solo compra directa: una subasta sin buyout no se puede comprar al
        # instante, y tomar su puja como precio genera chollos que no existen.
        price_copper = auction.get("buyout")
        if not isinstance(price_copper, int) or isinstance(price_copper, bool) or price_copper <= 0:
            log.debug(
                "Ignorada subasta %s de %s en reino %s: sin compra directa",
                auction.get("id"),
                rule.name,
                realm_id,
            )
            continue

        ilvl = resolve_ilvl(item_obj, bonus_ilvl_map)

        if rule.sin_ilvl:
            # Precio unico: el ilvl que traiga la subasta no cambia lo que vale,
            # asi que ni se mira ni se ensena.
            threshold_gold = rule.max_price
        elif ilvl.value is not None:
            threshold_gold = rule.threshold_gold(ilvl.value)
            if threshold_gold is None:
                # Ese ilvl no esta en la tabla del objeto: no interesa.
                continue
        elif alert_on_unconfirmed_ilvl:
            threshold_gold = rule.cheapest_threshold_gold
        else:
            continue

        threshold_copper = threshold_gold * COPPER_PER_GOLD

        log.debug(
            "Vista %s | %s g | ilvl %s (%s) | umbral %s g | reino %s",
            rule.name,
            price_copper // COPPER_PER_GOLD,
            ilvl.value,
            ilvl.source,
            threshold_gold,
            realm_id,
        )

        # La comparacion va en cobre a proposito: convertir a oro antes de
        # comparar redondearia hacia abajo y dejaria pasar precios por encima.
        if price_copper > threshold_copper:
            continue

        deals.append(
            Deal(
                auction_id=int(auction.get("id", 0)),
                item_id=item_id,
                item_name=rule.name,
                ilvl=None if rule.sin_ilvl else ilvl.value,
                ilvl_confirmed=ilvl.confirmed and not rule.sin_ilvl,
                price_copper=price_copper,
                threshold_copper=threshold_copper,
                realm_id=realm_id,
                quantity=int(auction.get("quantity", 1) or 1),
                time_left=str(auction.get("time_left", "")),
                sin_ilvl=rule.sin_ilvl,
                pet_species_id=especie,
            )
        )

    return deals


def scan_realms(
    client: BlizzardClient,
    config: Config,
    realm_ids: Sequence[int],
    rules_by_item_id: Mapping[int, ItemRule],
    rules_by_species: Mapping[int, ItemRule] | None = None,
) -> ScanResult:
    """Escanea todos los reinos en paralelo y agrega los resultados."""
    result = ScanResult()

    def scan_one(realm_id: int):
        try:
            snapshot = client.auctions(realm_id)
        except BlizzardError as exc:
            log.warning("Reino %s: %s", realm_id, exc)
            return realm_id, None, 0, None
        deals = find_deals(
            snapshot.auctions,
            realm_id,
            rules_by_item_id,
            config.bonus_ilvl_map,
            config.settings.alert_on_unconfirmed_ilvl,
            rules_by_species,
        )
        return realm_id, deals, len(snapshot.auctions), snapshot.taken_at

    workers = min(config.settings.max_workers, max(len(realm_ids), 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for realm_id, deals, auction_count, taken_at in executor.map(scan_one, realm_ids):
            if deals is None:
                result.realms_failed.append(realm_id)
                continue
            result.realms_ok += 1
            result.auctions_seen += auction_count
            result.deals.extend(deals)
            if taken_at and (result.snapshot_at is None or taken_at > result.snapshot_at):
                result.snapshot_at = taken_at

    result.deals.sort(key=lambda deal: deal.discount_pct, reverse=True)
    return result
