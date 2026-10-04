"""Busca productos que valgan mucho mas en unos reinos que en otros.

Se baja el volcado de subastas de toda la region, lo resume a unos pocos
precios por producto y reino, y saca dos listas:

  1. Arbitrajes: comprar en el reino barato y vender en el caro (banco de
     hermandad de guerra por medio).
  2. Flips locales: comprar y revender sin salir del mismo reino.

Con `--solo` se mira una categoria en vez de todo:

    .venv\\Scripts\\python.exe analizar_mercado.py --solo monturas,juguetes
    .venv\\Scripts\\python.exe analizar_mercado.py --solo mascotas --top 40

Al final imprime las lineas listas para pegar en la seccion `items:` de
config.yaml, con el umbral puesto donde tiene sentido: la mediana de los
minimos de la region dividida por el ratio pedido, o sea "avisame cuando este a
menos de un tercio de lo que vale". Las mascotas se quedan fuera de esa parte a
proposito: el vigilante distingue por item_id y todas comparten el 82800, asi
que una regla para una seria una regla para todas.

El volcado agregado se guarda, asi que se pueden repetir los calculos con otros
umbrales sin volver a bajarse media region:

    .venv\\Scripts\\python.exe analizar_mercado.py --desde analisis/<fichero>.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardClient, BlizzardError
from wowalerts.catalogo import cargar as cargar_catalogo
from wowalerts.config import COPPER_PER_GOLD, load_config
from wowalerts.mercado import (
    TIPO_MASCOTA,
    TIPO_OBJETO,
    Clave,
    ResumenReino,
    agregar,
    arbitrajes,
    flips_locales,
    percentil,
    resumir_reino,
)

log = logging.getLogger("analizar")

DIR_ANALISIS = Path("analisis")
CATEGORIAS = ("mascotas", "monturas", "juguetes", "equipo")

# Calidad de las mascotas, que en las subastas viene como numero.
CALIDAD = {0: "pobre", 1: "comun", 2: "poco comun", 3: "rara", 4: "epica"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--realms",
        default="",
        help="Ids de connected realm separados por comas. Vacio = toda la region.",
    )
    parser.add_argument(
        "--solo",
        default="",
        help=f"Categorias a mirar, separadas por comas: {', '.join(CATEGORIAS)}. "
        "Vacio = todo.",
    )
    parser.add_argument(
        "--refrescar-catalogo",
        action="store_true",
        help="Vuelve a pedir a Blizzard que objetos son monturas y juguetes.",
    )
    parser.add_argument(
        "--precio-minimo",
        type=int,
        default=500,
        help="En oro. Por debajo de esto no se mira nada (defecto: 500).",
    )
    parser.add_argument(
        "--beneficio-minimo",
        type=int,
        default=20_000,
        help="En oro, ya descontada la comision (defecto: 20000).",
    )
    parser.add_argument(
        "--ratio-minimo",
        type=float,
        default=3.0,
        help="Cuantas veces mas caro tiene que ser vender que comprar (defecto: 3).",
    )
    parser.add_argument(
        "--reinos-minimos",
        type=int,
        default=15,
        help="Reinos con dato para fiarse de la estadistica (defecto: 15).",
    )
    parser.add_argument(
        "--reinos-rentables",
        type=int,
        default=5,
        help="En cuantos reinos tiene que dar beneficio para creerselo (defecto: 5).",
    )
    parser.add_argument(
        "--valor-minimo",
        type=int,
        default=0,
        help="En oro. Solo productos cuya mediana en la region llegue a esto, "
        "para no llenar la lista de calderilla con buen porcentaje.",
    )
    parser.add_argument(
        "--venta-maxima",
        type=int,
        default=5_000_000,
        help="En oro. Una mediana por encima de esto es precio aparcado, no "
        "mercado (defecto: 5000000). A 0 se desactiva.",
    )
    parser.add_argument(
        "--vigilar",
        action="store_true",
        help="Las lineas de config salen de TODO lo que pase --valor-minimo, no "
        "solo de lo que hoy tenga una ganga. Es lo que quieres para dejar la "
        "trampa puesta: los productos caros casi nunca estan de oferta, y la "
        "gracia del vigilante es enterarse el dia que lo esten.",
    )
    parser.add_argument("--top", type=int, default=25, help="Filas por tabla.")
    parser.add_argument(
        "--desde",
        default="",
        help="Reutiliza un agregado ya guardado en vez de bajarse la region.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


# -- descarga ---------------------------------------------------------------


def descargar(client, config, realm_ids: list[int], precio_minimo_cobre: int):
    """Baja cada reino, lo resume y suelta las subastas antes del siguiente.

    Resumir dentro del hilo es lo que hace esto viable: si se devolvieran las
    subastas crudas, la region entera no cabria en memoria.
    """
    resumenes: list[tuple[int, dict]] = []

    def una(realm_id: int):
        snapshot = client.auctions(realm_id)
        resumen = resumir_reino(
            snapshot.auctions, config.bonus_ilvl_map, precio_minimo_cobre
        )
        return realm_id, resumen, len(snapshot.auctions)

    with ThreadPoolExecutor(max_workers=config.settings.max_workers) as pool:
        for futuro in [pool.submit(una, r) for r in realm_ids]:
            try:
                realm_id, resumen, vistas = futuro.result()
            except BlizzardError as exc:
                log.warning("Reino omitido: %s", exc)
                continue
            resumenes.append((realm_id, resumen))
            log.info(
                "  reino %s: %s subastas, %s productos por encima del suelo",
                realm_id,
                vistas,
                len(resumen),
            )

    return resumenes


def guardar(resumenes, region: str) -> Path:
    DIR_ANALISIS.mkdir(exist_ok=True)
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    destino = DIR_ANALISIS / f"mercado-{region}-{sello}.json"
    crudo = {
        str(realm_id): {
            f"{c.tipo}:{c.id}:{'' if c.variante is None else c.variante}": [
                list(d.precios),
                d.listados,
            ]
            for c, d in resumen.items()
        }
        for realm_id, resumen in resumenes
    }
    destino.write_text(json.dumps(crudo), encoding="utf-8")
    return destino


def cargar(ruta: str):
    crudo = json.loads(Path(ruta).read_text(encoding="utf-8"))
    resumenes = []
    for realm_id, productos in crudo.items():
        resumen = {}
        for texto, (precios, listados) in productos.items():
            tipo, id_, variante = texto.split(":")
            clave = Clave(tipo, int(id_), int(variante) if variante else None)
            resumen[clave] = ResumenReino(precios=tuple(precios), listados=listados)
        resumenes.append((int(realm_id), resumen))
    return resumenes


# -- filtrado por categoria -------------------------------------------------


def filtrar(agregado, categorias: set[str], catalogo) -> dict:
    """Se queda con las categorias pedidas.

    "equipo" es todo lo que no es ninguna de las otras tres, o sea armaduras y
    armas, pero tambien recetas, materiales y transmog.
    """
    if not categorias:
        return agregado

    monturas = catalogo.get("monturas", set())
    juguetes = catalogo.get("juguetes", set())

    def categoria_de(clave: Clave) -> str:
        if clave.es_mascota:
            return "mascotas"
        if clave.id in monturas:
            return "monturas"
        if clave.id in juguetes:
            return "juguetes"
        return "equipo"

    return {c: v for c, v in agregado.items() if categoria_de(c) in categorias}


# -- presentacion -----------------------------------------------------------


def oro(cobre: int) -> str:
    return f"{cobre // COPPER_PER_GOLD:,}".replace(",", ".")


class Nombres:
    """Nombres de producto y de reino, pedidos solo para lo que se imprime."""

    def __init__(self, client):
        self.client = client
        self._productos: dict[Clave, str] = {}
        self._reinos: dict[int, str] = {}

    def producto(self, clave: Clave) -> str:
        if clave not in self._productos:
            if clave.es_mascota:
                nombre = self.client.pet_species_name(clave.id) or f"especie {clave.id}"
                calidad = CALIDAD.get(clave.variante)
                self._productos[clave] = f"{nombre} ({calidad})" if calidad else nombre
            else:
                self._productos[clave] = (
                    self.client.item_name(clave.id) or f"objeto {clave.id}"
                )
        return self._productos[clave]

    def reino(self, realm_id: int) -> str:
        if realm_id not in self._reinos:
            self._reinos[realm_id] = self.client.connected_realm_name(realm_id)
        return self._reinos[realm_id]


def variante_de(clave: Clave) -> str:
    """Lo que va en la columna de variante: el ilvl del equipo, o nada."""
    if clave.es_mascota or clave.variante is None:
        return "-"
    return str(clave.variante)


def tabla_arbitrajes(filas, nombres) -> None:
    print()
    print("=" * 118)
    print(" COMPRAR EN UN REINO, VENDER EN OTRO (banco de hermandad de guerra)")
    print("=" * 118)
    print(
        f"{'PRODUCTO':<44} {'ILVL':>5} {'COMPRA EN':<22} {'PRECIO':>10} "
        f"{'MEDIANA':>10} {'NETO':>10} {'RENT/TOT':>8}"
    )
    print("-" * 118)
    for a in filas:
        print(
            f"{nombres.producto(a.clave)[:43]:<44} "
            f"{variante_de(a.clave):>5} "
            f"{nombres.reino(a.reino_compra)[:21]:<22} "
            f"{oro(a.precio_compra):>10} "
            f"{oro(a.venta_tipica):>10} "
            f"{oro(a.neto_tipico):>10} "
            f"{a.reinos_rentables:>3}/{a.reinos_con_dato:<3}"
        )


def tabla_flips(filas, nombres) -> None:
    print()
    print("=" * 118)
    print(" COMPRAR Y REVENDER EN EL MISMO REINO")
    print("=" * 118)
    print(
        f"{'PRODUCTO':<44} {'ILVL':>5} {'REINO':<22} {'COMPRA':>10} "
        f"{'REVENTA':>10} {'NETO':>10} {'SUBASTAS':>8}"
    )
    print("-" * 118)
    for f in filas:
        print(
            f"{nombres.producto(f.clave)[:43]:<44} "
            f"{variante_de(f.clave):>5} "
            f"{nombres.reino(f.realm_id)[:21]:<22} "
            f"{oro(f.compra):>10} "
            f"{oro(f.referencia):>10} "
            f"{oro(f.neto):>10} "
            f"{f.listados_reino:>8}"
        )


def vigilables(agregado, valor_minimo: int, reinos_minimos: int) -> set:
    """Todo lo que valga lo suficiente como para querer enterarse.

    Nada que ver con si hoy hay ganga: un objeto de dos millones puede pasarse
    semanas sin que nadie lo tire de precio, y precisamente por eso interesa
    tener el aviso puesto en vez de mirarlo a mano.
    """
    elegidos = set()
    for clave, por_realm in agregado.items():
        if len(por_realm) < reinos_minimos:
            continue
        minimos = sorted(d.minimo for d in por_realm.values())
        if percentil(minimos, 50) >= valor_minimo:
            elegidos.add(clave)
    return elegidos


def tabla_valor(agregado, claves, nombres, umbral_ganga: float = 0.4) -> None:
    """Lo que hay, ordenado por lo que vale, haya hoy ganga o no.

    Las otras dos tablas contestan "que compro ahora". Esta contesta "que me
    conviene tener vigilado", que es una pregunta distinta: un producto de dos
    millones puede pasarse semanas sin una sola oferta y seguir siendo el que
    mas te interesa que suene.
    """
    print()
    print("=" * 104)
    print(" CATALOGO POR VALOR")
    print("=" * 104)
    print(
        f"{'PRODUCTO':<44} {'MEDIANA':>12} {'MAS BARATO':>12} {'REINOS':>7} {'GANGAS':>7}"
    )
    print("-" * 104)

    filas = []
    for clave in claves:
        por_realm = agregado[clave]
        minimos = sorted(d.minimo for d in por_realm.values())
        mediana = percentil(minimos, 50)
        gangas = sum(1 for m in minimos if m <= mediana * umbral_ganga)
        filas.append((mediana, minimos[0], len(minimos), gangas, clave))

    for mediana, barato, reinos, gangas, clave in sorted(filas, reverse=True):
        print(
            f"{nombres.producto(clave)[:43]:<44} "
            f"{oro(mediana):>12} {oro(barato):>12} {reinos:>7} {gangas:>7}"
        )
    print()
    print(
        f"{len(filas)} productos. GANGAS = reinos donde lo mas barato esta al "
        f"{umbral_ganga:.0%} o menos de la mediana."
    )


def sugerencias_config(
    agregado, claves, nombres, ratio: float, venta_maxima: int
) -> None:
    """Lineas listas para pegar en `items:` del config.

    El umbral es la mediana de los minimos de la region dividida por el ratio
    que has pedido: "avisame cuando este a menos de un tercio de lo que vale".

    Un percentil de los minimos parece mas fino, pero no lo es. En estos objetos
    la distribucion no es una cuesta, son dos mesetas: cuatro o cinco reinos con
    el objeto tirado y setenta con el mismo precio repetido al cobre --el mismo
    vendedor publicando en toda la region--. El percentil 25 cae dentro de la
    meseta cara, asi que como umbral saltaria en casi todos los reinos. Una
    fraccion de la mediana cae donde tiene que caer: en el hueco entre las dos.

    Las mascotas salen con `pet_species_id` en vez de `item_id`, que es como
    las pide el vigilante: por item_id todas serian el 82800 y una regla para
    el Dragoncito Celestial avisaria tambien de cada rata en venta.
    """
    print()
    print("=" * 118)
    print(f" PARA PEGAR EN config.yaml (umbral = mediana de la region / {ratio:g})")
    print("=" * 118)

    por_item: dict[int, dict[int | None, int]] = {}
    mascotas: dict[Clave, int] = {}
    for clave, por_realm in agregado.items():
        if clave not in claves:
            continue
        minimos = sorted(d.minimo for d in por_realm.values())
        if len(minimos) < 5:
            continue
        mediana = percentil(minimos, 50)
        # Mismo criterio que en los arbitrajes: una mediana imposible es un
        # precio aparcado, y poner ahi un umbral solo trae avisos de humo.
        if venta_maxima and mediana > venta_maxima:
            continue
        if clave.es_mascota:
            mascotas[clave] = int(mediana / ratio)
        else:
            por_item.setdefault(clave.id, {})[clave.variante] = int(mediana / ratio)

    for item_id, por_ilvl in por_item.items():
        print(f'  - name: "{nombres.producto(Clave(TIPO_OBJETO, item_id))}"')
        print(f"    item_id: {item_id}")
        con_ilvl = {k: v for k, v in por_ilvl.items() if k is not None}
        if con_ilvl:
            filas = ", ".join(
                f"{ilvl}: {precio // COPPER_PER_GOLD}"
                for ilvl, precio in sorted(con_ilvl.items())
            )
            print(f"    max_price_by_ilvl: {{ {filas} }}")
        else:
            print(f"    max_price: {por_ilvl[None] // COPPER_PER_GOLD}")
            print("    avisar_undercut: false")
        print()

    for clave, precio in mascotas.items():
        print(f'  - name: "{nombres.producto(clave)}"')
        print(f"    pet_species_id: {clave.id}")
        print(f"    max_price: {precio // COPPER_PER_GOLD}")
        print("    avisar_undercut: false")
        print()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    load_dotenv()
    config = load_config(args.config)

    categorias = {c.strip() for c in args.solo.split(",") if c.strip()}
    desconocidas = categorias - set(CATEGORIAS)
    if desconocidas:
        print(
            f"No conozco la categoria {', '.join(sorted(desconocidas))}. "
            f"Las que hay: {', '.join(CATEGORIAS)}.",
            file=sys.stderr,
        )
        return 2

    client = BlizzardClient(
        os.getenv("BLIZZARD_CLIENT_ID", ""),
        os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )

    if args.desde:
        log.info("Reutilizando %s", args.desde)
        resumenes = cargar(args.desde)
    else:
        realm_ids = (
            [int(r) for r in args.realms.split(",") if r.strip()]
            if args.realms
            else client.connected_realm_ids()
        )
        log.info(
            "Bajando %s reinos (suelo: %s oro)...", len(realm_ids), args.precio_minimo
        )
        arranque = time.monotonic()
        resumenes = descargar(
            client, config, realm_ids, args.precio_minimo * COPPER_PER_GOLD
        )
        log.info(
            "%s reinos en %.0f s. Guardado en %s",
            len(resumenes),
            time.monotonic() - arranque,
            guardar(resumenes, config.region),
        )

    agregado = agregar(resumenes)
    log.info("%s productos distintos en la region", len(agregado))

    if categorias:
        catalogo = (
            cargar_catalogo(
                client,
                DIR_ANALISIS / f"catalogo-{config.region}.json",
                refrescar=args.refrescar_catalogo,
                max_workers=config.settings.max_workers,
            )
            if categorias & {"monturas", "juguetes", "equipo"}
            else {}
        )
        agregado = filtrar(agregado, categorias, catalogo)
        log.info("%s tras filtrar por %s", len(agregado), ", ".join(sorted(categorias)))

    comision = config.settings.ah_cut_pct
    comunes = dict(
        comision_pct=comision,
        beneficio_minimo=args.beneficio_minimo * COPPER_PER_GOLD,
        ratio_minimo=args.ratio_minimo,
        reinos_minimos=args.reinos_minimos,
    )
    arbis = arbitrajes(
        agregado,
        reinos_rentables_minimos=args.reinos_rentables,
        valor_minimo=args.valor_minimo * COPPER_PER_GOLD,
        venta_maxima=args.venta_maxima * COPPER_PER_GOLD,
        **comunes,
    )
    flips = flips_locales(agregado, **comunes)
    log.info(
        "%s arbitrajes y %s flips locales por encima del filtro", len(arbis), len(flips)
    )

    if args.vigilar:
        destacados = vigilables(
            agregado, args.valor_minimo * COPPER_PER_GOLD, args.reinos_minimos
        )
        log.info("%s productos a vigilar por valor", len(destacados))
    else:
        destacados = {a.clave for a in arbis[: args.top]}
        destacados.update(f.clave for f in flips[: args.top])

    nombres = Nombres(client)
    if args.vigilar:
        tabla_valor(agregado, destacados, nombres)
    else:
        tabla_arbitrajes(arbis[: args.top], nombres)
        tabla_flips(flips[: args.top], nombres)

    sugerencias_config(
        agregado,
        destacados,
        nombres,
        args.ratio_minimo,
        args.venta_maxima * COPPER_PER_GOLD,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
