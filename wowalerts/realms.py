"""Traduccion de nombres de reino a ids de connected realm.

Las subastas tuyas llegan con el nombre del reino tal y como se ve en el juego,
y la API las sirve por connected realm. Este modulo hace el puente, cacheando
el resultado porque un reino no cambia de grupo casi nunca.
"""

from __future__ import annotations

import logging
from typing import Iterable

from .blizzard import BlizzardError
from .misubastas import slugify_realm

log = logging.getLogger(__name__)


class RealmResolutionError(Exception):
    """No se ha podido averiguar a que connected realm pertenece un reino."""


def resolve_connected_realms(
    client,
    cache,
    realm_names: Iterable[str],
    strict: bool = True,
) -> dict[str, int]:
    """Devuelve {nombre de reino: connected realm id} para los reinos dados.

    La clave es el nombre tal cual lo escribe el juego, y no el slug, porque
    hay nombres de los que no se puede deducir ninguno: un reino ruso se llama
    'Ревущий фьорд' y su slug es 'revushchiy-fiord'. Quitarle a eso todo lo que
    no sea A-Z deja la cadena vacia, asi que la unica via es buscarlo por
    nombre en el indice de Blizzard.

    Con `strict=False` los reinos que fallen se omiten con un aviso en el log,
    en vez de tumbar la pasada entera: mas vale vigilar cinco reinos de seis que
    ninguno.
    """
    resultado: dict[str, int] = {}
    indice: list[dict] | None = None

    for nombre in dict.fromkeys(realm_names):
        cacheado = cache.get(nombre)
        if isinstance(cacheado, int):
            resultado[nombre] = cacheado
            continue

        slug = slugify_realm(nombre)
        realm_id = None

        if slug:
            try:
                realm_id = client.connected_realm_id_for(slug)
            except BlizzardError as exc:
                if strict:
                    raise RealmResolutionError(
                        f"No he podido consultar el reino {nombre!r}: {exc}"
                    ) from exc
                log.warning("Reino %s omitido: %s", nombre, exc)
                continue

        if realm_id is None:
            # El slug no vale, o no se ha podido construir. Segunda via: buscar
            # el slug oficial por nombre en el indice, que se pide una sola vez.
            if indice is None:
                indice = client.realm_index()
            oficial = _buscar_en_indice(indice, nombre)
            if oficial and oficial != slug:
                try:
                    realm_id = client.connected_realm_id_for(oficial)
                except BlizzardError as exc:
                    log.warning("Reino %s (%s) omitido: %s", nombre, oficial, exc)

        if realm_id is None:
            if strict:
                raise RealmResolutionError(
                    f"Blizzard no conoce ningun reino llamado {nombre!r}. "
                    "Comprueba el nombre en el juego."
                )
            log.warning("Reino %s omitido: Blizzard no lo conoce.", nombre)
            continue

        resultado[nombre] = realm_id
        cache.set(nombre, realm_id)

    return resultado


def _buscar_en_indice(indice: list[dict], nombre: str) -> str | None:
    """Slug oficial del reino que se llama asi, o None.

    Primero se compara el nombre entero contra los del reino en todos los
    idiomas, que es lo unico que salva a los reinos rusos. Despues, como red
    adicional, las formas reducidas a letras y numeros, que salvan diferencias
    de guiones y espacios.
    """
    objetivo = nombre.strip().casefold()
    reducido = _solo_alfanumerico(nombre)

    for realm in indice:
        nombres = [str(n) for n in realm.get("names") or []]
        if any(n.strip().casefold() == objetivo for n in nombres):
            oficial = realm.get("slug")
            return oficial if isinstance(oficial, str) else None

    if not reducido:
        return None

    for realm in indice:
        formas = {_solo_alfanumerico(str(realm.get("slug", "")))}
        formas.update(_solo_alfanumerico(str(n)) for n in realm.get("names") or [])
        if reducido in formas:
            oficial = realm.get("slug")
            return oficial if isinstance(oficial, str) else None
    return None


def _solo_alfanumerico(texto: str) -> str:
    return "".join(c for c in slugify_realm(texto) if c.isalnum())
