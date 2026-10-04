"""Resolucion de los nombres del config a ids de objeto de Blizzard."""

from __future__ import annotations

import logging

from .blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from .config import Config, ItemRule
from .state import ItemIdCache

log = logging.getLogger(__name__)


class ItemResolutionError(Exception):
    """No se ha podido identificar ni uno solo de los objetos vigilados."""


def resolve_item_ids(
    client: BlizzardClient, config: Config, cache: ItemIdCache
) -> dict[int, ItemRule]:
    """Devuelve {item_id: regla} para todos los objetos del config.

    Orden de preferencia: el `item_id` fijado a mano en el config, la busqueda
    en la API, y como ultimo recurso el id cacheado de una ejecucion anterior
    (asi un fallo puntual de la busqueda no deja de vigilar el objeto).
    """
    resolved: dict[int, ItemRule] = {}
    unresolved: list[str] = []

    for rule in config.items:
        # Las mascotas no tienen objeto que buscar: van por especie y viven en
        # su propio mapa (ver `reglas_por_especie`).
        if rule.es_mascota:
            continue

        item_id = rule.item_id
        if item_id is not None:
            log.debug("%s: id %s fijado en el config", rule.name, item_id)
        else:
            item_id = _search(client, rule.name) or cache.get(rule.name)

        if item_id is None:
            unresolved.append(rule.name)
            continue

        if item_id in resolved:
            log.warning(
                "%r y %r comparten el id %s; me quedo con el primero.",
                resolved[item_id].name,
                rule.name,
                item_id,
            )
            continue

        resolved[item_id] = rule
        cache.set(rule.name, item_id)
        log.info("  ✓ %s -> id %s", rule.name, item_id)

    if unresolved:
        log.warning(
            "No he identificado %s objeto(s): %s. Revisa que el nombre este "
            "escrito exactamente como en el juego, en ingles.",
            len(unresolved),
            ", ".join(unresolved),
        )

    if not resolved and not any(r.es_mascota for r in config.items):
        raise ItemResolutionError(
            "No he podido identificar ninguno de los objetos del config.\n"
            "Los nombres deben coincidir exactamente con los del juego en ingles. "
            "Si el nombre es correcto, anade 'item_id' a mano en config.yaml."
        )

    return resolved


def reglas_por_especie(config: Config) -> dict[int, ItemRule]:
    """Devuelve {pet_species_id: regla} para las mascotas del config.

    Van aparte de los objetos a proposito. En las subastas todas las mascotas
    son el objeto 82800, asi que meterlas en el mapa por item_id haria que una
    regla para una avisara de todas --y de paso ensuciaria el seguimiento de
    undercuts y ventas, que tambien casa por item_id--.
    """
    reglas: dict[int, ItemRule] = {}
    for rule in config.items:
        if not rule.es_mascota:
            continue
        especie = rule.pet_species_id
        if especie in reglas:
            log.warning(
                "%r y %r vigilan la misma especie %s; me quedo con la primera.",
                reglas[especie].name,
                rule.name,
                especie,
            )
            continue
        reglas[especie] = rule
        log.info("  ✓ %s -> especie %s", rule.name, especie)
    return reglas


def _search(client: BlizzardClient, name: str) -> int | None:
    try:
        return client.search_item_id(name)
    except BlizzardAuthError:
        # Un fallo de credenciales afecta a todos los objetos por igual: seguir
        # intentandolo solo produciria nueve avisos identicos y un mensaje final
        # enganoso sobre nombres mal escritos.
        raise
    except BlizzardError as exc:
        log.warning("Busqueda de %r fallida (%s); tirare de cache si la hay.", name, exc)
        return None
