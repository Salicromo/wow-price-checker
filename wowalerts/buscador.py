"""El buscador de la app: donde esta mas barato cualquier cosa de la region.

Como la casa de subastas del juego, pero mirando los 92 reinos a la vez. Se
guardan solo los reinos mas baratos de cada producto: la pregunta es "donde
lo compro", y para eso el reino numero cuarenta no aporta nada y multiplica
por cuatro lo que baja el movil.

Los materiales y consumibles (commodities) no salen: Blizzard los vende en
una casa comun a toda la region, asi que cuestan lo mismo en todos los reinos
y no vienen en el volcado de cada uno.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .mercado import TIPO_MASCOTA, Clave, ResumenReino

# Por debajo de esto hay decenas de miles de objetos de dos cobres que nadie
# busca. Mismo suelo que la web publica y analizar_mercado.py.
PRECIO_MINIMO_ORO = 500

REINOS_POR_PRODUCTO = 10

# Nombres nuevos que se piden por pasada. La primera vez son ~20.000 objetos y
# dos peticiones por cada uno; de golpe se comeria la cuota horaria de la API
# y retrasaria la pasada. Asi el catalogo se completa en unas cinco horas.
NOMBRES_POR_PASADA = 4000

COBRE_POR_ORO = 10_000

# (orden de grupo, precio minimo en cobre, cuantas en venta)
Oferta = tuple[int, int, int]


def clave_de_nombre(clave: Clave) -> str:
    """'o:123' o 'm:45': el nombre es del producto, no de la variante."""
    return ("m:" if clave.tipo == TIPO_MASCOTA else "o:") + str(clave.id)


def acumular(
    ofertas: dict[Clave, list[Oferta]],
    grupo: int,
    resumen: Mapping[Clave, ResumenReino],
    limite: int = REINOS_POR_PRODUCTO,
) -> None:
    """Suma un reino a lo acumulado, quedandose con los `limite` mas baratos.

    Se recorta sobre la marcha para no tener los 92 reinos en memoria a la vez.
    """
    for clave, r in resumen.items():
        if not r.precios:
            continue
        lista = ofertas.setdefault(clave, [])
        lista.append((grupo, r.precios[0], r.listados))
        if len(lista) > limite:
            lista.sort(key=lambda o: o[1])
            del lista[limite:]


def nombres_que_faltan(
    ofertas: Mapping[Clave, list[Oferta]],
    conocidos: Mapping[str, Any],
    limite: int = NOMBRES_POR_PASADA,
) -> list[Clave]:
    """Productos sin nombre todavia, los que mas se venden primero.

    Mientras el catalogo se va llenando, que lo primero en aparecer sea lo que
    esta en mas reinos: es lo que mas probablemente vas a buscar.
    """
    difusion: dict[str, tuple[int, Clave]] = {}
    for clave, lista in ofertas.items():
        nombre = clave_de_nombre(clave)
        if nombre in conocidos:
            continue
        previo = difusion.get(nombre)
        if previo is None or len(lista) > previo[0]:
            difusion[nombre] = (len(lista), clave)
    orden = sorted(difusion.values(), key=lambda d: (-d[0], d[1].tipo, d[1].id))
    return [clave for _, clave in orden[:limite]]


def construir_indice(
    ofertas: Mapping[Clave, list[Oferta]],
    nombres: Mapping[str, Mapping[str, Any]],
    grupos: Iterable[tuple[str, list[str], int]],
    generado: int,
) -> dict[str, Any]:
    """El fichero que baja la app.

    Lo que aun no tiene nombre no sale: no hay forma de buscarlo. Los precios
    van en oro, que es como se habla en el juego y ocupa menos.
    """
    productos: dict[str, dict[str, Any]] = {}
    for clave, lista in ofertas.items():
        nombre = nombres.get(clave_de_nombre(clave))
        if not nombre or not (nombre.get("es") or nombre.get("en")):
            continue
        ficha = productos.setdefault(clave_de_nombre(clave), {
            "t": "m" if clave.tipo == TIPO_MASCOTA else "o",
            "id": clave.id,
            "es": nombre.get("es") or nombre.get("en"),
            "en": nombre.get("en") or nombre.get("es"),
            "i": nombre.get("icono"),
            "v": [],
        })
        ficha["v"].append([
            clave.variante,
            [[g, minimo // COBRE_POR_ORO, n] for g, minimo, n in sorted(lista, key=lambda o: o[1])],
        ])

    for ficha in productos.values():
        ficha["v"].sort(key=lambda v: -1 if v[0] is None else v[0])

    return {
        "version": 1,
        "generado": generado,
        "grupos": [
            {"nombre": nombre, "slugs": slugs, "visto": visto}
            for nombre, slugs, visto in grupos
        ],
        "productos": sorted(productos.values(), key=lambda p: (p["t"], p["id"])),
    }
