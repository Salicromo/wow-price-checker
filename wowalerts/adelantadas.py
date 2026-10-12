"""El resumen de "te han adelantado" que lee la ventana del addon.

El vigilante lo escribe en cada pasada (`escribir`) y el workflow lo sube a la
rama 'datos' del repositorio privado. sync_subastas.py lo trae y lo convierte
en Adelantadas.lua (`a_lua`), porque el addon no tiene red y solo lee ficheros
Lua al cargar la interfaz.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = 1


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


def a_lua(datos: Mapping[str, Any]) -> str:
    """El contenido de Adelantadas.lua. ValueError si `datos` no tiene la forma."""
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
    lineas += ["    },", "}"]
    return "\n".join(lineas) + "\n"
