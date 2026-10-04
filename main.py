"""Vigilante de precios de la Casa de Subastas de WoW.

Escanea las subastas de todos los reinos de una region y avisa por Discord
cuando alguno de los objetos vigilados esta en compra directa por debajo del
precio que hayas fijado en config.yaml.

Uso tipico:

    py main.py --test-discord                  # comprobar el webhook
    py main.py --dry-run --realms 1305,1378    # prueba rapida, sin enviar nada
    py main.py                                 # escaneo completo real
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from wowalerts.blizzard import BlizzardAuthError, BlizzardClient, BlizzardError
from wowalerts.config import ConfigError, load_config
from wowalerts.disparo import (
    PASADAS_QUE_TIENEN_QUE_COINCIDIR,
    REAJUSTE_QUE_NO_MERECE_AVISO,
    CronJobOrg,
    DisparoError,
    conviene_mover,
    distancia,
)
from wowalerts.items import (
    ItemResolutionError,
    reglas_por_especie,
    resolve_item_ids,
)
from wowalerts.journalator import leer_resumenes, ranking
from wowalerts.misubastas import (
    MisSubastasError,
    actividad_por_maquina,
    leer_canceladas,
    leer_snapshots,
    separar_por_frescura,
)
from wowalerts.panel import build_panel, build_panel_ventas
from wowalerts.notifier import (
    DiscordError,
    DiscordNotifier,
    format_gold,
    realm_names_for,
)
from wowalerts.personajes import (
    leer_rosters,
    orden_de_personajes,
    por_nombre_de_reino,
    quien_puede_comprar,
)
from wowalerts.realms import RealmResolutionError, resolve_connected_realms
from wowalerts.scanner import scan_realms
from wowalerts.silencio import en_silencio
from wowalerts.snapshot import (
    dump_age,
    dump_is_stale,
    falta_para_el_siguiente,
)
from wowalerts.state import (
    HistorialDeVolcados,
    JsonMapCache,
    ItemIconCache,
    ItemIdCache,
    NotifiedAuctions,
    NotifiedUndercuts,
    RealmIdCache,
    SeguimientoVentas,
)
from wowalerts.undercut import find_undercuts
from wowalerts.ventas import revisar_reino

log = logging.getLogger("wowalerts")

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_TOO_MANY_FAILURES = 2

DEFAULT_STATE_DIR = Path(".state")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Avisa por Discord de chollos en la Casa de Subastas de WoW.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  py main.py --test-discord\n"
            "  py main.py --dry-run --realms 1305,1378 -v\n"
            "  py main.py\n"
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Ruta del fichero de configuracion (por defecto: config.yaml).",
    )
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help="Carpeta donde se guarda la memoria entre ejecuciones.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Escanea e imprime los chollos, pero no envia nada a Discord ni "
        "guarda el estado. Ideal para probar.",
    )
    parser.add_argument(
        "--realms",
        help="Lista de ids de reino separados por comas, para escanear solo "
        "esos en vez de toda la region. Acelera muchisimo las pruebas.",
    )
    parser.add_argument(
        "--test-discord",
        action="store_true",
        help="Envia un mensaje de prueba al webhook y termina.",
    )
    parser.add_argument(
        "--ignore-state",
        action="store_true",
        help="Avisa tambien de chollos ya notificados en pasadas anteriores.",
    )
    parser.add_argument(
        "--undercut",
        action="store_true",
        help="En vez de buscar chollos, avisa si alguien ha adelantado a tus "
        "propias subastas de los objetos vigilados. Necesita la carpeta "
        "mis_subastas, que genera sync_subastas.py en cada maquina.",
    )
    parser.add_argument(
        "--ventas",
        action="store_true",
        help="Avisa en su propio canal de las subastas tuyas que se han "
        "vendido. Se combina con --undercut para hacer las dos vigilancias "
        "con una sola descarga.",
    )
    parser.add_argument(
        "--personajes",
        default="mis_personajes",
        help="Carpeta con la lista de tus personajes, un fichero por maquina. "
        "Sirve para decir con quien entrar a por cada chollo.",
    )
    parser.add_argument(
        "--mis-subastas",
        default="mis_subastas",
        help="Carpeta con el volcado de tus subastas, un fichero por maquina "
        "(por defecto: mis_subastas).",
    )
    parser.add_argument(
        "--mis-ventas",
        default="mis_ventas",
        help="Carpeta con el resumen de lo que has vendido, un fichero por "
        "maquina (por defecto: mis_ventas). Lo genera sync_subastas.py leyendo "
        "el addon Journalator, y es lo que alimenta el panel de ventas.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra el detalle de cada subasta vista (util para revisar los "
        "bonus ids cuando algo no cuadra).",
    )
    return parser


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )


def parse_realm_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            raise ConfigError(
                f"--realms solo admite numeros separados por comas; "
                f"{chunk!r} no lo es."
            )
        ids.append(int(chunk))
    if not ids:
        raise ConfigError("--realms no contiene ningun id de reino.")
    return sorted(set(ids))


def print_deals(deals, realm_names, compradores=None) -> None:
    """Vuelca los chollos por consola (lo que se enviaria a Discord)."""
    for deal in deals:
        if deal.sin_ilvl:
            ilvl = "sin ilvl"
        else:
            ilvl = f"ilvl {deal.ilvl}" if deal.ilvl_confirmed else "ilvl SIN CONFIRMAR"
        realm = realm_names.get(deal.realm_id, f"Reino {deal.realm_id}")
        quien = (compradores or {}).get(deal.realm_id)
        log.info(
            "  %s | %s g (%s, limite %s g, -%.0f%%) | %s%s",
            deal.item_name,
            format_gold(deal.price_gold),
            ilvl,
            format_gold(deal.threshold_gold),
            deal.discount_pct,
            realm,
            f" | ir con: {quien}" if quien else "",
        )


def print_ventas(ventas) -> None:
    """Vuelca las ventas por consola (lo que se enviaria a Discord)."""
    for venta in ventas:
        cuenta = (
            f"WoW {venta.subasta.account}"
            if venta.subasta.account is not None
            else venta.subasta.realm
        )
        log.info(
            "  %s | %s g netos | %s (%s)",
            venta.subasta.item_name,
            format_gold(venta.neto_gold),
            venta.subasta.character,
            cuenta,
        )


def resolve_icons(client, cache, deals) -> dict[int, str]:
    """Miniatura de cada objeto con chollo, pidiendola solo la primera vez.

    Los iconos no cambian, asi que se cachean. Un fallo aqui no impide el aviso:
    simplemente sale sin miniatura.
    """
    urls: dict[int, str] = {}
    for item_id in dict.fromkeys(deal.item_id for deal in deals):
        url = cache.get(item_id) or client.item_icon_url(item_id)
        if url:
            urls[item_id] = url
            cache.set(item_id, url)
    return urls


def compradores_para(roster_path: str, realm_names) -> dict[int, str]:
    """Con que personaje tuyo se puede comprar un chollo de cada reino.

    No cuesta ni una peticion: el nombre de un connected realm ya trae dentro
    todos los reinos que comparten casa de subastas, y el escaneo lo pide de
    todas formas para el aviso.
    """
    roster = leer_rosters(roster_path)
    if not roster:
        return {}

    indice = por_nombre_de_reino(roster)
    return {
        realm_id: quien_puede_comprar(indice, nombre)
        for realm_id, nombre in realm_names.items()
    }


def agrupar_por_reino(mis_subastas, realm_ids_por_reino) -> dict[int, list]:
    """Agrupa tus subastas por connected realm.

    Varios reinos comparten connected realm, asi que agrupar por ahi y no por
    nombre evita descargar dos veces el mismo volcado.
    """
    grupos: dict[int, list] = {}
    for subasta in mis_subastas:
        realm_id = realm_ids_por_reino.get(subasta.realm)
        if realm_id is None:
            log.warning(
                "Omito las subastas de %s: no se a que reino conectado pertenece.",
                subasta.realm,
            )
            continue
        grupos.setdefault(realm_id, []).append(subasta)
    return grupos


def nombres_vigilados(client, cache: JsonMapCache, item_ids, species_ids=()) -> set[str]:
    """Como se llama cada cosa que vigilas, en todos los idiomas.

    Journalator apunta el nombre tal y como lo ve tu cliente y no guarda el id,
    asi que comparar nombres es la unica forma de saber si una venta suya es de
    algo que rastreamos. Se piden todos los idiomas de una vez porque cuesta lo
    mismo que pedir uno, y asi da igual en que idioma juegues.

    Las mascotas van aparte: en la casa de subastas todas son el mismo objeto
    "jaula" y solo las distingue el id de especie, pero en el correo llegan con
    su propio nombre, que es justo el que hay que reconocer.
    """
    nombres: set[str] = set()

    def recoge(clave: str, pedir) -> None:
        guardados = cache.get(clave)
        if guardados is None:
            guardados = sorted(set(pedir().values()))
            if not guardados:
                # Sin nombre solo se pierden sus ventas en el panel. No se
                # cachea el vacio: asi la pasada siguiente lo vuelve a intentar.
                log.warning("No he podido leer el nombre de %s.", clave)
                return
            cache.set(clave, guardados)
        nombres.update(guardados)

    for item_id in dict.fromkeys(item_ids):
        recoge(f"item:{item_id}", lambda i=item_id: client.item_names(i))
    for species_id in dict.fromkeys(species_ids):
        recoge(f"pet:{species_id}", lambda s=species_id: client.pet_species_names(s))

    return nombres


def actualizar_panel_ventas(
    client, notifier, state_dir: Path, mis_ventas_path: str, item_ids, species_ids=()
) -> None:
    """Reescribe el mensaje fijado con los reinos donde mas vendes.

    Un aviso suelto dice que has vendido algo; esto dice DONDE vendes, que es lo
    que decide adonde merece la pena volver a llevar genero. Las cifras salen de
    Journalator, no de lo que detecta el vigilante: el addon apunta la factura
    exacta del correo y lleva meses de historial, mientras que aqui solo se ve
    una subasta desaparecer y hay que deducir por cuanto se fue.
    """
    cache = JsonMapCache(state_dir / "nombres_objetos.json", "nombres")
    nombres = nombres_vigilados(client, cache, item_ids, species_ids)
    cache.save()

    filas, totales = ranking(leer_resumenes(mis_ventas_path), nombres)

    memoria = JsonMapCache(state_dir / "panel_ventas.json", "panel")
    anterior = memoria.get("message_id")
    nuevo = notifier.upsert_panel(
        build_panel_ventas(filas, totales, datetime.now(timezone.utc)),
        anterior,
    )

    if nuevo and nuevo != anterior:
        memoria.set("message_id", nuevo)
        memoria.save()


def actualizar_panel(
    notifier, state_dir: Path, mis_subastas, undercuts, snapshot_at, caducados=()
):
    """Reescribe el mensaje fijado con el estado de todas tus subastas.

    El id del mensaje se guarda entre pasadas: sin el habria que publicar uno
    nuevo cada hora, que es exactamente lo que el panel evita.
    """
    memoria = JsonMapCache(state_dir / "panel.json", "panel")
    anterior = memoria.get("message_id")

    nuevo = notifier.upsert_panel(
        build_panel(mis_subastas, undercuts, snapshot_at, caducados), anterior
    )
    if not nuevo:
        return None

    # El enlace se calcula una sola vez y se guarda: el panel se edita en su
    # sitio y nunca sube al final del canal, asi que sin un enlace directo hay
    # que rebuscarlo a mano cada vez.
    enlace = memoria.get("url") if nuevo == anterior else None
    if not enlace:
        enlace = notifier.panel_url(nuevo)

    if nuevo != anterior or enlace != memoria.get("url"):
        memoria.set("message_id", nuevo)
        memoria.set("url", enlace)
        memoria.save()

    if nuevo != anterior:
        log.info("📊 Panel publicado: %s", enlace or "(sin enlace)")
    else:
        log.info("📊 Panel actualizado: %s", enlace or "(sin enlace)")
    return enlace


def caducados_por_avisar(ahora: list[str], ya_avisados: list[str]) -> list[str]:
    """Los personajes caducados de los que todavia no se ha avisado.

    Solo los nuevos: el estado dura hasta que los visitas, y cantarlo cada hora
    seria una alarma que se aprende a ignorar, que es peor que no tenerla.
    """
    return sorted(set(ahora) - set(ya_avisados))


def run_mis_subastas(
    client,
    config,
    rules_by_item_id,
    notifier_undercut,
    notifier_ventas,
    state_dir: Path,
    mis_subastas_path: str,
    roster_path: str,
    mis_ventas_path: str,
    *,
    hacer_undercut: bool,
    hacer_ventas: bool,
    dry_run: bool,
    ignore_state: bool,
    callado: bool = False,
) -> int:
    """Una pasada de vigilancia sobre tus propias subastas.

    Undercuts y ventas comparten la descarga: son las mismas subastas de los
    mismos reinos, leidas del mismo volcado. Cada vigilancia manda su aviso a
    su canal.
    """
    todas = leer_snapshots(mis_subastas_path)

    # Un volcado mas viejo que tu duracion de listado no puede estar describiendo
    # nada vivo: todo lo que contaba ha caducado ya. Seguir creyendolo es lo que
    # el 2026-09-02 canto como vendidas dos subastas que solo se habian
    # relistado, porque la Steam Deck llevaba 16 horas sin exportar y seguia
    # afirmando los ids del dia anterior.
    todas, de_volcado_viejo = separar_por_frescura(
        todas, datetime.now(timezone.utc), config.settings.listing_hours
    )
    if de_volcado_viejo:
        # Se dice "han caducado" y no "no puedo leerlas", que era lo que ponia
        # antes, porque son cosas muy distintas y la segunda suena a averia. Si
        # el addon exporto hace mas horas de las que dura un listado, todo lo que
        # decia ya ha vencido: esta en el buzon, no en la casa de subastas.
        # Refrescar el volcado no lo devuelve, hay que volver a listarlo.
        personajes = sorted({s.character for s in de_volcado_viejo})
        log.warning(
            "⚠️  %s subasta(s) de %s personaje(s) tienen datos de hace mas de "
            "%s h, que es lo que duran tus listados. Las que Blizzard siga "
            "listando se vigilan igual; el resto ya habran caducado y estaran "
            "en su buzon. Si quieres seguir vendiendo ahi, entra y vuelve a "
            "listarlas: %s%s",
            len(de_volcado_viejo),
            len(personajes),
            config.settings.listing_hours,
            ", ".join(personajes[:8]),
            "..." if len(personajes) > 8 else "",
        )

    # Solo interesan los objetos que vigila config.yaml: el resto de lo que
    # tengas puesto (monturas, mochilas, decoracion) no es el negocio.
    mis_subastas = [s for s in todas if s.item_id in rules_by_item_id]
    # Las de volcado viejo se sueltan del seguimiento sin veredicto: no se puede
    # afirmar si se vendieron, caducaron o las relistaste.
    olvidar = {s.auction_id for s in de_volcado_viejo}

    seguimiento = SeguimientoVentas(state_dir / "ventas.json")
    # Lo que queda por resolver no depende de que el addon este al dia: las
    # subastas seguidas las avala el volcado de Blizzard. El 2026-09-11, tras
    # doce horas sin jugar, todo lo del addon era viejo, la pasada se despedia
    # aqui sin mirar el seguimiento y las ventas de la noche no salieron hasta
    # volver a entrar al juego.
    pendientes = seguimiento.reinos_con_seguimiento() if hacer_ventas else set()

    if not mis_subastas and not pendientes:
        log.info(
            "😴 De tus %s subasta(s) conocidas, ninguna es de un objeto vigilado. "
            "Nada que comprobar.",
            len(todas),
        )
        # El panel se refresca igual: lo que cuenta es lo que ya vendiste, no lo
        # que tengas puesto ahora mismo.
        if hacer_ventas and not dry_run and notifier_ventas:
            actualizar_panel_ventas(
                client,
                notifier_ventas,
                state_dir,
                mis_ventas_path,
                rules_by_item_id,
                reglas_por_especie(config),
            )
        return EXIT_OK

    if mis_subastas:
        log.info(
            "📋 %s de tus %s subastas son de objetos vigilados, en %s reino(s).",
            len(mis_subastas),
            len(todas),
            len({s.realm for s in mis_subastas}),
        )
    else:
        log.info(
            "🔎 Nada fresco del addon, pero quedan subastas por resolver en %s "
            "reino(s): las sigo con lo que dice Blizzard.",
            len(pendientes),
        )
        # Sin subastas tuyas con las que comparar no hay undercuts que buscar,
        # y asi el panel de undercuts se queda como estaba en vez de vaciarse.
        hacer_undercut = False

    realm_cache = RealmIdCache(state_dir / "realm_ids.json")
    realm_ids_por_reino = resolve_connected_realms(
        client, realm_cache, (s.realm for s in mis_subastas), strict=False
    )
    if not dry_run:
        realm_cache.save()

    grupos = agrupar_por_reino(mis_subastas, realm_ids_por_reino)
    # Sin subastas frescas no hay reinos que resolver: los del seguimiento ya
    # vienen con su id y se anaden mas abajo.
    if mis_subastas and not grupos:
        raise RealmResolutionError(
            "No he podido resolver ninguno de tus reinos. Sin eso no puedo "
            "descargar sus subastas."
        )

    notified = NotifiedUndercuts(
        state_dir / "undercuts.json", config.settings.state_retention_runs
    )
    # Objetos de los que no quieres avisos de undercut. Se calculan igual que el
    # resto: las ventas necesitan saber si a una subasta la habian adelantado
    # para no confundir un reposteo tuyo con una venta. Lo unico que cambia es
    # que no se envian.
    sin_undercut = {
        item_id
        for item_id, rule in rules_by_item_id.items()
        if not rule.avisar_undercut
    }
    # Los avisos salen en el orden en que tienes los personajes, no en el que
    # toque descargar los reinos: asi siempre miras al mismo sitio.
    orden = orden_de_personajes(leer_rosters(roster_path), config.orden_personajes)
    # Lo que el addon ha visto que cancelaste: nada de eso es una venta.
    canceladas = leer_canceladas(mis_subastas_path) if hacer_ventas else set()
    if canceladas:
        log.info("🚫 %s cancelacion(es) conocidas del addon.", len(canceladas))
    # La ultima senal de vida de cada maquina. Es lo que dice si estabas jugando
    # cuando una subasta desaparecio, y por tanto si pudiste cancelarla sin que
    # me haya llegado todavia.
    actividad = actividad_por_maquina(mis_subastas_path) if hacer_ventas else {}

    if hacer_ventas:
        # Un reino donde queda algo por resolver se mira aunque el volcado del
        # addon ya no mencione ninguna subasta tuya alli. Si no, al vender la
        # ultima de un reino y hacer /reload, esa venta no se detectaria nunca.
        for realm_id in seguimiento.reinos_con_seguimiento():
            grupos.setdefault(realm_id, [])

    todos: list = []
    ventas: list = []
    snapshot_at = None
    # Cuantas subastas conoce el addon de cada personaje y cuantas siguen vivas.
    # Un personaje con todas muertas es uno cuyos datos son de antes de que las
    # repostearas: contra ids muertos no se detecta nada, y en silencio.
    conocidas: dict[str, int] = {}
    vivas_por_pj: dict[str, int] = {}
    for realm_id, mias in grupos.items():
        try:
            snapshot = client.auctions(realm_id)
        except BlizzardError as exc:
            # El reino no se evalua esta hora. Es importante no tocar su
            # seguimiento: si diera por desaparecidas sus subastas, una caida de
            # Blizzard se convertiria en una rafaga de ventas inventadas.
            log.warning("Reino %s: %s", realm_id, exc)
            continue

        if snapshot.taken_at and (snapshot_at is None or snapshot.taken_at > snapshot_at):
            snapshot_at = snapshot.taken_at

        vivos = {a.get("id") for a in snapshot.auctions}
        for mia in mias:
            conocidas[mia.character] = conocidas.get(mia.character, 0) + 1
            if mia.auction_id in vivos:
                vivas_por_pj[mia.character] = vivas_por_pj.get(mia.character, 0) + 1

        # Se calculan siempre que se pida cualquiera de las dos vigilancias:
        # las ventas los necesitan para no confundir un reposteo tuyo con una
        # venta, aunque no se vayan a avisar.
        del_reino_undercuts = find_undercuts(
            snapshot.auctions, mias, config.bonus_ilvl_map, realm_id
        )
        if hacer_undercut:
            todos.extend(
                u for u in del_reino_undercuts if u.mine.item_id not in sin_undercut
            )

        if hacer_ventas:
            # Sin Last-Modified se usa el reloj, que con el cron a y 33 queda a
            # dos minutos del volcado real: buena aproximacion.
            dump_at = snapshot.taken_at or datetime.now(timezone.utc)
            del_reino, seguidas, ultimo = revisar_reino(
                seguimiento.del_reino(realm_id),
                mias,
                snapshot.auctions,
                realm_id,
                dump_at,
                seguimiento.anterior(realm_id),
                config.settings.listing_hours,
                config.settings.ah_cut_pct,
                {u.mine.auction_id for u in del_reino_undercuts},
                canceladas,
                not callado,
                olvidar=olvidar,
                actividad=actividad,
                bonus_ilvl_map=config.bonus_ilvl_map,
            )
            ventas.extend(del_reino)
            seguimiento.actualizar_reino(realm_id, seguidas, ultimo)

    if snapshot_at:
        edad = (datetime.now(timezone.utc) - snapshot_at).total_seconds() / 60
        log.info(
            "🕒 Datos del volcado de las %s UTC (hace %.0f min).",
            snapshot_at.strftime("%H:%M"),
            edad,
        )

    caducados = [pj for pj, n in conocidas.items() if n and not vivas_por_pj.get(pj)]
    if caducados:
        log.warning(
            "⚠️  %s personaje(s) sin datos frescos (ninguna de sus subastas "
            "conocidas sigue viva): %s. Entra con ellos, abre la Casa de "
            "Subastas y haz /reload.",
            len(caducados),
            ", ".join(sorted(caducados)[:12]),
        )

    # Un personaje caducado deja de vigilarse entero: ni undercuts ni ventas.
    # Eso es demasiado grave para dejarlo solo en el panel y en el log, asi que
    # se avisa por Discord la primera vez que aparece.
    memoria_caducados = JsonMapCache(state_dir / "panel.json", "panel")
    ya_avisados = memoria_caducados.get("caducados_avisados") or []
    nuevos = caducados_por_avisar(caducados, ya_avisados)
    if nuevos and notifier_undercut and not dry_run and not callado:
        notifier_undercut.send_warning(
            "Personajes que he dejado de vigilar",
            f"De estos {len(nuevos)} personaje(s) no me sirve lo que tengo "
            "apuntado: ninguna de sus subastas conocidas sigue viva, asi que "
            "**no puedo avisarte ni de undercuts ni de ventas suyas**.\n\n"
            + ", ".join(nuevos)
            + "\n\nEntra con cada uno, abre la Casa de Subastas, espera unos "
            "segundos y haz `/reload`.",
        )
        memoria_caducados.set("caducados_avisados", sorted(caducados))
        memoria_caducados.save()
    elif mis_subastas and set(caducados) != set(ya_avisados) and not dry_run:
        # Con mis_subastas vacio no se ha podido juzgar a nadie, y guardar la
        # lista vacia volveria a cantar por Discord a todos la proxima vez.
        # Se guarda igualmente para que arreglar uno no reabra el aviso de los
        # demas la proxima vez.
        memoria_caducados.set("caducados_avisados", sorted(caducados))
        memoria_caducados.save()

    if hacer_undercut:
        # El panel se reescribe siempre, tambien cuando no hay novedades: su
        # gracia es decir como estas, y "todo primero" es una respuesta tan util
        # como una lista de cosas que atender.
        panel_url = None
        if notifier_undercut and not dry_run:
            panel_url = actualizar_panel(
                notifier_undercut,
                state_dir,
                mis_subastas,
                todos,
                snapshot_at,
                caducados,
            )

        frescos = todos if ignore_state else notified.filter_new(todos)
        # Los ya avisados no se tiran ni van marcados como repetidos: se
        # acumulan con los nuevos en la tarjeta de su personaje, porque lo
        # accionable es todo lo que sigue adelantado, no cuando se dijo.
        claves_frescas = {
            (u.realm_id, u.mine.auction_id, u.rival_auction_id) for u in frescos
        }
        ya_avisados = [
            u
            for u in todos
            if (u.realm_id, u.mine.auction_id, u.rival_auction_id)
            not in claves_frescas
        ]
        if ya_avisados:
            log.info(
                "🔁 %s undercut(s) ya avisados, van con los nuevos.",
                len(ya_avisados),
            )

        if not frescos:
            log.info("😌 Nadie nuevo te ha adelantado.")
        else:
            log.info("⚔️ Te han adelantado en %s subasta(s):", len(frescos))
            for undercut in frescos:
                cuenta = (
                    f"WoW {undercut.mine.account}"
                    if undercut.mine.account is not None
                    else undercut.mine.realm
                )
                log.info(
                    "  %s | tuya %s g vs %s g | %s (%s)",
                    undercut.mine.item_name,
                    format_gold(undercut.my_price_gold),
                    format_gold(undercut.rival_price_gold),
                    undercut.mine.character,
                    cuenta,
                )

            if callado:
                # Sin marcarlos como avisados: al acabar el silencio se envia
                # lo que siga adelantado, que es lo unico accionable.
                log.info("🔕 En silencio: no envio estos avisos todavia.")
            elif not dry_run:

                def marcar(undercuts) -> None:
                    for undercut in undercuts:
                        notified.mark(
                            notified.key(
                                undercut.realm_id,
                                undercut.mine.auction_id,
                                undercut.rival_auction_id,
                            )
                        )

                try:
                    enviados = notifier_undercut.send_undercuts(
                        frescos, ya_avisados, panel_url, orden
                    )
                except DiscordError as exc:
                    # Los personajes cuyo mensaje si llego no se repiten.
                    marcar(exc.entregados)
                    notified.save()
                    raise
                log.info("📨 Enviados a Discord %s aviso(s).", len(enviados))
                # Solo se marcan los que han salido de verdad, igual que con los
                # chollos.
                marcar(enviados)
                # Se guarda ya, no al final de la pasada: las ventas van por
                # otro webhook, y si ese fallara la excepcion subiria antes de
                # llegar al final. Lo que ya ha salido constaria como no
                # avisado y la pasada siguiente te lo volveria a cantar.
                notified.save()

    if hacer_ventas:
        if not ventas:
            log.info("💤 No se te ha vendido nada esta hora.")
        else:
            total = format_gold(sum(v.neto_gold for v in ventas))
            log.info("💰 %s venta(s), %s g netos:", len(ventas), total)
            print_ventas(ventas)

            if not dry_run:
                enviadas = notifier_ventas.send_ventas(ventas, orden)
                log.info("📨 Enviadas a Discord %s venta(s).", len(enviadas))

    # Fuera del "else": el panel no depende de lo que se haya vendido esta hora,
    # sino de todo lo que Journalator lleva apuntado.
    if hacer_ventas and not dry_run and notifier_ventas:
        actualizar_panel_ventas(
            client,
            notifier_ventas,
            state_dir,
            mis_ventas_path,
            rules_by_item_id,
            reglas_por_especie(config),
        )

    if dry_run:
        log.info("🧪 --dry-run: no envio nada a Discord ni guardo el estado.")
        return EXIT_OK

    if hacer_undercut:
        notified.save()
    # Se guarda DESPUES de enviar: si Discord falla, la excepcion sube y el
    # seguimiento se queda como estaba, asi que la pasada siguiente vuelve a
    # detectar esas ventas en vez de perderlas.
    if hacer_ventas:
        seguimiento.save()
    return EXIT_OK


# Cuantas pasadas seguidas se aceptan esperando al volcado nuevo antes de tirar
# la toalla. Esperar sale a cuenta mientras es pasajero, hasta que el disparo se
# recoloque; si no se recolocara nunca, esperar cada hora se comeria la cuota de
# GitHub Actions en pocos dias.
ESPERAS_SEGUIDAS_MAXIMAS = 4


def es_pasada_desatendida() -> bool:
    """Si corre sola, sin nadie mirando.

    Decide si merece la pena esperar unos minutos a que salga el volcado nuevo.
    Lanzada a mano no: esperar diez minutos mientras pruebas algo no lo quiere
    nadie. Cualquier pasada en Actions si, la dispare quien la dispare.
    """
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"


def es_pasada_programada() -> bool:
    """Si nos ha lanzado el cron externo, el unico disparo puntual que hay.

    Solo en esas pasadas significa algo la hora de arranque, que es de donde
    sale el desfase del disparo. En una lanzada a mano la eliges tu, y en las
    que dispara el 'schedule' de GitHub la elige su cola: esos eventos se
    retrasan entre 20 y 40 minutos, asi que la hora de arranque no dice nada del
    cron.

    Lo aprendimos por las malas el 2026-09-02: una pasada de 'schedule'
    programada a y 25 arranco a y 49, se midio un descuelgue de 26 minutos y se
    aviso de que el disparo estaba mal cuando estaba perfectamente puesto. El
    minuto al que se movia salia bien de casualidad, porque se calcula desde la
    hora de publicacion y no desde la de arranque.
    """
    return (
        os.getenv("GITHUB_ACTIONS", "").lower() == "true"
        and os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
    )


def mantener_disparo_alineado(
    arranque: datetime,
    publicado: datetime,
    historial: HistorialDeVolcados,
    notifier,
    *,
    dry_run: bool,
    callado: bool = False,
) -> None:
    """Vigila que el cron siga disparando justo despues del volcado.

    Blizzard mueve la hora de publicacion cada pocas semanas sin avisar: el
    2026-08-31 el volcado salia a las :31:22 y el 2026-09-02 a las :23:30.
    Cuando pasa no se rompe nada, solo llegan los avisos mas tarde, que es la
    clase de deterioro del que no te enteras nunca.

    Con las credenciales de cron-job.org puestas, la pasada lo mueve sola. Sin
    ellas avisa por Discord, porque enterrarlo en el log de Actions es lo mismo
    que no decirlo.

    En silencio se mide y se mueve igual: cambiar el minuto del cron no despierta
    a nadie, y esperar al final de la ventana costaria toda la manana con los
    avisos desalineados. Lo unico que se aplaza es contarlo, que se recoge en la
    primera pasada despierta.
    """
    # Un volcado de hace mas de una hora no habla del cron, sino de que Blizzard
    # iba tarde, y eso ya tiene su propio aviso. Ojo: al reves si cuenta, porque
    # un `publicado` posterior al arranque significa que disparamos antes de que
    # publicaran y tuvimos que esperar.
    if (arranque - publicado) >= timedelta(hours=1):
        return

    historial.apunta(publicado.minute)
    objetivo = conviene_mover(historial.minutos, arranque.minute)
    if objetivo is None:
        return

    razon = (
        f"Blizzard lleva {PASADAS_QUE_TIENEN_QUE_COINCIDIR} pasadas publicando a "
        f"y {publicado.minute:02d} y el disparo esta en y {arranque.minute:02d}."
    )
    credenciales = (
        os.getenv("CRONJOB_API_KEY", ""),
        os.getenv("CRONJOB_JOB_ID", ""),
    )

    if dry_run or not all(credenciales):
        log.warning("💡 %s Conviene moverlo al minuto %02d.", razon, objetivo)
        if not dry_run:
            contar(
                notifier,
                historial,
                "El disparo se ha desalineado",
                f"{razon}\n\nEntra en cron-job.org y pon el disparo en el minuto "
                f"{objetivo:02d}: tendras los avisos antes.",
                callado=callado,
            )
        # Se olvida lo medido tambien al avisar, para no repetir el aviso cada
        # hora hasta que lo cambies: vuelve a medir y reincide en tres pasadas.
        historial.olvida()
        return

    try:
        CronJobOrg(*credenciales).mover_a(objetivo)
    except DisparoError as exc:
        # Sin olvidar el historial: si ha sido un fallo pasajero, la pasada
        # siguiente lo vuelve a intentar.
        log.error("❌ %s", exc)
        return

    log.warning("🔧 %s Lo he movido al minuto %02d.", razon, objetivo)
    historial.olvida()

    # Un minuto arriba o abajo es afinar, no arreglar una averia. Se hace igual
    # --es lo que mantiene el aviso lo mas rapido posible-- pero no merece una
    # notificacion: llenaria Discord de mensajes que no piden nada de ti.
    if distancia(objetivo, arranque.minute) <= REAJUSTE_QUE_NO_MERECE_AVISO:
        log.info("Reajuste pequeno: no te doy la lata por Discord.")
        return

    contar(
        notifier,
        historial,
        "He movido el disparo",
        f"{razon}\n\nLo he cambiado al minuto {objetivo:02d} en cron-job.org "
        f"para que los avisos vuelvan a llegarte nada mas publicarse el volcado.",
        callado=callado,
    )


def contar(
    notifier,
    historial: HistorialDeVolcados,
    titulo: str,
    texto: str,
    *,
    callado: bool,
) -> None:
    """Manda el aviso, o lo guarda para cuando se acabe el silencio."""
    if callado:
        log.info("🔕 En silencio: dejo el aviso para cuando acabe la ventana.")
        historial.deja_aviso(titulo, texto)
        return
    avisar_por_discord(notifier, titulo, texto)


def avisar_por_discord(notifier, titulo: str, texto: str) -> None:
    """Manda un aviso de estado, sin dejar que un fallo de Discord tumbe nada."""
    if not notifier:
        return
    try:
        notifier.send_warning(titulo, texto)
    except DiscordError as exc:
        log.error("Ademas, no he podido avisar por Discord: %s", exc)


def esperar_volcado_nuevo(
    client: BlizzardClient,
    realm_ids: list[int],
    conocido: datetime,
    settings,
    segundos: int,
) -> bool:
    """Vigila un reino hasta que Blizzard publique un volcado posterior.

    Antes esto era un `sleep` a ciegas seguido de un reescaneo completo de los
    92 reinos: casi medio giga de descarga para averiguar una fecha, y encima a
    destiempo, porque si el volcado salia recien empezada la siesta no nos
    enterabamos hasta dos minutos despues.

    Blizzard regenera toda la region a la vez, asi que basta preguntarle la hora
    a un reino cualquiera, y preguntarla sale por 0,4 s porque no hay que bajar
    el cuerpo de la respuesta. Eso permite mirar cada pocos segundos y volver en
    cuanto aparece, dentro del mismo presupuesto de espera de antes.

    Devuelve True si salio el volcado nuevo, y False si se agoto la espera.
    """
    if not realm_ids:
        return False

    reloj = realm_ids[0]
    # Se cuenta en vueltas y no contra el reloj para que la espera sea la misma
    # mirando el log que corriendo los tests, donde el reloj va fingido.
    espera = settings.dump_poll_seconds
    vueltas = max(1, -(-segundos // espera))
    for _ in range(vueltas):
        time.sleep(espera)
        try:
            publicado = client.auction_dump_time(reloj)
        except BlizzardError as exc:
            # Un fallo suelto sondeando no es motivo para rendirse: se reintenta
            # en la vuelta siguiente, que cuesta cuatro decimas.
            log.debug("El sondeo del volcado ha fallado: %s", exc)
            continue
        if publicado and publicado > conocido:
            log.info(
                "✅ Ya esta: Blizzard ha publicado el volcado de las %s UTC. "
                "Reescaneo.",
                publicado.strftime("%H:%M"),
            )
            return True
    return False


def run(args: argparse.Namespace) -> int:
    load_dotenv()

    # Cuando arranco, para poder medir despues cuanto tarde en enterarme de un
    # volcado desde que Blizzard lo publico.
    arranque = datetime.now(timezone.utc)

    config = load_config(args.config)

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    # Cada vigilancia va a su canal: son avisos de naturaleza distinta y
    # mezclarlos hace que se pierdan unos entre otros. Si no hay canal propio
    # configurado, se usa el de siempre.
    undercut_url = os.getenv("DISCORD_UNDERCUT_WEBHOOK_URL", "") or webhook_url
    ventas_url = os.getenv("DISCORD_VENTAS_WEBHOOK_URL", "") or webhook_url

    notifier = DiscordNotifier(webhook_url) if webhook_url else None
    notifier_undercut = DiscordNotifier(undercut_url) if undercut_url else None
    notifier_ventas = DiscordNotifier(ventas_url) if ventas_url else None

    if args.test_discord:
        # Se prueba el canal de la vigilancia que se haya pedido.
        prueba = notifier
        if args.ventas:
            prueba = notifier_ventas
        elif args.undercut:
            prueba = notifier_undercut
        if prueba is None:
            raise DiscordError(
                "Falta DISCORD_WEBHOOK_URL, asi que no hay nada que probar.\n"
                "Copia .env.example a .env y rellenalo."
            )
        prueba.send_test()
        log.info("✅ Mensaje de prueba enviado. Miralo en Discord.")
        return EXIT_OK

    # La guarda mira el canal de la vigilancia pedida, no siempre el general:
    # con --ventas y solo DISCORD_VENTAS_WEBHOOK_URL puesto, hay donde escribir.
    if args.undercut or args.ventas:
        hacen_falta = []
        if args.undercut:
            hacen_falta.append(notifier_undercut)
        if args.ventas:
            hacen_falta.append(notifier_ventas)
    else:
        hacen_falta = [notifier]
    if not args.dry_run and any(n is None for n in hacen_falta):
        raise DiscordError(
            "Falta DISCORD_WEBHOOK_URL. Copia .env.example a .env y rellenalo, "
            "o usa --dry-run si solo quieres ver los resultados por consola."
        )

    client = BlizzardClient(
        client_id=os.getenv("BLIZZARD_CLIENT_ID", ""),
        client_secret=os.getenv("BLIZZARD_CLIENT_SECRET", ""),
        region=config.region,
        locale=config.locale,
        timeout=config.settings.request_timeout,
    )

    # El silencio se calcula una vez por pasada: se calla el ENVIO, no la
    # deteccion. Las pasadas siguen corriendo y el estado sigue actualizandose,
    # que es lo que necesita el seguimiento de ventas para no perder el hilo.
    ajustes = config.settings
    callado = en_silencio(
        datetime.now(timezone.utc),
        ajustes.silencio_desde,
        ajustes.silencio_hasta,
        ajustes.zona_horaria,
    )
    if callado:
        log.info(
            "🔕 Silencio de %02d:00 a %02d:00 (%s): sigo vigilando, pero no "
            "envio nada hasta que acabe.",
            ajustes.silencio_desde,
            ajustes.silencio_hasta,
            ajustes.zona_horaria,
        )
    # El interruptor de la app es un silencio sin hora de fin: mismo efecto, y
    # por eso el mismo camino. Lo callado no se marca como avisado y sale al
    # reanudar si sigue vivo.
    if ajustes.avisos_pausados:
        callado = True
        log.info(
            "⏸️ Avisos pausados desde la app: sigo vigilando, pero no envio "
            "nada hasta que los reanudes."
        )

    state_dir = Path(args.state_dir)
    item_cache = ItemIdCache(state_dir / "item_ids.json")
    icon_cache = ItemIconCache(state_dir / "item_icons.json")
    notified = NotifiedAuctions(
        state_dir / "notified.json", config.settings.state_retention_runs
    )

    log.info("🔍 Identificando los %s objetos vigilados...", len(config.items))
    rules_by_item_id = resolve_item_ids(client, config, item_cache)
    rules_by_species = reglas_por_especie(config)
    if not args.dry_run:
        item_cache.save()

    if args.undercut or args.ventas:
        return run_mis_subastas(
            client,
            config,
            rules_by_item_id,
            notifier_undercut,
            notifier_ventas,
            state_dir,
            args.mis_subastas,
            args.personajes,
            args.mis_ventas,
            hacer_undercut=args.undercut,
            hacer_ventas=args.ventas,
            dry_run=args.dry_run,
            ignore_state=args.ignore_state,
            callado=callado,
        )

    if args.realms:
        realm_ids = parse_realm_ids(args.realms)
        log.info("🎯 Escaneando %s reino(s) indicados a mano...", len(realm_ids))
    else:
        realm_ids = client.connected_realm_ids()
        log.info("🚀 Escaneando los %s reinos de %s...", len(realm_ids), config.region.upper())

    settings = config.settings
    intentos = settings.stale_retries
    historial = HistorialDeVolcados(state_dir / "volcados.json")

    while True:
        result = scan_once(
            client,
            config,
            realm_ids,
            rules_by_item_id,
            rules_by_species,
            notified,
            icon_cache,
            notifier,
            args.personajes,
            dry_run=args.dry_run,
            ignore_state=args.ignore_state,
            callado=callado,
        )

        ahora = datetime.now(timezone.utc)
        tarde = dump_is_stale(result.snapshot_at, ahora, settings.max_dump_age_minutes)

        # El otro motivo para esperar: el volcado que tenemos delante esta a
        # punto de caducar. Pasa cuando el disparo se queda justo por delante de
        # la publicacion, y entonces cada pasada procesaria el de la hora
        # anterior. Un chollo de hace 54 minutos ya no es un chollo.
        falta = (
            falta_para_el_siguiente(result.snapshot_at, ahora)
            if result.snapshot_at
            else None
        )
        caduca_ya = (
            not tarde
            and falta is not None
            # Sin cota inferior a proposito: un `falta` negativo significa que
            # el volcado ya deberia haber salido, que es justo cuando hay que
            # esperarlo. Con "0 < falta" quedaba un hueco entre los 60 y los 61
            # minutos de antiguedad --ni retrasado ni inminente-- por el que se
            # colaban datos de hace una hora. Se ve disparando a y 24 con
            # publicacion a y 23:30 el dia que Blizzard llega tarde.
            and falta <= settings.espera_maxima_minutos
            # Solo sin nadie mirando: esperar diez minutos mientras pruebas
            # algo a mano no lo quiere nadie.
            and es_pasada_desatendida()
        )

        # El contador solo se reinicia cuando el volcado llega sano, no cuando
        # dejamos de esperar por el tope: si no, se esperaria cuatro de cada
        # cinco pasadas para siempre, que es justo lo que el tope evita.
        if not caduca_ya:
            historial.reinicia_esperas()

        inminente = caduca_ya
        if caduca_ya and historial.esperas_seguidas >= ESPERAS_SEGUIDAS_MAXIMAS:
            # Esperar sale a cuenta mientras es pasajero, hasta que el disparo se
            # recoloque. Si llevamos tantas pasadas asi es que no se ha
            # recolocado --la clave de cron-job.org caducada, por ejemplo-- y
            # seguir esperando cada hora se comeria la cuota de Actions.
            log.warning(
                "⚠️  Llevo %s pasadas esperando al volcado y el disparo sigue sin "
                "recolocarse. Dejo de esperar para no gastar horas de Actions: "
                "los avisos saldran con retraso hasta que muevas el cron.",
                historial.esperas_seguidas,
            )
            inminente = False

        if not tarde and not inminente:
            break

        # Aqui snapshot_at no puede ser None: sin marca de tiempo ni `tarde` ni
        # `inminente` pueden ser ciertos y ya habriamos salido del bucle.
        ultimo = result.snapshot_at.strftime("%H:%M")
        edad = int(dump_age(result.snapshot_at, ahora).total_seconds() // 60)
        if intentos < 1:
            log.warning(
                "⚠️  El volcado mas nuevo sigue siendo el de las %s UTC (%s min) "
                "y ya no quedan reintentos. Lo recogera la pasada de la hora "
                "siguiente.",
                ultimo,
                edad,
            )
            break

        if tarde:
            margen = settings.stale_retry_wait_seconds
            log.warning(
                "⏳ Blizzard va tarde: el volcado mas nuevo es el de las %s UTC y "
                "ya tiene %s min, asi que el de esta hora no ha salido. Vigilo "
                "hasta %s s a ver si aparece (quedan %s intento(s)).",
                ultimo,
                edad,
                margen,
                intentos,
            )
        else:
            historial.apunta_espera()
            # Lo que falte mas un colchon, porque no publican al segundo exacto.
            margen = int(falta * 60) + settings.stale_retry_wait_seconds
            log.warning(
                "⏳ El volcado de las %s UTC ya tiene %s min y el siguiente sale "
                "en unos %.0f min: no merece la pena avisar de chollos tan "
                "viejos. Espero al nuevo (hasta %s s).",
                ultimo,
                edad,
                falta,
                margen,
            )

        intentos -= 1
        if not esperar_volcado_nuevo(
            client, realm_ids, result.snapshot_at, settings, margen
        ):
            log.warning(
                "⚠️  Sigue sin aparecer. Reescaneo de todos modos por si acaso."
            )

    # Una vez por pasada y no dentro del bucle: si hemos estado esperando a un
    # volcado retrasado, ese retraso es de Blizzard y no dice nada del cron.
    #
    # En silencio ni se mide: esto acaba mandando un aviso a Discord, y aqui no
    # hay nada que se pierda por esperar. Quedan 16 pasadas al dia despiertas,
    # de sobra para cazar un cambio de horario que pasa cada varias semanas.
    if result.snapshot_at and es_pasada_programada():
        # Se mide y se mueve tambien en silencio: cambiar el minuto del cron no
        # despierta a nadie, y esperar a las nueve costaria toda la manana con
        # los avisos desalineados. Lo que se aplaza es contarlo.
        mantener_disparo_alineado(
            arranque,
            result.snapshot_at,
            historial,
            notifier,
            dry_run=args.dry_run,
            callado=callado,
        )
        if not callado and not args.dry_run:
            pendiente = historial.recoge_aviso()
            if pendiente:
                avisar_por_discord(notifier, *pendiente)

    # Fuera del if: la cuenta de esperas se lleva en el bucle de arriba y hay que
    # guardarla aunque no toque medir el disparo, que es de lo que depende el
    # tope de gasto.
    if not args.dry_run:
        historial.save()

    if result.failure_ratio > settings.failure_ratio_threshold:
        message = (
            f"Han fallado {len(result.realms_failed)} de {result.realms_total} reinos "
            f"en esta pasada. Los resultados estan incompletos: puede haber chollos "
            f"que no hayas visto."
        )
        log.error("❌ %s", message)
        if notifier and not args.dry_run:
            try:
                notifier.send_warning("Escaneo incompleto", message)
            except DiscordError as exc:
                log.error("Ademas, no he podido avisar por Discord: %s", exc)
        return EXIT_TOO_MANY_FAILURES

    return EXIT_OK


def scan_once(
    client,
    config,
    realm_ids,
    rules_by_item_id,
    rules_by_species,
    notified,
    icon_cache,
    notifier,
    roster_path: str,
    *,
    dry_run: bool,
    ignore_state: bool,
    callado: bool = False,
):
    """Una lectura completa de la region, con sus avisos ya enviados.

    Se ejecuta mas de una vez cuando el volcado de Blizzard llega tarde. Cada
    intento avisa por su cuenta y marca lo enviado, de modo que un chollo visto
    solo en el primer intento no se pierde aunque en el segundo ya no aparezca:
    para entonces lo habran comprado, pero el aviso salio a tiempo.
    """
    started = time.monotonic()
    result = scan_realms(client, config, realm_ids, rules_by_item_id, rules_by_species)
    elapsed = time.monotonic() - started

    log.info(
        "📊 %s/%s reinos leidos en %.0f s (%s subastas analizadas).",
        result.realms_ok,
        result.realms_total,
        elapsed,
        f"{result.auctions_seen:,}".replace(",", "."),
    )
    if result.snapshot_at:
        edad = (
            datetime.now(timezone.utc) - result.snapshot_at
        ).total_seconds() / 60
        log.info(
            "🕒 Datos del volcado de las %s UTC (hace %.0f min).",
            result.snapshot_at.strftime("%H:%M"),
            edad,
        )

    if result.realms_failed:
        log.warning(
            "⚠️  %s reino(s) han fallado: %s",
            len(result.realms_failed),
            ", ".join(str(r) for r in sorted(result.realms_failed)[:20]),
        )

    fresh = result.deals if ignore_state else notified.filter_new(result.deals)
    repeats = len(result.deals) - len(fresh)
    if repeats:
        log.info("🔁 %s chollo(s) ya avisados anteriormente, omitidos.", repeats)

    if fresh:
        realm_names = realm_names_for(fresh, client.connected_realm_name)
        compradores = compradores_para(roster_path, realm_names)
        log.info("🎉 %s chollo(s) nuevos:", len(fresh))
        print_deals(fresh, realm_names, compradores)

        if callado:
            # No se marcan como avisados, asi que al acabar el silencio se
            # envian los que sigan por debajo de tu precio.
            log.info("🔕 En silencio: no envio estos chollos todavia.")
        elif dry_run:
            log.info("🧪 --dry-run: no envio nada a Discord ni guardo el estado.")
        else:
            icon_urls = resolve_icons(client, icon_cache, fresh)
            icon_cache.save()
            try:
                sent = notifier.send_deals(
                    fresh, realm_names, icon_urls, result.snapshot_at, compradores
                )
            except DiscordError as exc:
                # Lo que llego antes del fallo ya esta en Discord: se apunta
                # antes de dejar subir el error, o la pasada siguiente lo
                # repetiria.
                for deal in exc.entregados:
                    notified.mark(deal.realm_id, deal.auction_id)
                notified.save()
                raise
            log.info("📨 Enviados a Discord %s chollo(s).", len(sent))

            # Solo se marcan los que han salido de verdad. Si algo no cupo en
            # el aviso, sigue sin marcar y la proxima pasada lo enviara.
            for deal in sent:
                notified.mark(deal.realm_id, deal.auction_id)

            pendientes = len(fresh) - len(sent)
            if pendientes:
                log.warning(
                    "⏭️  %s chollo(s) no caben en este aviso; se enviaran en la "
                    "proxima pasada.",
                    pendientes,
                )
    else:
        log.info("😴 Ningun chollo nuevo esta vez.")

    if not dry_run:
        # Se guarda en cada intento, no al final: si la pasada muriera durante
        # la espera, lo ya avisado seguiria constando y no se repetiria.
        notified.save()

    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)

    try:
        return run(args)
    except (
        ConfigError,
        BlizzardAuthError,
        DiscordError,
        ItemResolutionError,
        MisSubastasError,
        RealmResolutionError,
    ) as exc:
        log.error("❌ %s", exc)
        return EXIT_CONFIG_ERROR
    except BlizzardError as exc:
        log.error("❌ Error hablando con la API de Blizzard: %s", exc)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario.")
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    sys.exit(main())
