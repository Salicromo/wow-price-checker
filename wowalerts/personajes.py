"""Que personajes tienes y en que reino esta cada uno.

No hace falta addon para esto: WoW crea una carpeta por personaje dentro de la
de su reino, dentro de la de su cuenta. Leer esa estructura da la lista entera,
incluidos los personajes que no tienen ninguna subasta puesta.

Sirve para que un chollo diga con quien hay que entrar a comprarlo, y para
avisar cuando el chollo esta en un reino donde no tienes a nadie.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, Sequence

from .misubastas import cuenta_de_ruta, slugify_realm

log = logging.getLogger(__name__)

ROSTER_VERSION = 1


@dataclass(frozen=True)
class Personaje:
    """Un personaje tuyo, con el reino y la cuenta en la que vive."""

    name: str
    realm: str
    realm_slug: str
    account: int | None = None

    @property
    def etiqueta(self) -> str:
        """'Kbardan · WoW 2', o solo el nombre si no se sabe la cuenta."""
        if self.account is None:
            return self.name
        return f"{self.name} · WoW {self.account}"


def leer_personajes(wow_root: str | Path) -> list[Personaje]:
    """Todos tus personajes, sacados de la estructura de carpetas de WTF."""
    personajes: list[Personaje] = []

    for carpeta in Path(wow_root).glob("WTF/Account/*/*/*"):
        if not carpeta.is_dir():
            continue
        # Account/<cuenta>/SavedVariables/ no es un reino.
        if carpeta.parent.name == "SavedVariables":
            continue

        realm = carpeta.parent.name
        personajes.append(
            Personaje(
                name=carpeta.name,
                realm=realm,
                realm_slug=slugify_realm(realm),
                account=cuenta_de_ruta(carpeta),
            )
        )

    personajes.sort(key=lambda p: (p.account or 0, p.realm, p.name))
    log.info("%s personaje(s) tuyos en %s reino(s).", len(personajes), len({p.realm_slug for p in personajes}))
    return personajes


def escribir_personajes(path: str | Path, personajes: Sequence[Personaje]) -> bool:
    """Escribe mis_personajes.json. True solo si el contenido ha cambiado."""
    path = Path(path)
    contenido = json.dumps(
        {
            "version": ROSTER_VERSION,
            "characters": [
                {
                    "name": p.name,
                    "realm": p.realm,
                    "account": p.account,
                }
                for p in personajes
            ],
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )

    anterior = path.read_text(encoding="utf-8") if path.is_file() else None
    if anterior == contenido:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")
    return True


def orden_de_personajes(
    roster: Iterable[Personaje], preferido: Sequence[str] = ()
) -> dict[tuple[str, str], int]:
    """En que orden leer los avisos: (nombre, reino) -> posicion.

    Manda `preferido`, que es la lista de config.yaml y refleja el orden en que
    tienes los personajes en el selector. Eso no se puede deducir de ningun
    fichero: si lo reordenas arrastrando, ese orden vive en el servidor.

    Los que no esten en la lista van detras, por cuenta y luego como vengan del
    roster (que va por reino). Sin esto los avisos salian en el orden en que
    tocara descargar los reinos, que cambia de una pasada a otra.
    """
    posicion = {nombre: i for i, nombre in enumerate(preferido)}
    resto = sorted(
        (p for p in roster if p.name not in posicion),
        key=lambda p: (p.account if p.account is not None else 99,),
    )

    orden: dict[tuple[str, str], int] = {}
    for p in roster:
        if p.name in posicion:
            orden[(p.name, p.realm)] = posicion[p.name]
    for i, p in enumerate(resto):
        orden[(p.name, p.realm)] = len(posicion) + i
    return orden


def leer_rosters(origen: str | Path) -> list[Personaje]:
    """Une la lista de personajes de todas tus maquinas.

    En la Steam Deck solo estan las carpetas de los personajes con los que has
    jugado alli, asi que ninguna maquina tiene la lista completa: hay que
    juntarlas. Un personaje que aparezca en las dos se cuenta una vez.

    Acepta tambien un fichero suelto, que es como estaba antes de haber dos
    maquinas.
    """
    origen = Path(origen)
    if origen.is_file():
        return leer_roster(origen)
    if not origen.is_dir():
        log.debug("No existe %s: no se que personajes tienes.", origen)
        return []

    unicos: dict[tuple[str, str], Personaje] = {}
    for fichero in sorted(origen.glob("*.json")):
        for personaje in leer_roster(fichero):
            unicos.setdefault((personaje.realm, personaje.name), personaje)

    return sorted(unicos.values(), key=lambda p: (p.account or 0, p.realm, p.name))


def leer_roster(path: str | Path) -> list[Personaje]:
    """Lee mis_personajes.json. Un fichero que no existe son cero personajes."""
    path = Path(path)
    if not path.is_file():
        log.debug("No existe %s: no se que personajes tienes.", path)
        return []

    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s ilegible (%s); sigo sin la lista de personajes.", path, exc)
        return []

    personajes: list[Personaje] = []
    for cruda in datos.get("characters") or []:
        nombre = cruda.get("name")
        realm = cruda.get("realm")
        if not isinstance(nombre, str) or not isinstance(realm, str):
            continue
        cuenta = cruda.get("account")
        personajes.append(
            Personaje(
                name=nombre,
                realm=realm,
                realm_slug=slugify_realm(realm),
                account=cuenta if isinstance(cuenta, int) else None,
            )
        )
    return personajes


def por_nombre_de_reino(
    personajes: Iterable[Personaje],
) -> dict[str, list[Personaje]]:
    """Indexa tus personajes por el nombre de su reino, para buscarlos rapido."""
    indice: dict[str, list[Personaje]] = {}
    for personaje in personajes:
        indice.setdefault(personaje.realm.strip().casefold(), []).append(personaje)
    return indice


def quien_puede_comprar(
    indice: dict[str, list[Personaje]], nombre_conectado: str, tope: int = 2
) -> str:
    """Con quien entrar a por un chollo que esta en ese connected realm.

    `nombre_conectado` es lo que devuelve la API para un connected realm, que
    ya trae dentro todos los reinos que comparten casa de subastas separados
    por barras: 'Dun Modr / Sanguino'. Aprovecharlo evita tener que resolver
    los reinos de tus 152 personajes contra la API, que es lo mismo pero
    pagando noventa peticiones.
    """
    candidatos: list[Personaje] = []
    vistos: set[tuple[str, str]] = set()

    for parte in nombre_conectado.split("/"):
        for personaje in indice.get(parte.strip().casefold(), []):
            clave = (personaje.name, personaje.realm)
            if clave not in vistos:
                vistos.add(clave)
                candidatos.append(personaje)

    if not candidatos:
        return "no tienes personaje en ese reino"

    nombres = [p.etiqueta for p in candidatos[:tope]]
    sobran = len(candidatos) - len(nombres)
    if sobran:
        nombres.append(f"y {sobran} mas")
    return nombres[0] if len(nombres) == 1 else "\n".join(nombres)
