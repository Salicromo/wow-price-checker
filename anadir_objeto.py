"""Anade a config.yaml el objeto nuevo que pide una issue.

    py anadir_objeto.py < cuerpo.md         # el cuerpo de la issue por stdin
    py anadir_objeto.py --dry-run < x.md    # sin escribir nada

Hermano de aplicar_tope.py: aquel mueve el tope de un objeto que ya vigilas,
este anade uno que no estaba. Por stdout sale el comentario en markdown que el
workflow publica en la issue, y el codigo de salida le dice si commitear (0) o
dejarla abierta (1).

Hay dos emisores del cuerpo --la app del movil y el formulario de GitHub-- y
los dos generan el mismo markdown, asi que aqui hay un solo parser.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from wowalerts.config import Config, ConfigError, ItemRule, load_config
from wowalerts.objetos import (
    ObjetoError,
    ampliar_equipo,
    anadir_equipo,
    anadir_patron,
)
from wowalerts.topes import TopeError

EXIT_OK = 0
EXIT_ERROR = 1

# Las etiquetas de los campos, que es como GitHub titula cada bloque del cuerpo.
# Son el contrato con .github/ISSUE_TEMPLATE/objeto.yml y con la app: si cambias
# una aqui, cambiala en los tres sitios.
CAMPO_OBJETO = "Objeto"
CAMPO_TIPO = "Tipo"
CAMPO_TOPES_ILVL = "Topes por ilvl"
CAMPO_TOPE = "Tope, en oro"

# Lo que escribe GitHub cuando dejas en blanco un campo opcional.
SIN_RESPUESTA = "_No response_"

EQUIPO = "equipo"
PATRON = "patron"

# El id que lleva dentro un enlace de Wowhead, que es lo que se pega desde el
# movil: https://www.wowhead.com/es/item=258126/patron-...
_ENLACE = re.compile(r"item=(\d+)")


@dataclass(frozen=True)
class Peticion:
    # Lo escrito en el campo: un enlace de Wowhead, un id, o el nombre en ingles.
    objeto: str
    tipo: str
    # Los escalones que escribe quien anade una pieza de equipo; None en un patron.
    topes_ilvl: Mapping[int, int] | None
    tope: int | None


def _campos(cuerpo: str) -> dict[str, str]:
    """Parte el cuerpo en '### Etiqueta' -> valor.

    GitHub renderiza los formularios con la ETIQUETA del campo como encabezado,
    no con su id, asi que es la etiqueta lo que hay que buscar.
    """
    trozos = re.split(r"^###[ \t]*(.+?)[ \t]*$", cuerpo, flags=re.MULTILINE)
    return {
        trozos[i].strip(): trozos[i + 1].strip()
        for i in range(1, len(trozos) - 1, 2)
    }


def _entero(texto: str, campo: str) -> int:
    """Un entero escrito por una persona en un movil.

    Se admiten separadores de miles y un 'g' detras, porque escribir '40.000 g'
    es lo natural y rechazarlo obligaria a repetir la issue entera. Pero un
    punto o una coma que no separa tres cifras exactas es un decimal, no un
    millar: '20.5' no son doscientos cinco.
    """
    if re.search(r"[.,](?!\d{3}(?!\d))", texto.strip()):
        raise ObjetoError(f"{campo!r}: {texto!r} no es un numero entero.")
    limpio = re.sub(r"[.,\s]", "", texto)
    limpio = re.sub(r"[gG]$", "", limpio)
    if not re.fullmatch(r"\d+", limpio):
        raise ObjetoError(f"{campo!r}: {texto!r} no es un numero entero.")
    return int(limpio)


# Un escalon de la tabla: 'ilvl: tope' o 'ilvl = tope', con una vineta
# opcional delante ('-', '*' o '•'), porque el campo se suele pegar de
# una lista escrita a mano. ASCII para que un digito de otro alfabeto no pase
# por numero y reviente en int().
_ESCALON = re.compile(r"^\s*(?:[-*•]\s+)?(\d+)\s*[:=]\s*(.+?)\s*$", re.ASCII)

# Ningun ilvl real llega tan alto: por encima, casi seguro que el ilvl y el
# tope estan al reves.
_ILVL_MAXIMO = 2000


def _tabla(texto: str) -> dict[int, int]:
    """Los escalones del campo 'Topes por ilvl', uno por linea.

    Uno por linea y no separados por comas, porque la coma tambien es separador
    de miles ('20,000') y el campo se escribe a mano. Las lineas en blanco no
    cuentan.
    """
    topes: dict[int, int] = {}
    for linea in texto.splitlines():
        if not linea.strip():
            continue
        escalon = _ESCALON.match(linea)
        if escalon is None:
            raise ObjetoError(
                f"{CAMPO_TOPES_ILVL!r}: no entiendo la linea {linea.strip()!r}. "
                "Va un escalon por linea, como '368: 20000'."
            )
        ilvl = int(escalon.group(1))
        tope = _entero(escalon.group(2), CAMPO_TOPES_ILVL)
        if ilvl <= 0 or tope <= 0:
            raise ObjetoError(
                f"{CAMPO_TOPES_ILVL!r}: en {linea.strip()!r} el ilvl y el tope "
                "tienen que ser mayores que cero."
            )
        if ilvl > _ILVL_MAXIMO:
            raise ObjetoError(
                f"{CAMPO_TOPES_ILVL!r}: {ilvl} no es un ilvl posible (maximo "
                f"{_ILVL_MAXIMO}). Revisa si el ilvl y el tope estan al reves."
            )
        if ilvl in topes:
            raise ObjetoError(
                f"{CAMPO_TOPES_ILVL!r}: el ilvl {ilvl} esta repetido."
            )
        topes[ilvl] = tope
    if not topes:
        raise ObjetoError(
            f"{CAMPO_TOPES_ILVL!r} no trae ningun escalon. Pon uno por linea, "
            "como '368: 20000'."
        )
    return topes


def _relleno(campos: dict[str, str], etiqueta: str) -> str | None:
    """El valor de un campo opcional, o None si se dejo en blanco."""
    valor = campos.get(etiqueta, "").strip()
    return None if not valor or valor == SIN_RESPUESTA else valor


def _tipo(texto: str) -> str:
    limpio = texto.strip().lower()
    if limpio.startswith("equipo"):
        return EQUIPO
    # Por el principio, que el desplegable dice "Patron" con tilde o sin ella.
    if limpio.startswith("patr"):
        return PATRON
    raise ObjetoError(
        f"No entiendo el tipo {texto!r}. Tiene que ser 'Equipo (tabla por ilvl)' "
        "o 'Patron o receta (precio unico)'. Las mascotas y las monturas se "
        "siguen anadiendo a mano en config.yaml."
    )


def id_de(texto: str) -> int | None:
    """El item id que lleva dentro lo escrito, si lo lleva.

    Vale el enlace de Wowhead y el numero suelto. Cualquier otra cosa se toma
    por el nombre del objeto en ingles.
    """
    enlace = _ENLACE.search(texto)
    if enlace is not None:
        return int(enlace.group(1))
    limpio = texto.strip()
    # ASCII y no solo isdigit(): '²'.isdigit() da True pero int('²') explota.
    return int(limpio) if re.fullmatch(r"\d+", limpio, re.ASCII) else None


def parsear(cuerpo: str) -> Peticion:
    """La peticion que lleva dentro el cuerpo de una issue."""
    campos = _campos(cuerpo)

    for etiqueta in (CAMPO_OBJETO, CAMPO_TIPO):
        if etiqueta not in campos:
            raise ObjetoError(
                f"Falta el campo {etiqueta!r} en la issue. Usa la plantilla de "
                "'Anadir un objeto' en vez de una issue en blanco."
            )

    objeto = _relleno(campos, CAMPO_OBJETO)
    if objeto is None:
        raise ObjetoError(f"El campo {CAMPO_OBJETO!r} viene vacio.")

    tipo = _tipo(campos[CAMPO_TIPO])
    topes_ilvl = _relleno(campos, CAMPO_TOPES_ILVL)
    tope = _relleno(campos, CAMPO_TOPE)

    if tipo == EQUIPO:
        if topes_ilvl is None:
            raise ObjetoError(
                "Una pieza de equipo lleva tabla por ilvl: rellena "
                f"{CAMPO_TOPES_ILVL!r} con un escalon por linea, como "
                "'368: 20000'."
            )
        return Peticion(objeto, EQUIPO, _tabla(topes_ilvl), None)

    if tope is None:
        raise ObjetoError(
            f"Un patron lleva precio unico: rellena {CAMPO_TOPE!r}."
        )
    return Peticion(objeto, PATRON, None, _entero(tope, CAMPO_TOPE))


def resolver(client: BlizzardClient, peticion: Peticion) -> tuple[str, int]:
    """El nombre en ingles y el id del objeto que pide la issue.

    El movil no tiene credenciales de Blizzard: por eso el campo viaja como
    texto y la traduccion a id se hace aqui, en Actions, que es donde estan los
    secretos.
    """
    item_id = id_de(peticion.objeto)
    if item_id is not None:
        nombre = client.item_name(item_id)
        if nombre is None:
            # item_name() devuelve None tanto si el id no existe como si
            # Blizzard no ha respondido (ver su docstring en blizzard.py), asi
            # que no se puede culpar solo al enlace.
            raise ObjetoError(
                f"Blizzard no conoce el id {item_id}, o no ha respondido. "
                "Comprueba el enlace: el numero es el que va detras de "
                "'item=' en Wowhead. Si es correcto, abre otra issue para "
                "reintentarlo."
            )
        return nombre, item_id

    nombre = peticion.objeto.strip()
    item_id = client.search_item_id(nombre)
    if item_id is None:
        raise ObjetoError(
            f"Blizzard no encuentra ningun objeto que se llame {nombre!r}. Tiene "
            "que ser el nombre en ingles, igual que en el juego; si el objeto es "
            "recien salido, pega mejor su enlace de Wowhead."
        )
    # El nombre canonico de Blizzard, no el que haya tecleado quien escribe la
    # issue: si no se puede consultar (sin red, o item_name falla), se queda
    # con el nombre buscado.
    nombre = client.item_name(item_id) or nombre
    return nombre, item_id


def vigilado(config: Config, nombre: str, item_id: int) -> ItemRule | None:
    """La regla que ya vigila ese objeto, por nombre o por id, o None."""
    for regla in config.items:
        if regla.name.strip().lower() == nombre.strip().lower():
            return regla
        if regla.item_id is not None and regla.item_id == item_id:
            return regla
    return None


def comprobar_nuevo(config: Config, nombre: str, item_id: int) -> None:
    """Que el objeto no estuviera vigilado ya, ni por nombre ni por id."""
    for regla in config.items:
        if regla.name.strip().lower() == nombre.strip().lower():
            raise ObjetoError(
                f"{regla.name!r} ya esta vigilado. Para cambiarle el tope usa el "
                "boton de la app, o la plantilla 'Ajustar un tope'."
            )
        if regla.item_id is not None and regla.item_id == item_id:
            raise ObjetoError(
                f"El objeto {item_id} ya esta vigilado, con el nombre "
                f"{regla.name!r}. Para cambiarle el tope usa el boton de la app."
            )


def _cargar(texto: str) -> Config:
    """load_config solo lee de disco, asi que el texto pasa por un temporal."""
    ruta = Path(tempfile.mkdtemp()) / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return load_config(ruta)


def verificar(
    viejo: str, nuevo: str, nombre: str, item_id: int, peticion: Peticion
) -> ItemRule:
    """La red de seguridad que hace seguro editar YAML por texto.

    Si la edicion ha roto el fichero, no ha dejado el objeto pedido, o ha
    tocado cualquier otro, se aborta antes de commitear nada.

    Devuelve la regla nueva, que es lo que el comentario de la issue ensena.
    """
    try:
        antes = {regla.name: regla for regla in _cargar(viejo).items}
        despues = {regla.name: regla for regla in _cargar(nuevo).items}
    except ConfigError as fallo:
        raise ObjetoError(
            f"El config.yaml resultante no es valido, asi que no lo toco: {fallo}"
        ) from fallo

    regla = despues.get(nombre)
    if regla is None:
        raise ObjetoError(f"{nombre!r} no ha quedado en config.yaml. No anado nada.")
    if regla.item_id != item_id:
        raise ObjetoError(
            f"{nombre!r} no ha quedado con el id {item_id}. No anado nada."
        )

    if peticion.tipo == EQUIPO:
        if (
            regla.max_price is not None
            or dict(regla.max_price_by_ilvl) != dict(peticion.topes_ilvl)
        ):
            raise ObjetoError(
                f"Los topes de {nombre!r} no han quedado como los pedidos. "
                "No anado nada."
            )
    elif (
        regla.max_price != peticion.tope
        or regla.avisar_undercut
        or not regla.se_repostea
    ):
        raise ObjetoError(
            f"{nombre!r} no ha quedado con el precio y las banderas pedidos. "
            "No anado nada."
        )

    extra = (set(despues) - set(antes)) - {nombre}
    eliminados = set(antes) - set(despues)
    if extra or eliminados:
        raise ObjetoError(
            "La edicion ha anadido o quitado objetos ademas del nuevo ("
            + ", ".join(sorted(extra | eliminados))
            + "), asi que no la aplico."
        )

    movidos = [n for n in antes if antes[n] != despues.get(n)]
    if movidos:
        raise ObjetoError(
            "La edicion ha tocado otros objetos ademas del nuevo ("
            + ", ".join(sorted(movidos))
            + "), asi que no la aplico."
        )

    return regla


def _oro(cantidad: int) -> str:
    """40000 -> '40.000' (separador de miles a la espanola)."""
    return f"{cantidad:,}".replace(",", ".")


def _ok(nombre: str, item_id: int, regla: ItemRule) -> str:
    if regla.max_price is not None:
        topes = f"{_oro(regla.max_price)} de oro"
    else:
        topes = "\n".join(
            f"ilvl {ilvl}: {_oro(tope)}"
            for ilvl, tope in sorted(regla.max_price_by_ilvl.items())
        )
    return (
        "✅ **Objeto anadido.**\n\n"
        "```\n"
        f"{nombre}  (id {item_id})\n"
        f"{topes}\n"
        "```\n\n"
        "Empieza a vigilarse en la pasada siguiente, como mucho dentro de una "
        "hora, y a partir de ahi sale en la app."
    )


def verificar_ampliacion(
    viejo: str, nuevo: str, nombre: str, esperada: dict[int, int]
) -> None:
    """La misma red que verificar(), para una tabla ampliada.

    Solo puede haber cambiado la tabla de ese objeto, y tiene que haber quedado
    exactamente como la esperada: la vieja mas los escalones nuevos.
    """
    try:
        antes = {regla.name: regla for regla in _cargar(viejo).items}
        despues = {regla.name: regla for regla in _cargar(nuevo).items}
    except ConfigError as fallo:
        raise ObjetoError(
            f"El config.yaml resultante no es valido, asi que no lo toco: {fallo}"
        ) from fallo

    if set(antes) != set(despues):
        raise ObjetoError(
            "La edicion ha anadido o quitado objetos, asi que no la aplico."
        )
    if despues[nombre] != replace(antes[nombre], max_price_by_ilvl=esperada):
        raise ObjetoError(
            f"La tabla de {nombre!r} no ha quedado como la pedida. No toco nada."
        )
    movidos = [n for n in antes if n != nombre and antes[n] != despues[n]]
    if movidos:
        raise ObjetoError(
            "La edicion ha tocado otros objetos ("
            + ", ".join(sorted(movidos))
            + "), asi que no la aplico."
        )


def _ok_ampliado(
    nombre: str, anadidos: dict[int, int], ya_estaban: dict[int, int]
) -> str:
    escalones = "\n".join(
        f"ilvl {ilvl}: {_oro(tope)}" for ilvl, tope in sorted(anadidos.items())
    )
    texto = (
        f"✅ **Tabla de {nombre} ampliada.**\n\n"
        f"```\n{escalones}\n```\n\n"
        "Empieza a vigilarse en la pasada siguiente, como mucho dentro de una "
        "hora."
    )
    if ya_estaban:
        texto += (
            "\n\nEstos ilvl ya estaban y **no los he tocado**: "
            + ", ".join(
                f"{ilvl} ({_oro(tope)})" for ilvl, tope in sorted(ya_estaban.items())
            )
            + ". Para cambiarles el tope usa 'Ajustar un tope'."
        )
    return texto


def _error(fallo: Exception) -> str:
    return (
        "❌ **No he anadido nada.**\n\n"
        f"{fallo}\n\n"
        "Corrige y abre otra issue; esta se queda abierta para que puedas verla."
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anade a config.yaml el objeto que pide una issue.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No escribe el fichero: solo dice que haria.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    ruta = Path(args.config)
    load_dotenv(Path(__file__).resolve().parent / ".env")

    try:
        peticion = parsear(sys.stdin.read())
        texto = ruta.read_text(encoding="utf-8")
        config = load_config(ruta)
        client = BlizzardClient(
            client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
            client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
            region=config.region,
            locale=config.locale,
            timeout=config.settings.request_timeout,
        )
        # Fuerza la autenticacion ya: si las credenciales fallan, que salte
        # aqui como BlizzardAuthError y no se confunda mas tarde con un id
        # que Blizzard "no conoce" (item_name() traga cualquier BlizzardError
        # y devuelve None igual para las dos cosas).
        _ = client.token
        nombre, item_id = resolver(client, peticion)
        existente = vigilado(config, nombre, item_id)
        if (
            existente is not None
            and peticion.tipo == EQUIPO
            and not existente.sin_ilvl
            and not existente.es_mascota
        ):
            # Ya lo vigilas y es equipo: lo normal en una temporada nueva, la
            # misma pieza a ilvl que su tabla no tiene. Se amplia la tabla.
            nuevo, anadidos, ya_estaban = ampliar_equipo(
                texto, existente.name, peticion.topes_ilvl
            )
            verificar_ampliacion(
                texto, nuevo, existente.name,
                {**existente.max_price_by_ilvl, **anadidos},
            )
            comentario = _ok_ampliado(existente.name, anadidos, ya_estaban)
        else:
            comprobar_nuevo(config, nombre, item_id)
            if peticion.tipo == EQUIPO:
                nuevo = anadir_equipo(texto, nombre, item_id, peticion.topes_ilvl)
            else:
                nuevo = anadir_patron(texto, nombre, item_id, peticion.tope)
            regla = verificar(texto, nuevo, nombre, item_id, peticion)
            comentario = _ok(nombre, item_id, regla)
    except (
        ObjetoError,
        TopeError,
        ConfigError,
        BlizzardAuthError,
        BlizzardError,
        OSError,
    ) as fallo:
        print(_error(fallo))
        return EXIT_ERROR
    except Exception as fallo:
        # Ultimo recurso: el workflow publica esta salida como comentario de
        # la issue, asi que un fallo sin capturar la dejaria sin comentario y
        # sin ninguna pista de que ha pasado.
        print(_error(fallo))
        return EXIT_ERROR

    if not args.dry_run:
        ruta.write_text(nuevo, encoding="utf-8")

    print(comentario)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
