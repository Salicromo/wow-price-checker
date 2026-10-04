"""Llena la base de la web publica con el volcado de esta hora.

    py publicar_web.py                      # toda la region
    py publicar_web.py --realms 1305,1329   # dos reinos, para probar
    py publicar_web.py --db /srv/web.db     # otra ruta de base

Va aparte de `main.py` a proposito: main manda tus alertas y no conviene
tocarlo para esto.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from web.db import abrir, ruta_de_entorno
from web.ingesta import (
    guardar_atributos,
    guardar_iconos,
    guardar_nombres,
    guardar_reinos,
    recalcular_estadisticas,
    volcar,
)
from wowalerts.blizzard import BlizzardClient, BlizzardError
from wowalerts.config import COPPER_PER_GOLD, load_config
from wowalerts.mercado import TIPO_OBJETO, Clave, ResumenReino, agregar, resumir_reino

log = logging.getLogger("publicar_web")

# Mismos numeros que `main.py` (EXIT_OK / EXIT_TOO_MANY_FAILURES): un cron que
# vigile las dos pasadas no tiene que aprenderse dos convenios distintos para
# saber si una region ha salido incompleta.
EXIT_OK = 0
EXIT_DEMASIADOS_FALLOS = 2

# Mismo suelo que analizar_mercado.py: por debajo de esto hay decenas de
# miles de objetos de dos cobres que nadie busca jamas, y la region entera no
# cabria en memoria si se guardaran.
PRECIO_MINIMO_ORO = 500

# Cuantos iconos atrasados se rellenan por pasada. Ver `productos_sin_icono`:
# el catalogo entero son ~18.000 peticiones extra y esto corre cada hora, asi
# que se va cerrando el hueco a plazos. Con 3.000 por pasada el catalogo
# queda completo en unas seis horas. `--iconos` lo sube para un relleno
# inicial de una sentada.
ICONOS_POR_PASADA = 3000

# Lo mismo para las categorias. Se rellenan al mismo ritmo y por lo mismo:
# 19.365 productos se guardaron antes de que existiera la tabla `atributo`.
ATRIBUTOS_POR_PASADA = 3000

# Los idiomas que sirve la web, guardados con el codigo de dos letras que usa
# `web.consultas.IDIOMA_POR_DEFECTO` y que es la clave `idioma` de la tabla
# `nombre`. Blizzard devuelve doce locales por objeto (verificado contra la
# API), pero tres pares truncan al mismo codigo de dos letras --en_GB/en_US a
# "en", es_ES/es_MX a "es", zh_CN/zh_TW a "zh"--, y guardar los doce pisaria
# una version con la otra segun el orden en que llegue el diccionario de
# Blizzard. Se eligen ocho sin colision: los idiomas nativos de las regiones
# que soporta este proyecto (`wowalerts.config.VALID_REGIONS` = eu/us/kr/tw)
# --ingles para eu y us, coreano para kr, chino para tw-- mas los otros
# cuatro idiomas grandes de la region eu (aleman, frances, italiano, ruso).
# Se deja fuera portugues de Brasil porque no hay ninguna region soportada
# aqui donde sea el idioma nativo. Dentro de cada pareja que colisiona: de
# en_GB/en_US se guarda GB porque "eu" es la region por defecto de
# config.yaml; de es_ES/es_MX se guarda ES, el castellano en el que esta
# escrito este proyecto; de zh_CN/zh_TW se guarda TW, porque es la que
# corresponde a la region "tw" que si se soporta (China no es una region de
# Battle.net aqui).
IDIOMAS = {
    "de_DE": "de",
    "en_GB": "en",
    "es_ES": "es",
    "fr_FR": "fr",
    "it_IT": "it",
    "ko_KR": "ko",
    "ru_RU": "ru",
    "zh_TW": "zh",
}

FilaNombre = tuple[str, int, str, str, str | None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        # Sin valor por defecto aqui: se resuelve en main(), DESPUES de
        # load_dotenv(), porque argparse evalua los defaults al construir el
        # parser y para entonces el .env todavia no se ha leido.
        "--db",
        default=None,
        help="Ruta de la base de la web publica. Por defecto, $AUCTION_DB.",
    )
    parser.add_argument(
        "--realms",
        default="",
        help="Ids de connected realm separados por comas. Vacio = toda la region.",
    )
    parser.add_argument(
        "--iconos",
        type=int,
        default=ICONOS_POR_PASADA,
        help=(
            "Cuantos iconos atrasados rellenar en esta pasada. 0 los desactiva. "
            "Subelo para el relleno inicial del catalogo entero."
        ),
    )
    parser.add_argument(
        "--atributos",
        type=int,
        default=ATRIBUTOS_POR_PASADA,
        help=(
            "Cuantas categorias atrasadas rellenar en esta pasada. 0 las "
            "desactiva. Subelo para clasificar el catalogo entero de una vez."
        ),
    )
    parser.add_argument(
        "--solo-atributos",
        action="store_true",
        help=(
            "Solo rellena categorias que falten: no baja subastas ni toca los "
            "precios."
        ),
    )
    parser.add_argument(
        "--solo-iconos",
        action="store_true",
        help=(
            "Solo rellena iconos que falten: no baja subastas ni toca los "
            "precios. Para el relleno inicial del catalogo."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


# -- descarga -----------------------------------------------------------------


def descargar_reinos(
    client: BlizzardClient, config, realm_ids: Sequence[int], precio_minimo_cobre: int
) -> tuple[list[tuple[int, dict[Clave, ResumenReino]]], dict[int, str]]:
    """Baja, resume y nombra cada reino en paralelo. Mismo patron que
    `analizar_mercado.descargar`: resumir dentro del hilo es lo que hace esto
    viable, porque la region entera no cabe en memoria si se devuelven las
    subastas crudas.

    El nombre del reino se pide en el mismo hilo que sus subastas y no aparte:
    hacen falta los nombres de TODOS los reinos que respondan (la tabla
    `reino` es el indice publico de la web), asi que no hay peticion que
    ahorrar uniendola a la que ya se estaba haciendo.
    """
    resumenes: list[tuple[int, dict[Clave, ResumenReino]]] = []
    nombres_reino: dict[int, str] = {}

    def una(realm_id: int):
        snapshot = client.auctions(realm_id)
        resumen = resumir_reino(
            snapshot.auctions, config.bonus_ilvl_map, precio_minimo_cobre
        )
        nombre = client.connected_realm_name(realm_id)
        return realm_id, resumen, nombre, len(snapshot.auctions)

    with ThreadPoolExecutor(max_workers=config.settings.max_workers) as pool:
        for futuro in [pool.submit(una, r) for r in realm_ids]:
            try:
                realm_id, resumen, nombre, vistas = futuro.result()
            except BlizzardError as exc:
                log.warning("Reino omitido: %s", exc)
                continue
            resumenes.append((realm_id, resumen))
            nombres_reino[realm_id] = nombre
            log.info(
                "  reino %s (%s): %s subastas, %s productos por encima del suelo",
                realm_id,
                nombre,
                vistas,
                len(resumen),
            )

    return resumenes, nombres_reino


def productos_sin_nombre(con, agregado) -> list[tuple[str, int]]:
    """Que (tipo, producto_id) del agregado no tienen fila todavia en `nombre`.

    Los nombres no cambian salvo que Blizzard saque un parche, asi que solo
    hace falta pedirlos la primera vez que aparece un producto: la primera
    pasada pide los ~20 000 objetos que haya en la region, y las siguientes
    casi ninguno. Sin esto, cada pasada horaria repetiria las mismas 20 000
    peticiones que ya se sabian de la pasada anterior.

    Solo entran los objetos (`TIPO_OBJETO`): `item_names` pide por item id, y
    las mascotas no tienen uno propio en las subastas -- todas son la misma
    jaula y lo que las distingue es la especie (ver `wowalerts.mercado`).
    """
    conocidos = {
        (fila[0], fila[1])
        for fila in con.execute("SELECT DISTINCT tipo, producto_id FROM nombre")
    }
    vistos: set[tuple[str, int]] = set()
    faltan: list[tuple[str, int]] = []
    for clave in agregado:
        if clave.tipo != TIPO_OBJETO:
            continue
        par = (clave.tipo, clave.id)
        if par in conocidos or par in vistos:
            continue
        vistos.add(par)
        faltan.append(par)
    return faltan


def pedir_datos(
    client: BlizzardClient, faltan: Sequence[tuple[str, int]], max_workers: int
) -> tuple[list[FilaNombre], list[dict]]:
    """Nombres y atributos de lo que falte, en paralelo. Una peticion por objeto.

    Incluso en la primera pasada son del orden de 20 000 objetos: en serie
    tardaria decenas de minutos, y el volcado de subastas que se esta
    publicando se renueva cada hora.

    `client.item_datos` se traga sus propios errores y devuelve None si un
    objeto falla, asi que no hace falta capturar nada aqui: un objeto que hoy
    no responde se vuelve a intentar en la pasada siguiente, porque sigue sin
    tener fila en `nombre`.

    Un objeto sin categoria no se guarda NI CON NOMBRE, a proposito. Si se
    guardara el nombre, dejaria de aparecer en `productos_sin_nombre` y ya no
    se volveria a preguntar por el nunca, quedandose sin categoria para
    siempre. Prefiero reintentarlo cada hora: son pocos y la alternativa es
    perderlos.

    Dos peticiones por objeto nuevo en total --esta y la del icono-- y ninguna
    para los ~20.000 que ya estan guardados.
    """
    nombres: list[FilaNombre] = []
    atributos: list[dict] = []

    def uno(par: tuple[str, int]):
        tipo, producto_id = par
        return tipo, producto_id, client.item_datos(producto_id), client.item_icon_url(
            producto_id
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for futuro in [pool.submit(uno, par) for par in faltan]:
            tipo, producto_id, datos, icono = futuro.result()
            if datos is None:
                continue
            for locale, codigo in IDIOMAS.items():
                nombre = datos["nombres"].get(locale)
                if nombre:
                    nombres.append((tipo, producto_id, codigo, nombre, icono))
            atributos.append({"tipo": tipo, "producto_id": producto_id, **datos})

    return nombres, atributos


def productos_sin_atributos(con, limite: int) -> list[tuple[str, int]]:
    """Productos con nombre pero sin categoria, hasta `limite`.

    El gemelo de `productos_sin_icono`, y por lo mismo: los 19.365 objetos que
    se guardaron antes de que existiera la tabla `atributo` ya tienen fila en
    `nombre`, asi que `productos_sin_nombre` no vuelve a mirarlos y sin esto no
    tendrian categoria jamas --ni saldrian en ninguna pagina de /items.
    """
    return [
        (fila[0], fila[1])
        for fila in con.execute(
            "SELECT DISTINCT n.tipo, n.producto_id FROM nombre n "
            " WHERE NOT EXISTS (SELECT 1 FROM atributo a "
            "                    WHERE a.tipo = n.tipo "
            "                      AND a.producto_id = n.producto_id) "
            " ORDER BY n.producto_id "
            " LIMIT ?",
            (limite,),
        )
    ]


def pedir_atributos(
    client: BlizzardClient, faltan: Sequence[tuple[str, int]], max_workers: int
) -> list[dict]:
    """Los atributos que falten, en paralelo. Igual que `pedir_iconos`."""

    def uno(par: tuple[str, int]):
        tipo, producto_id = par
        return tipo, producto_id, client.item_datos(producto_id)

    filas = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for futuro in [pool.submit(uno, par) for par in faltan]:
            tipo, producto_id, datos = futuro.result()
            if datos is not None:
                filas.append({"tipo": tipo, "producto_id": producto_id, **datos})
    return filas


def productos_sin_icono(con, limite: int) -> list[tuple[str, int]]:
    """Productos que ya tienen nombre pero no icono, hasta `limite`.

    Hace falta porque `productos_sin_nombre` solo mira lo que NO esta en la
    tabla: los 18.675 objetos que se guardaron cuando el icono se dejaba
    siempre a None ya tienen su fila, asi que por ahi no vuelven a pasar y no
    verian una foto jamas.

    El limite no es decoracion: son ~18.000 peticiones extra a la API de
    Blizzard, y meterlas de golpe en una pasada que corre cada hora es la
    forma de que te limiten el ritmo. A `ICONOS_POR_PASADA` por vez el hueco
    se cierra solo en unas cuantas pasadas y ninguna se alarga de mas.
    """
    return [
        (fila[0], fila[1])
        for fila in con.execute(
            "SELECT DISTINCT tipo, producto_id FROM nombre "
            " WHERE icono IS NULL "
            " ORDER BY producto_id "
            " LIMIT ?",
            (limite,),
        )
    ]


def pedir_iconos(
    client: BlizzardClient, faltan: Sequence[tuple[str, int]], max_workers: int
) -> list[tuple[str, int, str | None]]:
    """Los iconos que falten, en paralelo. Igual que `pedir_atributos`.

    `item_icon_url` ya se traga sus errores y devuelve None, y `guardar_iconos`
    descarta los None, asi que un objeto que falle hoy se reintenta manana sin
    que nadie tenga que llevar la cuenta.
    """
    def uno(par: tuple[str, int]):
        tipo, producto_id = par
        return tipo, producto_id, client.item_icon_url(producto_id)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return [f.result() for f in [pool.submit(uno, par) for par in faltan]]


# -- orquestacion ---------------------------------------------------------------


def poblar(
    con,
    agregado,
    nombres_reino: dict[int, str],
    nombres_producto: Sequence[FilaNombre],
    generado_en: int,
) -> int:
    """Escribe una pasada entera en la base. Pura: nada de esto toca la red.

    El orden importa: reinos y nombres primero, porque la pagina de producto
    los necesita para renderizar (`web.consultas.ficha` cae a "#id" sin un
    nombre, y `reinos_de` sin un reino no tiene de donde sacar el nombre de
    la fila). Los precios van al final -- `volcar` es lo que se reemplaza
    entero dentro de una transaccion, y es lo que decide que la pasada ha
    terminado de verdad.
    """
    guardar_reinos(con, nombres_reino)
    if nombres_producto:
        guardar_nombres(con, nombres_producto)
    filas = volcar(con, agregado, generado_en)
    recalcular_estadisticas(con)
    return filas


def main(argv=None, *, client: BlizzardClient | None = None) -> int:
    """Punto de entrada del script.

    `client` es la unica costura pensada para los tests: dejar que se inyecte
    un cliente falso permite probar el contrato de codigos de salida sin red,
    sin tocar como esta construido el resto de la funcion.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    load_dotenv()
    # Ahora si: el .env ya esta leido, asi que AUCTION_DB dice lo que tenga que
    # decir. El --db explicito sigue mandando sobre el.
    ruta_db = Path(args.db) if args.db else ruta_de_entorno()
    config = load_config(args.config)

    if client is None:
        client = BlizzardClient(
            os.getenv("BLIZZARD_CLIENT_ID", ""),
            os.getenv("BLIZZARD_CLIENT_SECRET", ""),
            region=config.region,
            locale=config.locale,
            timeout=config.settings.request_timeout,
        )

    if args.solo_atributos:
        # Misma cautela que en `--solo-iconos`: fuera antes de tocar subastas,
        # porque `volcar()` reemplaza la tabla `precio` entera.
        con = abrir(ruta_db)
        faltan_atrib = productos_sin_atributos(con, args.atributos)
        log.info("%s productos sin categoria en esta tanda", len(faltan_atrib))
        arranque_atrib = time.monotonic()
        puestos = guardar_atributos(
            con, pedir_atributos(client, faltan_atrib, config.settings.max_workers)
        )
        log.info(
            "Listo: %s categorias de %s pedidas en %.0f s. Quedan %s.",
            puestos,
            len(faltan_atrib),
            time.monotonic() - arranque_atrib,
            len(productos_sin_atributos(con, 1_000_000)),
        )
        return EXIT_OK

    if args.solo_iconos:
        # Sale por aqui antes de tocar nada de subastas. No es un atajo de
        # comodidad: `volcar()` reemplaza la tabla `precio` entera, asi que una
        # pasada que rellenara iconos y ademas publicara dejaria la web con
        # solo los reinos que se hubieran bajado en ese momento.
        con = abrir(ruta_db)
        faltan_iconos = productos_sin_icono(con, args.iconos)
        log.info("%s productos sin icono en esta tanda", len(faltan_iconos))
        arranque_iconos = time.monotonic()
        puestos = guardar_iconos(
            con, pedir_iconos(client, faltan_iconos, config.settings.max_workers)
        )
        log.info(
            "Listo: %s iconos de %s pedidos en %.0f s. Quedan %s por rellenar.",
            puestos,
            len(faltan_iconos),
            time.monotonic() - arranque_iconos,
            len(productos_sin_icono(con, 1_000_000)),
        )
        return EXIT_OK

    realm_ids = (
        [int(r) for r in args.realms.split(",") if r.strip()]
        if args.realms
        else client.connected_realm_ids()
    )

    log.info(
        "Bajando %s reinos (suelo: %s oro)...", len(realm_ids), PRECIO_MINIMO_ORO
    )
    arranque = time.monotonic()
    resumenes, nombres_reino = descargar_reinos(
        client, config, realm_ids, PRECIO_MINIMO_ORO * COPPER_PER_GOLD
    )

    # Mismo umbral que usa `main.py` para la misma decision (ver
    # `wowalerts.config.Settings.failure_ratio_threshold`): si fallan mas
    # reinos de la cuenta, no se toca la base. Publicar solo lo que ha
    # respondido no es "publicar un poco menos" -- `volcar()` borra la tabla
    # `precio` entera y reinserta solo esos reinos, asi que los que fallan
    # desaparecen de la web hasta la pasada siguiente. Los datos de la pasada
    # anterior tienen como mucho una hora; una region a medio reemplazar es
    # peor que eso, y encima no se nota porque el proceso sigue saliendo bien.
    # "Ningun reino ha respondido" no es un caso aparte: con resumenes vacio
    # el ratio sale 1.0, muy por encima de cualquier umbral razonable.
    fallidos = len(realm_ids) - len(resumenes)
    ratio_fallos = fallidos / len(realm_ids) if realm_ids else 0.0
    if ratio_fallos > config.settings.failure_ratio_threshold:
        log.error(
            "%s de %s reinos han fallado (%.0f%%), por encima del limite "
            "del %.0f%%: no toco la base. Me quedo a proposito con la "
            "pasada anterior.",
            fallidos,
            len(realm_ids),
            ratio_fallos * 100,
            config.settings.failure_ratio_threshold * 100,
        )
        return EXIT_DEMASIADOS_FALLOS
    log.info(
        "%s de %s reinos en %.0f s",
        len(resumenes),
        len(realm_ids),
        time.monotonic() - arranque,
    )

    agregado = agregar(resumenes)
    log.info("%s productos distintos en lo bajado", len(agregado))

    con = abrir(ruta_db)

    faltan = productos_sin_nombre(con, agregado)
    log.info("%s productos sin nombre todavia", len(faltan))
    arranque_nombres = time.monotonic()
    nombres_producto, atributos_producto = pedir_datos(
        client, faltan, config.settings.max_workers
    )
    if faltan:
        log.info(
            "%s filas de nombre en %.0f s",
            len(nombres_producto),
            time.monotonic() - arranque_nombres,
        )

    generado_en = int(time.time())
    filas = poblar(con, agregado, nombres_reino, nombres_producto, generado_en)

    # Los iconos atrasados van DESPUES de publicar: si esto falla o se corta a
    # medias, el volcado de precios ya esta escrito y la web ya sirve datos
    # nuevos. Una foto que falta es un defecto cosmetico, y no vale la pena
    # arriesgar la pasada entera por ella.
    if atributos_producto:
        guardar_atributos(con, atributos_producto)

    # Las categorias atrasadas, al mismo ritmo y despues de publicar que
    # los iconos: son metadatos, y ninguno vale una pasada de precios.
    sin_atributos = (
        productos_sin_atributos(con, args.atributos) if args.atributos else []
    )
    clasificados = 0
    if sin_atributos:
        clasificados = guardar_atributos(
            con, pedir_atributos(client, sin_atributos, config.settings.max_workers)
        )
        log.info("%s categorias nuevas", clasificados)

    sin_icono = productos_sin_icono(con, args.iconos) if args.iconos else []
    puestos = 0
    if sin_icono:
        arranque_iconos = time.monotonic()
        puestos = guardar_iconos(
            con, pedir_iconos(client, sin_icono, config.settings.max_workers)
        )
        log.info(
            "%s iconos de %s pedidos en %.0f s",
            puestos,
            len(sin_icono),
            time.monotonic() - arranque_iconos,
        )

    log.info(
        "Listo: %s reinos, %s productos, %s filas de precio, %s productos con "
        "nombre nuevo, %s iconos nuevos.",
        len(nombres_reino),
        len(agregado),
        filas,
        len(faltan),
        puestos,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
