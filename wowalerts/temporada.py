"""Que una temporada nueva no deje la vigilancia a ciegas.

Cuando sale temporada, Blizzard estrena bonus ids y el ilvl de cada subasta
deja de estar en `bonus_ilvl_map`. Aqui estan las dos piezas que lo cubren sin
que nadie tenga que editar config.yaml a mano:

1. `observar` apunta, en cada pasada, que listas de bonus de tus objetos no
   tienen ilvl conocido, y que ilvl conocidos quedan por encima de la tabla de
   su objeto (la pieza de siempre, a ilvl de temporada nueva).
2. `resolver_bonus` pregunta a Wowhead que ilvl da cada bonus desconocido. Es
   la misma fuente contra la que se comprobo la tabla a mano, y solo se da por
   buena una respuesta que cuadra tres veces: el bonus solo, el bonus en otro
   objeto, y la lista completa de la subasta.

Lo que no se puede confirmar no se escribe: se avisa, y mientras tanto los
chollos siguen saliendo como "ilvl sin confirmar".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import requests

from .config import ItemRule
from .ilvl import MIN_PLAUSIBLE_ILVL, resolve_ilvl

WOWHEAD_TOOLTIP = "https://nether.wowhead.com/tooltip/item/{item_id}"

# Tope de consultas a Wowhead por pasada. En una temporada nueva salen unas
# decenas de bonus; si hubiera mas, los que falten se miran en la pasada
# siguiente, una hora despues.
MAX_CONSULTAS = 80

_ILVL_TOOLTIP = re.compile(r"<!--ilvl-->(\d+)")


class WowheadError(Exception):
    """Wowhead no ha respondido o ha respondido algo que no se entiende."""


@dataclass
class Observado:
    """Lo que una pasada ha visto de tus objetos y no encaja en config.yaml."""

    # item_id -> listas de bonus (ordenadas) sin ningun bonus del mapa.
    sin_ilvl: dict[int, set[tuple[int, ...]]] = field(default_factory=dict)
    # (item_id, ilvl) -> precio mas barato visto, en cobre, de un ilvl que
    # queda por encima del escalon mas alto de la tabla del objeto.
    fuera_de_tabla: dict[tuple[int, int], int] = field(default_factory=dict)
    # item_id -> nombre, para poder contarlo.
    nombres: dict[int, str] = field(default_factory=dict)

    def juntar(self, otro: "Observado") -> None:
        for item_id, listas in otro.sin_ilvl.items():
            self.sin_ilvl.setdefault(item_id, set()).update(listas)
        for clave, precio in otro.fuera_de_tabla.items():
            actual = self.fuera_de_tabla.get(clave)
            if actual is None or precio < actual:
                self.fuera_de_tabla[clave] = precio
        self.nombres.update(otro.nombres)

    def vacio(self) -> bool:
        return not self.sin_ilvl and not self.fuera_de_tabla

    def a_json(self) -> dict:
        return {
            "sin_ilvl": {
                str(item_id): sorted(list(lista) for lista in listas)
                for item_id, listas in self.sin_ilvl.items()
            },
            "fuera_de_tabla": [
                [item_id, ilvl, precio]
                for (item_id, ilvl), precio in sorted(self.fuera_de_tabla.items())
            ],
            "nombres": {str(k): v for k, v in self.nombres.items()},
        }

    @classmethod
    def desde_json(cls, datos: Mapping) -> "Observado":
        return cls(
            sin_ilvl={
                int(item_id): {tuple(int(b) for b in lista) for lista in listas}
                for item_id, listas in (datos.get("sin_ilvl") or {}).items()
            },
            fuera_de_tabla={
                (int(item_id), int(ilvl)): int(precio)
                for item_id, ilvl, precio in datos.get("fuera_de_tabla") or []
            },
            nombres={int(k): str(v) for k, v in (datos.get("nombres") or {}).items()},
        )

    def guardar(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(self.a_json(), indent=2), encoding="utf-8")

    @classmethod
    def leer(cls, ruta: Path) -> "Observado | None":
        if not ruta.is_file():
            return None
        return cls.desde_json(json.loads(ruta.read_text(encoding="utf-8")))


def _es_equipo(regla: ItemRule) -> bool:
    return not regla.sin_ilvl and not regla.es_mascota and bool(regla.max_price_by_ilvl)


def observar(
    auctions: Iterable[Mapping],
    rules_by_item_id: Mapping[int, ItemRule],
    bonus_ilvl_map: Mapping[int, int],
) -> Observado:
    """Lo que no encaja de las subastas de un reino. Pura, sin red."""
    observado = Observado()
    for auction in auctions:
        item = auction.get("item") or {}
        item_id = item.get("id")
        if not isinstance(item_id, int) or item.get("pet_species_id") is not None:
            continue
        regla = rules_by_item_id.get(item_id)
        if regla is None or not _es_equipo(regla):
            continue

        bonus = tuple(
            sorted(b for b in item.get("bonus_lists") or [] if isinstance(b, int))
        )
        if not any(b in bonus_ilvl_map for b in bonus):
            # Sin bonus no hay nada que preguntar: es la pieza a su ilvl base.
            if bonus:
                observado.sin_ilvl.setdefault(item_id, set()).add(bonus)
                observado.nombres[item_id] = regla.name
            continue

        ilvl = resolve_ilvl(item, bonus_ilvl_map).value
        precio = auction.get("buyout")
        if (
            ilvl is None
            or ilvl <= max(regla.max_price_by_ilvl)
            or not isinstance(precio, int)
            or precio <= 0
        ):
            continue
        clave = (item_id, ilvl)
        if clave not in observado.fuera_de_tabla or precio < observado.fuera_de_tabla[clave]:
            observado.fuera_de_tabla[clave] = precio
        observado.nombres[item_id] = regla.name
    return observado


def ilvl_en_wowhead(
    item_id: int,
    bonus: Sequence[int] = (),
    session: requests.Session | None = None,
    timeout: int = 15,
) -> int | None:
    """El ilvl que ensena Wowhead para ese objeto con esos bonus.

    None si Wowhead no conoce el objeto o su ficha no trae ilvl. Cualquier
    fallo de red es WowheadError: eso no dice nada del bonus, y no se puede
    confundir con "este bonus no cambia el ilvl".
    """
    params = {"bonus": ":".join(str(b) for b in bonus)} if bonus else None
    try:
        respuesta = (session or requests).get(
            WOWHEAD_TOOLTIP.format(item_id=item_id),
            params=params,
            timeout=timeout,
            headers={"User-Agent": "wow-price-checker"},
        )
    except requests.RequestException as fallo:
        raise WowheadError(f"Wowhead no responde: {fallo}") from fallo
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        raise WowheadError(f"Wowhead responde {respuesta.status_code}.")
    try:
        tooltip = respuesta.json().get("tooltip") or ""
    except ValueError as fallo:
        raise WowheadError("Wowhead responde algo que no es JSON.") from fallo
    encontrado = _ILVL_TOOLTIP.search(tooltip)
    return int(encontrado.group(1)) if encontrado else None


@dataclass
class Resolucion:
    # bonus id -> ilvl, confirmados las tres veces.
    confirmados: dict[int, int] = field(default_factory=dict)
    # Listas de bonus que siguen sin ilvl despues de esto, por objeto.
    sin_resolver: dict[int, set[tuple[int, ...]]] = field(default_factory=dict)
    # Lo que ha impedido decidir, para contarlo en el aviso.
    motivos: list[str] = field(default_factory=list)


Consulta = Callable[[int, Sequence[int]], "int | None"]


def resolver_bonus(
    observado: Observado,
    bonus_ilvl_map: Mapping[int, int],
    consultar: Consulta,
    max_consultas: int = MAX_CONSULTAS,
) -> Resolucion:
    """Pregunta a Wowhead por los bonus que no conocemos.

    Un bonus se da por bueno si:
      - solo, cambia el ilvl base del objeto a algo creible;
      - en otro objeto da el mismo ilvl (los bonus de temporada fijan un ilvl
        absoluto, no suman: eso descarta los que dependen de la pieza);
      - la lista completa de la subasta da ese mismo ilvl (ningun otro bonus
        de la lista lo mueve).
    """
    resolucion = Resolucion()
    consultas = 0
    cache: dict[tuple[int, tuple[int, ...]], int | None] = {}

    def pedir(item_id: int, bonus: Sequence[int]) -> int | None:
        nonlocal consultas
        clave = (item_id, tuple(bonus))
        if clave not in cache:
            if consultas >= max_consultas:
                raise _SinConsultas()
            consultas += 1
            cache[clave] = consultar(item_id, bonus)
        return cache[clave]

    # bonus -> [(item_id, lista)] donde ha salido.
    donde: dict[int, list[tuple[int, tuple[int, ...]]]] = {}
    for item_id, listas in sorted(observado.sin_ilvl.items()):
        for lista in sorted(listas):
            for b in lista:
                if b not in bonus_ilvl_map:
                    donde.setdefault(b, []).append((item_id, lista))
    objetos = sorted(observado.sin_ilvl)

    try:
        for b, apariciones in sorted(donde.items()):
            item_id, lista = apariciones[0]
            if any(x in resolucion.confirmados for x in lista):
                continue
            try:
                base = pedir(item_id, ())
                solo = pedir(item_id, (b,))
                if solo is None or solo == base or solo < MIN_PLAUSIBLE_ILVL:
                    continue
                otro = next(
                    (i for i, _ in apariciones if i != item_id),
                    next((i for i in objetos if i != item_id), None),
                )
                if otro is None:
                    resolucion.motivos.append(
                        f"El bonus {b} parece dar ilvl {solo}, pero solo lo he "
                        "visto en un objeto y no tengo otro con el que comprobarlo."
                    )
                    continue
                if pedir(otro, (b,)) != solo:
                    resolucion.motivos.append(
                        f"El bonus {b} da ilvl distinto segun el objeto: no es "
                        "de los que fijan el ilvl, no lo apunto."
                    )
                    continue
                if pedir(item_id, lista) != solo:
                    continue
                resolucion.confirmados[b] = solo
            except WowheadError as fallo:
                resolucion.motivos.append(str(fallo))
                break
    except _SinConsultas:
        resolucion.motivos.append(
            f"Hay mas bonus de los que miro en una pasada ({max_consultas} "
            "consultas); el resto lo miro en la siguiente."
        )

    mapa = {**bonus_ilvl_map, **resolucion.confirmados}
    for item_id, listas in observado.sin_ilvl.items():
        pendientes = {lista for lista in listas if not any(b in mapa for b in lista)}
        if pendientes:
            resolucion.sin_resolver[item_id] = pendientes
    return resolucion


class _SinConsultas(Exception):
    pass


# --- Escribirlo en config.yaml -----------------------------------------------

_MAPA = re.compile(r"^bonus_ilvl_map:[ \t]*(?:#.*)?$", re.MULTILINE)
_ENTRADA = re.compile(r"^[ \t]+\d+[ \t]*:[ \t]*\d+", re.MULTILINE)
_PRIMER_NIVEL = re.compile(r"^[^ \t\n#]", re.MULTILINE)


class MapaError(Exception):
    """No se puede escribir en bonus_ilvl_map sin riesgo."""


def anadir_al_mapa(texto: str, nuevos: Mapping[int, int], fecha: str) -> str:
    """config.yaml con los bonus nuevos al final de `bonus_ilvl_map`.

    Por texto y no con PyYAML, por lo mismo que topes.py: el resto del fichero,
    comentarios incluidos, se queda byte a byte igual.
    """
    apertura = _MAPA.search(texto)
    if apertura is None:
        raise MapaError(
            "No encuentro 'bonus_ilvl_map:' en su propia linea en config.yaml."
        )
    siguiente = _PRIMER_NIVEL.search(texto, apertura.end())
    fin = siguiente.start() if siguiente else len(texto)
    entradas = list(_ENTRADA.finditer(texto, apertura.end(), fin))
    if not entradas:
        raise MapaError("'bonus_ilvl_map' no tiene ninguna entrada a la que seguir.")

    corte = texto.find("\n", entradas[-1].end())
    corte = len(texto) if corte == -1 else corte + 1
    antes = texto[:corte] if texto[:corte].endswith("\n") else texto[:corte] + "\n"
    bloque = f"  # Anadidos solos el {fecha}, comprobados en Wowhead\n" + "".join(
        f"  {bonus}: {ilvl}\n" for bonus, ilvl in sorted(nuevos.items())
    )
    return antes + bloque + texto[corte:]


# --- Contarlo -----------------------------------------------------------------


def _oro(cobre: int) -> str:
    return f"{cobre // 10_000:,}".replace(",", ".")


def texto_confirmados(confirmados: Mapping[int, int]) -> str:
    ilvls = sorted(set(confirmados.values()))
    return (
        "Ha salido temporada nueva (o un parche) con bonus ids que no conocia. "
        "Los he comprobado en Wowhead y los he anadido a `bonus_ilvl_map`:\n\n"
        + "\n".join(f"`{b}` → ilvl **{i}**" for b, i in sorted(confirmados.items()))
        + f"\n\nIlvl nuevos: {', '.join(str(i) for i in ilvls)}. No tienes que "
        "hacer nada; si alguno de tus objetos sale a esos ilvl y no lo tienes en "
        "su tabla, te lo digo aparte."
    )


def texto_sin_resolver(
    sin_resolver: Mapping[int, set[tuple[int, ...]]],
    nombres: Mapping[int, str],
    motivos: Sequence[str],
) -> str:
    lineas = [
        f"**{nombres.get(item_id, item_id)}**: bonus "
        + "; ".join(" ".join(str(b) for b in lista) for lista in sorted(listas)[:3])
        for item_id, listas in sorted(sin_resolver.items())
    ]
    texto = (
        "Hay subastas de tus objetos con bonus ids que no se traducir a ilvl, y "
        "no he podido confirmarlos en Wowhead. Mientras tanto te aviso de esos "
        "como *ilvl sin confirmar*, contra tu tope mas barato.\n\n"
        + "\n".join(lineas[:15])
    )
    if motivos:
        texto += "\n\n" + "\n".join(f"• {m}" for m in dict.fromkeys(motivos))
    return texto + (
        "\n\nLo vuelvo a intentar cada pasada. Si sigue asi unos dias (Wowhead "
        "tarda en tener los datos de un parche), se arregla a mano: ver "
        "'Cuando no se puede saber el ilvl' en el README."
    )


def texto_fuera_de_tabla(
    fuera: Mapping[tuple[int, int], int],
    nombres: Mapping[int, str],
    tablas: Mapping[int, Mapping[int, int]],
) -> str:
    lineas = [
        f"**{nombres.get(item_id, item_id)}**: ilvl **{ilvl}**, desde "
        f"{_oro(precio)} de oro (tu tabla llega a {max(tablas[item_id])})"
        if item_id in tablas and tablas[item_id]
        else f"**{nombres.get(item_id, item_id)}**: ilvl **{ilvl}**, desde {_oro(precio)} de oro"
        for (item_id, ilvl), precio in sorted(fuera.items())
    ]
    return (
        "Estos objetos que vigilas estan saliendo a un ilvl que no esta en su "
        "tabla, y de esos no te aviso:\n\n"
        + "\n".join(lineas[:25])
        + "\n\nSi quieres vigilarlos: boton **Anadir objeto** de la app (o la "
        "plantilla 'Anadir un objeto'), con la misma pieza y los ilvl con su "
        "tope. Se anaden a su tabla sin tocar los que ya tiene. Cada ilvl te lo "
        "digo una sola vez."
    )
