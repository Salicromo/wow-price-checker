"""El resumen de "te han adelantado" que lee la ventana del addon.

El vigilante lo escribe en cada pasada (`escribir`) y el workflow lo sube a la
rama 'datos' del repositorio privado. sync_subastas.py lo trae y lo convierte
en Adelantadas.lua (`a_lua`), porque el addon no tiene red y solo lee ficheros
Lua al cargar la interfaz.

En ese mismo fichero van los apuntes de lo repuesto en cada cuenta de WoW
(`vistas_de`, `juntar_vistas`): WoW guarda los datos de los addons por cuenta,
y sin esto lo repuesto con una no saldria tachado en la otra.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .misubastas import MisSubastasError, leer_cadena_lua

VERSION = 1

VISTAS_RE = re.compile(r'\["adelantadasJSON"\]\s*=\s*"')
CAMPOS_VISTA = ("en", "quedan", "pendientes")


def escribir(
    path: str | Path, cuentas: Sequence[Mapping[str, Any]], pasada: int, volcado: int
) -> bool:
    """Escribe el resumen. True solo si ha cambiado algo.

    En ASCII: al otro lado se lee con `git show`, que en Windows decodifica con
    la codificacion del sistema y romperia un nombre con tilde.
    """
    path = Path(path)
    contenido = json.dumps(
        {
            "version": VERSION,
            "pasada": pasada,
            "volcado": volcado,
            "total": sum(p["n"] for c in cuentas for p in c["personajes"]),
            "cuentas": list(cuentas),
        },
        ensure_ascii=True,
        sort_keys=True,
        indent=1,
    )
    if path.is_file() and path.read_text(encoding="utf-8") == contenido:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8", newline="\n")
    return True


def _entero(valor: Any, que: str) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ValueError(f"{que} deberia ser un numero entero y es {valor!r}")
    return valor


def _texto(valor: Any, que: str) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"{que} deberia ser un texto y es {valor!r}")
    return valor


def _cadena_lua(texto: str) -> str:
    escapado = (
        texto.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escapado + '"'


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def vistas_de(texto: str) -> dict[str, dict[str, int]]:
    """Los apuntes que guarda el addon de una cuenta: "Reino-Nombre" -> apunte.

    Se salta lo que no tenga la forma: esto sale de un fichero que escribe WoW,
    y un apunte raro no puede dejar sin los de los demas personajes.
    """
    match = VISTAS_RE.search(texto)
    if not match:
        return {}
    try:
        datos = json.loads(leer_cadena_lua(texto, match.end()))
    except (MisSubastasError, json.JSONDecodeError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {
        clave: {campo: apunte[campo] for campo in CAMPOS_VISTA}
        for clave, apunte in datos.items()
        if isinstance(apunte, dict) and all(_es_entero(apunte.get(c)) for c in CAMPOS_VISTA)
    }


def juntar_vistas(
    de_cada_cuenta: Iterable[Mapping[str, Mapping[str, int]]],
) -> dict[str, dict[str, int]]:
    """Los apuntes de todas las cuentas; de cada personaje, el mas reciente."""
    juntas: dict[str, dict[str, int]] = {}
    for vistas in de_cada_cuenta:
        for clave, apunte in vistas.items():
            if clave not in juntas or apunte["en"] > juntas[clave]["en"]:
                juntas[clave] = dict(apunte)
    return juntas


def a_lua(
    datos: Mapping[str, Any], vistas: Mapping[str, Mapping[str, int]] | None = None
) -> str:
    """El contenido de Adelantadas.lua. ValueError si `datos` no tiene la forma.

    `vistas` son los apuntes de todas las cuentas (ver `juntar_vistas`).
    """
    if not isinstance(datos, Mapping):
        raise ValueError("el resumen deberia ser un objeto JSON")
    cuentas = datos.get("cuentas")
    if not isinstance(cuentas, list):
        raise ValueError("al resumen le falta la lista de cuentas")

    lineas = [
        "-- Generado por sync_subastas.py a partir del ultimo aviso de undercut.",
        "-- No se sube a git. No lo edites a mano: se reescribe solo.",
        "",
        "WowAlertsAdelantadas = {",
        f"    pasada = {_entero(datos.get('pasada'), 'pasada')},",
        f"    volcado = {_entero(datos.get('volcado'), 'volcado')},",
        f"    total = {_entero(datos.get('total'), 'total')},",
        "    cuentas = {",
    ]
    for grupo in cuentas:
        if not isinstance(grupo, Mapping) or not isinstance(grupo.get("personajes"), list):
            raise ValueError(f"cuenta mal formada: {grupo!r}")
        cuenta = grupo.get("cuenta")
        cuenta_lua = "nil" if cuenta is None else str(_entero(cuenta, "cuenta"))
        lineas.append(f"        {{ cuenta = {cuenta_lua}, personajes = {{")
        for p in grupo["personajes"]:
            if not isinstance(p, Mapping):
                raise ValueError(f"personaje mal formado: {p!r}")
            lineas.append(
                "            { "
                f"nombre = {_cadena_lua(_texto(p.get('nombre'), 'nombre'))}, "
                f"reino = {_cadena_lua(_texto(p.get('reino'), 'reino'))}, "
                f"n = {_entero(p.get('n'), 'n')}, "
                f"caras = {_entero(p.get('caras'), 'caras')} }},"
            )
        lineas.append("        } },")
    lineas += ["    },", "    vistas = {"]
    for clave, apunte in sorted((vistas or {}).items()):
        lineas.append(
            f"        [{_cadena_lua(clave)}] = {{ "
            f"en = {apunte['en']}, quedan = {apunte['quedan']}, "
            f"pendientes = {apunte['pendientes']} }},"
        )
    lineas += ["    },", "}"]
    return "\n".join(lineas) + "\n"
