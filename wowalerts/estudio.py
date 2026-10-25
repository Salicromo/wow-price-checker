"""Estudio de en que reinos se vende el equipo de ilvl alto.

La API de Blizzard no publica ventas: solo una foto por hora de lo que sigue
a la venta. Aqui se compara la foto de cada reino con la de la hora anterior y
se apunta como venta lo que desaparece sin haber podido caducar. Es la regla
del estudio que se hizo a mano en septiembre y octubre de 2026, ahora pasada a
pasada para que se acumulen dias sin depender del PC.

Una subasta que falta en la foto siguiente pudo venderse, caducar o retirarse:

- Caducar no pudo si le quedaban 12 h o mas (LONG o VERY_LONG).
- Retirarla se reconoce de dos maneras. Si sale otra igual (mismo objeto, ilvl
  y cantidad), es un reposteo. Si desaparece entero un lote de tres o mas
  subidas de una tacada (ids casi seguidos), lo retiro el vendedor: tres
  compradores distintos no se llevan un lote completo en la misma hora.

Lo que queda es una estimacion, no la cifra exacta: una retirada suelta sin
repostear se cuenta como venta.

Las funciones son puras, como historial.py: reciben y devuelven datos, y quien
llama decide donde se guardan.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from .ilvl import resolve_ilvl

ILVLS = (318, 321, 324, 328)

# Le quedan 12 h o mas: entre dos fotos de una hora no puede caducar.
NO_CADUCAN = {"LONG", "VERY_LONG"}

# Dos fotos con mas hueco que esto no se comparan: en ese tiempo hasta una
# LONG pudo caducar, y la cuenta saldria inflada.
HUECO_MAXIMO = int(2.5 * 3600)

DIAS = 14

# Ids de subasta a menos de esto entre si se subieron de una tacada.
HUECO_DE_LOTE = 3000
LOTE_MINIMO = 3

# [id de subasta, id de objeto, ilvl, compra directa, cantidad, tiempo restante]
Fila = list


def filas_del_reino(
    auctions: Iterable[Mapping[str, Any]],
    vigilados: set[int],
    bonus_ilvl_map: Mapping[int, int],
) -> list[Fila]:
    """Las subastas del estudio que hay ahora en un reino."""
    filas = []
    for auction in auctions:
        item = auction.get("item") or {}
        item_id = item.get("id")
        if item_id not in vigilados:
            continue
        buyout = auction.get("buyout")
        if not isinstance(buyout, int) or buyout <= 0:
            continue
        ilvl = resolve_ilvl(item, bonus_ilvl_map).value
        if ilvl not in ILVLS:
            continue
        cantidad = auction.get("quantity")
        if not isinstance(cantidad, int) or cantidad <= 0:
            cantidad = 1
        filas.append(
            [auction.get("id"), item_id, ilvl, buyout, cantidad, auction.get("time_left", "")]
        )
    return filas


def _retiradas(antes: Sequence[Fila], ids_ahora: set) -> set:
    """Ids de los lotes que han desaparecido enteros."""
    lotes: list[list[int]] = []
    for aid in sorted(f[0] for f in antes):
        if lotes and aid - lotes[-1][-1] <= HUECO_DE_LOTE:
            lotes[-1].append(aid)
        else:
            lotes.append([aid])
    return {
        aid
        for lote in lotes
        if len(lote) >= LOTE_MINIMO and not any(a in ids_ahora for a in lote)
        for aid in lote
    }


def comparar(antes: Sequence[Fila], ahora: Sequence[Fila]) -> list[list[int]]:
    """Las ventas entre dos fotos seguidas: [objeto, ilvl, compra directa, cantidad]."""
    ids_antes = {f[0] for f in antes}
    ids_ahora = {f[0] for f in ahora}
    nuevas = Counter((f[1], f[2], f[4]) for f in ahora if f[0] not in ids_antes)
    retiradas = _retiradas(antes, ids_ahora)

    ventas = []
    for aid, item_id, ilvl, buyout, cantidad, quedaba in antes:
        if aid in ids_ahora or quedaba not in NO_CADUCAN or aid in retiradas:
            continue
        if nuevas[(item_id, ilvl, cantidad)] > 0:
            nuevas[(item_id, ilvl, cantidad)] -= 1
            continue
        ventas.append([item_id, ilvl, buyout, cantidad])
    return ventas


def apuntar(estado: dict, realm_id: int, filas: list[Fila], visto: int) -> None:
    """Suma la foto de un reino al estudio y la guarda para la pasada siguiente."""
    fotos = estado.setdefault("fotos", {})
    registro = estado.setdefault("registro", [])
    anterior = fotos.get(str(realm_id))

    if anterior and anterior["visto"] == visto:
        # El mismo volcado otra vez: dos pasadas en la misma hora.
        return
    if anterior and 0 < visto - anterior["visto"] <= HUECO_MAXIMO:
        # Lo que habia a la venta al empezar la hora: lo que se pudo comprar.
        puestas = Counter(f[2] for f in anterior["filas"])
        registro.append(
            {
                "reino": realm_id,
                "hasta": visto,
                "ventas": comparar(anterior["filas"], filas),
                "puestas": {str(lv): puestas.get(lv, 0) for lv in ILVLS},
            }
        )
    fotos[str(realm_id)] = {"visto": visto, "filas": filas}


def recortar(estado: dict, ahora: int) -> None:
    """Olvida lo de hace mas de DIAS dias."""
    limite = ahora - DIAS * 86400
    estado["registro"] = [r for r in estado.get("registro", []) if r["hasta"] >= limite]


def construir_estudio(estado: dict, nombres: Mapping[int, str], ahora: int) -> dict:
    """El fichero que se publica: lo apuntado y el nombre de cada reino."""
    return {
        "generado": ahora,
        "ilvls": list(ILVLS),
        "reinos": {str(rid): nombre for rid, nombre in nombres.items()},
        "registro": estado.get("registro", []),
    }
