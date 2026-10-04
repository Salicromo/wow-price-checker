"""Genera los ficheros del addon a partir de config.yaml y personajes.yaml.

    py generar_vigilados.py                    # los dos ficheros
    py generar_vigilados.py --solo-personajes  # sin credenciales de Blizzard

El addon no puede leer YAML: WoW solo carga los ficheros Lua que lista el .toc.
Este script le pasa lo que el reposteo necesita en dos ficheros:

- Vigilados.lua: que objetos repostear y con que duracion postear. Se sube a
  git, porque en la Steam Deck no hay credenciales de Blizzard con las que
  resolver los ids.
- Personajes.lua: que personajes son tuyos. NO se sube: el repositorio es
  publico. Solo necesita personajes.yaml, asi que la Deck se lo genera sola.

Vuelve a ejecutarlo cada vez que cambies los objetos, personajes.yaml o
listing_hours. Un test falla si Vigilados.lua se queda atras.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from wowalerts.config import ConfigError, ItemRule, load_config
from wowalerts.items import ItemResolutionError, resolve_item_ids
from wowalerts.state import ItemIdCache

log = logging.getLogger("vigilados")

EXIT_OK = 0
EXIT_ERROR = 1

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "addon" / "WowAlertsExport" / "Vigilados.lua"

# La casa de subastas solo admite estas duraciones, y PostItem las pide por
# numero: 1 son 12 horas, 2 son 24 y 3 son 48.
DURACIONES = {12: 1, 24: 2, 48: 3}


def duracion_de(listing_hours: int) -> int:
    """El numero de duracion que entiende PostItem."""
    if listing_hours not in DURACIONES:
        raise ConfigError(
            f"'listing_hours' vale {listing_hours}, y la casa de subastas solo "
            "admite 12, 24 o 48 horas: el reposteo no sabria con que duracion "
            "postear."
        )
    return DURACIONES[listing_hours]


def _entra_en_vigilados(regla: ItemRule) -> bool:
    """Si `regla` tiene que entrar en el fichero que lee el addon.

    Lo dice `repostear` en config.yaml, que sin valor sigue a `avisar_undercut`:
    de las recetas no quieres avisos de undercut, pero si repostearlas.

    Las mascotas se quedan fuera: en la casa todas son la misma jaula.
    """
    return regla.se_repostea and not regla.es_mascota


def objetos_a_repostear(reglas: Mapping[int, ItemRule]) -> dict[int, str]:
    """{item_id: nombre} de los objetos que el addon repostea con la tecla."""
    return {
        item_id: regla.name
        for item_id, regla in sorted(reglas.items())
        if _entra_en_vigilados(regla)
    }


def _cadena_lua(texto: str) -> str:
    escapado = (
        texto.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escapado + '"'


def a_lua(objetos: Mapping[int, str], duracion: int) -> str:
    """El contenido de Vigilados.lua.

    Con la lista de personajes vacia: la rellena Personajes.lua, que el .toc
    carga justo despues. Sin ese fichero el addon sigue funcionando, solo que
    no distingue tus otras cuentas de un rival.
    """
    lineas = [
        "-- Generado por generar_vigilados.py a partir de config.yaml.",
        "-- No lo edites a mano: vuelve a ejecutar el script.",
        "",
        "WowAlertsVigilados = {",
        "    objetos = {",
    ]
    for item_id, nombre in sorted(objetos.items()):
        lineas.append(f"        [{item_id}] = {_cadena_lua(nombre)},")
    lineas += ["    },", "    personajes = {},", f"    duracion = {duracion},", "}"]
    return "\n".join(lineas) + "\n"


def personajes_a_lua(personajes: Sequence[str]) -> str:
    """El contenido de Personajes.lua."""
    lineas = [
        "-- Generado por generar_vigilados.py a partir de personajes.yaml.",
        "-- No se sube a git. No lo edites a mano: vuelve a ejecutar el script.",
        "",
        "WowAlertsVigilados.personajes = {",
    ]
    for nombre in personajes:
        lineas.append(f"    {_cadena_lua(nombre)},")
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def _escribir(salida: Path, texto: str) -> None:
    if salida.is_file() and salida.read_text(encoding="utf-8") == texto:
        log.info("%s ya estaba al dia.", salida.name)
        return
    # newline="\n": el mismo fichero byte a byte en Windows y en la Deck.
    salida.write_text(texto, encoding="utf-8", newline="\n")
    log.info("✅ Escrito %s.", salida)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(RAIZ / "config.yaml"))
    parser.add_argument("--state-dir", default=str(RAIZ / ".state"))
    parser.add_argument("--salida", default=str(DESTINO))
    parser.add_argument(
        "--solo-personajes",
        action="store_true",
        help="Escribe solo Personajes.lua, que no necesita credenciales de Blizzard.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(RAIZ / ".env")

    try:
        config = load_config(args.config)
        duracion = duracion_de(config.settings.listing_hours)
    except ConfigError as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR

    # Primero, y antes de hablar con Blizzard: es lo unico que hace falta en la
    # Deck, y no debe depender de que alli haya credenciales.
    salida = Path(args.salida)
    if config.orden_personajes:
        _escribir(salida.with_name("Personajes.lua"), personajes_a_lua(config.orden_personajes))
    else:
        log.warning(
            "Sin personajes.yaml: el reposteo no distinguira tus otras cuentas de "
            "un rival. Copia personajes.example.yaml a personajes.yaml."
        )
    if args.solo_personajes:
        return EXIT_OK

    client = BlizzardClient(
        client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
        client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )
    cache = ItemIdCache(Path(args.state_dir) / "item_ids.json")
    try:
        reglas = resolve_item_ids(client, config, cache)
    except (BlizzardAuthError, BlizzardError, ItemResolutionError) as exc:
        log.error("❌ %s", exc)
        return EXIT_ERROR
    cache.save()

    objetos = objetos_a_repostear(reglas)
    esperados = {r.name for r in config.items if _entra_en_vigilados(r)}
    faltan = esperados - set(objetos.values())
    if faltan:
        log.error(
            "❌ No se ha resuelto el id de: %s. Anade 'item_id' a mano en "
            "config.yaml para cada uno de esos objetos.",
            ", ".join(sorted(faltan)),
        )
        return EXIT_ERROR

    _escribir(salida, a_lua(objetos, duracion))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
