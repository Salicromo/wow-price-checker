"""El banco de hermandad, compartido entre tus cuentas de WoW.

WoW guarda los datos de los addons por cuenta (WTF/Account/<n>), y desde el
juego una cuenta no puede leer los de otra: sin esto habria que abrir el banco
con un personaje de cada cuenta. El addon deja lo que sabe del banco en
bancoJSON; aqui se busca lo mas nuevo de cada hermandad y se deja en
bancoDeOtraCuenta a las cuentas que lo tienen mas viejo. El addon lo recoge al
entrar y lo borra, asi que WoW nunca lo vuelve a escribir.

El ilvl de cada hueco lo apunta la cuenta que mete el objeto, y otra que abra
el banco despues tiene un recuento mas nuevo pero no lo sabe. Por eso los ilvl
no van con lo mas nuevo: se juntan los de todas, hueco a hueco, quedandose con
lo apuntado mas tarde, y se dejan a las cuentas a las que les falte algo.

Si la cuenta a la que se le deja esta jugando, WoW pisa el fichero al salir y
se pierde; pero ese guardado vuelve a disparar la sincronizacion y se deja otra
vez.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from wowalerts.misubastas import MisSubastasError, leer_cadena_lua

BANCO_RE = re.compile(r'\["bancoJSON"\]\s*=\s*"')
# Se escribe siempre en una sola linea, y el addon lo borra al leerlo antes de
# que WoW pueda reescribirlo a su manera: con esto basta para encontrarlo.
PENDIENTE_RE = re.compile(r'^\["bancoDeOtraCuenta"\] = .*\r?\n', re.MULTILINE)
CABECERA_RE = re.compile(r"^WowAlertsExportDB = \{(\r?\n)", re.MULTILINE)


def banco_de(texto: str) -> dict[str, dict]:
    """Lo que el addon de esa cuenta sabe del banco: clave -> {en, copias, ilvls}."""
    match = BANCO_RE.search(texto)
    if not match:
        return {}
    try:
        datos = json.loads(leer_cadena_lua(texto, match.end()))
    except (MisSubastasError, json.JSONDecodeError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {
        clave: b
        for clave, b in datos.items()
        if isinstance(b, dict) and isinstance(b.get("en"), (int, float))
    }


def _lua(valor: Any) -> str:
    """Un valor de JSON escrito como Lua. Una lista vacia es una tabla vacia."""
    if isinstance(valor, dict):
        partes = (f"[{_lua(k)}] = {_lua(v)}" for k, v in sorted(valor.items()))
        return "{" + ", ".join(partes) + "}"
    if isinstance(valor, list):
        return "{" + ", ".join(_lua(v) for v in valor) + "}"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(int(valor)) if float(valor).is_integer() else repr(valor)
    cadena = str(valor)
    for de, a in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\r", "\\r")):
        cadena = cadena.replace(de, a)
    return f'"{cadena}"'


def con_pendiente(texto: str, pendiente: dict[str, dict]) -> str:
    """El fichero con `pendiente` como bancoDeOtraCuenta, en lugar del que hubiera."""
    texto = PENDIENTE_RE.sub("", texto)
    if not pendiente:
        return texto
    match = CABECERA_RE.search(texto)
    if not match:
        return texto
    linea = f'["bancoDeOtraCuenta"] = {_lua(pendiente)},{match.group(1)}'
    return texto[: match.end()] + linea + texto[match.end() :]


def _ilvls(b: dict) -> dict[str, dict]:
    """Los ilvl apuntados. Sin ninguno, el addon los escribe como lista vacia."""
    ilvls = b.get("ilvls")
    return ilvls if isinstance(ilvls, dict) else {}


def _juntar_ilvls(bancos: Iterable[dict]) -> dict[str, dict]:
    """Los ilvl de todas las cuentas: en cada hueco, lo apuntado mas tarde."""
    juntos: dict[str, dict] = {}
    for b in bancos:
        for hueco, a in _ilvls(b).items():
            if isinstance(a, dict) and (
                hueco not in juntos or a.get("en", 0) > juntos[hueco].get("en", 0)
            ):
                juntos[hueco] = a
    return juntos


def compartir_banco(ficheros: Iterable[Path]) -> list[Path]:
    """Deja en cada cuenta lo mas nuevo de las demas. Devuelve las que ha tocado."""
    textos: dict[Path, str] = {}
    for fichero in ficheros:
        try:
            # newline="" para no cambiar los saltos de linea al reescribirlo.
            with open(fichero, encoding="utf-8", newline="") as f:
                textos[fichero] = f.read()
        except (OSError, UnicodeDecodeError):
            continue

    bancos = {fichero: banco_de(texto) for fichero, texto in textos.items()}
    mas_nuevo: dict[str, dict] = {}
    for banco in bancos.values():
        for clave, b in banco.items():
            if clave not in mas_nuevo or b["en"] > mas_nuevo[clave]["en"]:
                mas_nuevo[clave] = b
    mas_nuevo = {
        clave: {
            **b,
            "ilvls": _juntar_ilvls(banco[clave] for banco in bancos.values() if clave in banco),
        }
        for clave, b in mas_nuevo.items()
    }

    tocados = []
    for fichero, texto in textos.items():
        propio = bancos[fichero]
        pendiente = {
            clave: b
            for clave, b in mas_nuevo.items()
            if clave not in propio
            or propio[clave]["en"] < b["en"]
            or _ilvls(propio[clave]) != b["ilvls"]
        }
        nuevo = con_pendiente(texto, pendiente)
        if nuevo != texto:
            with open(fichero, "w", encoding="utf-8", newline="") as f:
                f.write(nuevo)
            tocados.append(fichero)
    return tocados
