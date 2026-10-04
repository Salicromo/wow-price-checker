"""Deteccion de ventas de tus propias subastas.

La API de Blizzard no publica ventas: solo una foto por hora de lo que sigue
vivo. Una subasta tuya que desaparece pudo venderse, caducar o cancelarse, y
desde fuera las tres se ven igual.

Aqui se separa la primera de las otras dos con una sola idea: de cada subasta
se guarda la fecha mas temprana en la que PODRIA caducar. Si desaparece antes
de esa fecha, es imposible que haya caducado.

La regla es pura, como scanner.find_deals y undercut.find_undercuts: recibe el
volcado ya descargado y devuelve las ventas, sin tocar red ni disco.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import AbstractSet, Mapping, Sequence

from .config import COPPER_PER_GOLD
from .ilvl import int_list, resolve_ilvl
from .misubastas import MyAuction

log = logging.getLogger(__name__)

# Vida minima que garantiza cada tramo de Blizzard. SHORT no garantiza nada:
# "menos de 30 minutos" incluye "un segundo".
TIEMPO_MINIMO_RESTANTE = {
    "VERY_LONG": timedelta(hours=12),
    "LONG": timedelta(hours=2),
    "MEDIUM": timedelta(minutes=30),
    "SHORT": timedelta(0),
}


# Cuanto se le da al addon para contar que cancelaste una subasta que te
# estaban adelantando. Cancelarla exige estar jugando, y jugar acaba en un
# /reload o en salir del juego, que es cuando WoW escribe los SavedVariables y
# el vigilante se entera. Si en todo ese rato el addon no ha vuelto a hablar, es
# que no has jugado, y entonces no has podido cancelarla: se vendio.
#
# Dos horas son dos pasadas mas. Caben de sobra antes de que el volcado del
# addon se pase de las horas que dura un listado, que es cuando la subasta se
# soltaria sin veredicto.
ESPERA_TRAS_UN_ADELANTAMIENTO = timedelta(hours=2)


# Cuanto se considera que sigue en marcha una partida despues de la ultima vez
# que una maquina exporto. Cancelar una subasta exige estar jugando, asi que una
# maquina que dio senales de vida hace menos de esto pudo cancelarla y todavia
# no habermelo contado.
#
# El 2026-09-07 esto costo ocho ventas falsas: la Steam Deck exporto Obarbar a
# las 22:36 UTC, siguio la ronda por Dbardan, Mbarlin, Ebardan y
# Ebarmar, y su sincronizacion se corto ahi. Las cancelaciones de esos cuatro
# se quedaron dentro de la Deck, sus subastas desaparecieron del volcado de las
# 23:23 y se cantaron como vendidas.
#
# Lo que fallaba no era el plazo, era medirlo desde la desaparicion: la espera
# vencia sola y decidia igual. Una maquina que ha dejado de sincronizar no se
# vuelve fiable porque pasen horas, asi que ahora la espera no vence: dura hasta
# que esa maquina vuelve a hablar. El precio es que una venta de verdad ocurrida
# justo despues de jugar no se anuncia hasta que vuelvas a entrar en esa
# maquina; a cambio, ninguna cancelacion se cuela como venta.
MARGEN_DE_SESION = timedelta(hours=2)


@dataclass(frozen=True)
class UltimoVolcado:
    """La foto anterior de un reino: cuando se leyo y hasta que id llegaba.

    El id maximo es lo que permite afirmar que una subasta acaba de nacer: los
    ids crecen con el tiempo dentro de un reino, asi que uno mayor que todos los
    de la foto anterior se publico despues de ella.
    """

    dump_at: datetime
    max_auction_id: int


@dataclass(frozen=True)
class SubastaVigilada:
    """Una subasta tuya en seguimiento, con lo justo para anunciar su venta.

    Guarda una copia de los datos del objeto a proposito. Cuando vendes y luego
    haces /reload, el volcado del addon deja de mencionarla, y eso puede pasar
    antes de la pasada siguiente: sin esta copia, esa venta no se anunciaria
    nunca.
    """

    auction_id: int
    item_id: int
    item_name: str
    # Hace falta en el aviso: el mismo objeto se vende a 292, 295, 298 y 305, y
    # sin el ilvl no se sabe cual de todas se ha ido.
    ilvl: int
    buyout_copper: int
    quantity: int
    character: str
    realm: str
    account: int | None
    # La fecha mas temprana en la que esta subasta podria caducar. Es una
    # garantia acumulada: solo sube, nunca baja.
    no_caduca_antes_de: datetime
    # Hora del ultimo volcado en el que se vio viva. Sirve para olvidarla si el
    # reino deja de escanearse.
    visto_at: datetime
    # Si la ultima vez que se vio viva alguien la habia adelantado. Cuando una
    # subasta adelantada desaparece, lo que ha pasado es que has ido a
    # repostearla: el aviso de undercut existe justamente para eso.
    adelantada: bool = False
    # Hora del volcado en el que se la vio faltar por primera vez. Mientras vale
    # None sigue viva. Una subasta que falta no se canta como vendida hasta la
    # pasada siguiente, para dar tiempo a que llegue del juego la noticia de que
    # la cancelaste tu: el volcado de Blizzard se entera de tus cancelaciones
    # antes que el addon, que solo escribe a disco al hacer /reload.
    desaparecida_at: datetime | None = None
    # La version exacta del objeto, como la exporta el addon. Hace falta para
    # reconocer un reposteo cuando Blizzard no dice el ilvl de la subasta nueva.
    bonus_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class Venta:
    """Una subasta tuya que ha desaparecido antes de poder caducar."""

    subasta: SubastaVigilada
    realm_id: int
    detectada_at: datetime
    ah_cut_pct: int = 5

    @property
    def neto_copper(self) -> int:
        """Lo que llega al buzon: el precio menos la comision de la casa.

        El descuento va en cobre y antes de pasar a oro, porque redondear a oro
        primero perderia la parte que se queda la casa en los precios bajos.
        """
        return self.subasta.buyout_copper * (100 - self.ah_cut_pct) // 100

    @property
    def neto_gold(self) -> int:
        return self.neto_copper // COPPER_PER_GOLD



def cota_por_time_left(time_left: str, dump_at: datetime) -> datetime:
    """Hasta cuando garantiza vivir una subasta vista en ese tramo.

    Un tramo que no reconozcamos no garantiza nada: si Blizzard inventa uno
    nuevo, callarse es mejor que afirmar de mas.
    """
    return dump_at + TIEMPO_MINIMO_RESTANTE.get(
        str(time_left).upper(), timedelta(0)
    )


def _vigilada_de(mia: MyAuction, dump_at: datetime) -> SubastaVigilada:
    """La copia inicial de una subasta tuya que se empieza a seguir."""
    return SubastaVigilada(
        auction_id=mia.auction_id,
        item_id=mia.item_id,
        item_name=mia.item_name,
        ilvl=mia.ilvl,
        buyout_copper=mia.buyout_copper,
        quantity=mia.quantity,
        character=mia.character,
        realm=mia.realm,
        account=mia.account,
        no_caduca_antes_de=dump_at,
        visto_at=dump_at,
        bonus_ids=mia.bonus_ids,
    )


def _la_han_repuesto(
    vigilada: SubastaVigilada,
    recien_puestas: Sequence[Mapping],
    bonus_ilvl_map: Mapping[int, int],
) -> bool:
    """Si en el volcado en que falta hay otra igual recien publicada.

    Es la huella de un reposteo, y la unica que queda cuando la maquina desde
    la que cancelaste no sincroniza: el 2026-09-09 la Steam Deck llevaba tres
    dias sin subir nada y catorce reposteos suyos se cantaron como ventas.

    Cuenta la misma version del objeto, con la regla de undercut._compite_con
    (mismo ilvl si se puede deducir, mismos bonus si no), a su precio o por
    debajo. Mas cara no cuenta: es lo que haria quien te la ha comprado para
    revenderla.

    El precio de esta regla: si alguien pone ese mismo objeto mas barato justo
    en la hora en que se vende el tuyo, esa venta no se anuncia.
    """
    for auction in recien_puestas:
        precio = auction.get("buyout")
        if not isinstance(precio, int) or isinstance(precio, bool) or precio <= 0:
            continue
        if precio > vigilada.buyout_copper:
            continue
        item = auction.get("item") or {}
        ilvl = resolve_ilvl(item, bonus_ilvl_map).value
        if ilvl is not None:
            if ilvl == vigilada.ilvl:
                return True
        elif frozenset(int_list(item.get("bonus_lists"))) == frozenset(vigilada.bonus_ids):
            return True
    return False


def revisar_reino(
    seguidas: Mapping[int, SubastaVigilada],
    mis_subastas: Sequence[MyAuction],
    auctions: Sequence[Mapping],
    realm_id: int,
    dump_at: datetime,
    anterior: UltimoVolcado | None,
    listing_hours: int = 12,
    ah_cut_pct: int = 5,
    adelantadas: AbstractSet[int] = frozenset(),
    canceladas: AbstractSet[int] = frozenset(),
    decidir: bool = True,
    olvidar: AbstractSet[int] = frozenset(),
    actividad: Mapping[str, datetime] = MappingProxyType({}),
    bonus_ilvl_map: Mapping[int, int] = MappingProxyType({}),
) -> tuple[list[Venta], dict[int, SubastaVigilada], UltimoVolcado]:
    """Las ventas de este reino, el seguimiento actualizado y su foto nueva.

    `anterior` es la foto del ultimo volcado de ESTE reino leido con exito. Vale
    None cuando es la primera vez o cuando el reino fallo, y entonces no se
    aplica la cota de nacimiento: sin saber que habia antes, no se puede
    afirmar que una subasta acabe de publicarse.

    `adelantadas` son las subastas tuyas que alguien esta adelantando ahora
    mismo, y `canceladas` las que el addon ha visto que retiraste tu: ni unas ni
    otras son ventas.

    Con `decidir` a False (la ventana de silencio) se sigue el rastro igual,
    pero no se cierra ningun caso: lo que falte se queda pendiente y se resuelve
    al despertar, con la hora en la que desaparecio de verdad.

    `actividad` dice cuando exporto por ultima vez cada maquina. Una que estaba
    jugando cuando la subasta desaparecio pudo cancelarla, y hasta que no vuelve
    a hablar no hay forma de saberlo: ver MARGEN_DE_SESION.

    `olvidar` son subastas cuya maquina lleva tanto sin exportar que ya no se
    puede afirmar nada de ellas. Se sueltan SIN veredicto, pero solo las que
    Blizzard tampoco lista: si sigue viva en el volcado, es real y se sigue
    vigilando. Lo que hay que evitar son los ids zombis --los que el addon aun
    canta y Blizzard ya no tiene--, porque son los que se inventan ventas.

    `bonus_ilvl_map` sirve para deducir el ilvl de las subastas nuevas del
    volcado: una igual a la tuya publicada justo cuando la tuya falta es un
    reposteo, y se cierra en el acto como una cancelacion conocida, tambien en
    silencio. Ver _la_han_repuesto.
    """
    mias_por_id = {m.auction_id: m for m in mis_subastas}

    # Cuando volco el addon por ultima vez lo de cada personaje. Es lo que dice
    # si ha tenido ocasion de contar una cancelacion tuya.
    exportado_por_pj: dict[str, int] = {}
    for mia in mis_subastas:
        exportado_por_pj[mia.character] = max(
            exportado_por_pj.get(mia.character, 0), mia.exported_at
        )

    # Una sola pasada por el volcado: de las 30.000 subastas del reino solo
    # interesan las tuyas, pero el id maximo se calcula sobre todas, que es lo
    # que hace fiable la cota de nacimiento.
    vivas: dict[int, str] = {}
    max_auction_id = 0
    # De paso se apartan las publicadas desde la foto anterior de los objetos
    # que sigo: son las candidatas a reposteo de lo que falte en este volcado.
    objetos_seguidos = {v.item_id for v in seguidas.values()}
    recien_puestas: dict[int, list[Mapping]] = {}
    for auction in auctions:
        auction_id = auction.get("id")
        if not isinstance(auction_id, int) or isinstance(auction_id, bool):
            continue
        max_auction_id = max(max_auction_id, auction_id)
        if auction_id in mias_por_id or auction_id in seguidas:
            vivas[auction_id] = str(auction.get("time_left", ""))
        if anterior is not None and auction_id > anterior.max_auction_id:
            item = auction.get("item")
            item_id = item.get("id") if isinstance(item, Mapping) else None
            if item_id in objetos_seguidos:
                recien_puestas.setdefault(item_id, []).append(auction)

    # Se sueltan las de volcado viejo, pero solo las que unicamente sostiene el
    # addon. Lo que Blizzard avala se sigue vigilando: ver _la_avala_blizzard.
    if olvidar:
        seguidas = {
            k: v
            for k, v in seguidas.items()
            if k not in olvidar or _la_avala_blizzard(v, k in vivas, anterior)
        }

    nuevas: dict[int, SubastaVigilada] = {}
    for auction_id, time_left in vivas.items():
        previa = seguidas.get(auction_id)

        cotas = [cota_por_time_left(time_left, dump_at)]
        if previa is not None:
            cotas.append(previa.no_caduca_antes_de)
        if anterior is not None and auction_id > anterior.max_auction_id:
            # No estaba en la foto anterior: se publico despues de ella, asi que
            # su plazo entero cuenta desde entonces.
            cotas.append(anterior.dump_at + timedelta(hours=listing_hours))

        base = (
            previa
            if previa is not None
            else _vigilada_de(mias_por_id[auction_id], dump_at)
        )

        # Si el addon ya no la conoce no se puede recalcular su undercut, asi
        # que se conserva lo ultimo que se supo: callarse de mas es preferible a
        # inventarse una venta.
        adelantada = (
            auction_id in adelantadas
            if auction_id in mias_por_id
            else base.adelantada
        )

        nuevas[auction_id] = replace(
            base,
            no_caduca_antes_de=max(cotas),
            visto_at=dump_at,
            adelantada=adelantada,
            desaparecida_at=None,
        )

    ventas: list[Venta] = []
    for auction_id, vigilada in seguidas.items():
        if auction_id in vivas:
            continue

        if auction_id in canceladas:
            log.info(
                "↩️  %s de %s: la cancelaste tu, asi que no la cuento como venta.",
                vigilada.character,
                vigilada.item_name,
            )
            continue

        # Solo en el volcado en que falta por primera vez: es el unico en el que
        # "publicada desde la foto anterior" quiere decir "a la vez que se fue".
        if vigilada.desaparecida_at is None and _la_han_repuesto(
            vigilada, recien_puestas.get(vigilada.item_id, ()), bonus_ilvl_map
        ):
            log.info(
                "↩️  %s de %s: ha salido otra igual en el mismo volcado en que "
                "falta esta, asi que la volviste a poner. No la cuento como venta.",
                vigilada.character,
                vigilada.item_name,
            )
            continue

        if not decidir:
            # En silencio no se cierra nada: se anota la desaparicion si es la
            # primera vez y se deja para cuando toque avisar.
            nuevas[auction_id] = (
                vigilada
                if vigilada.desaparecida_at is not None
                else replace(vigilada, desaparecida_at=dump_at)
            )
            continue

        if vigilada.desaparecida_at is None:
            # Falta por primera vez: se espera una pasada. Blizzard se entera de
            # tus cancelaciones antes que el addon, que solo vuelca a disco al
            # hacer /reload, asi que cantar la venta ya seria adelantarse a la
            # unica fuente capaz de desmentirla.
            nuevas[auction_id] = replace(vigilada, desaparecida_at=dump_at)
            # En INFO y no en DEBUG: con esto callado, una venta tarda una hora
            # en anunciarse y desde fuera no hay forma de distinguir "viene en la
            # proxima pasada" de "se ha perdido". Las cancelaciones ya se cantan
            # aqui mismo, asi que ademas era incoherente.
            log.info(
                "⏳ %s de %s ha desaparecido. Espero una pasada por si resulta "
                "que la cancelaste; si no, la anuncio en la siguiente.",
                vigilada.character,
                vigilada.item_name,
            )
            continue

        calladas = _maquinas_por_hablar(vigilada.desaparecida_at, actividad)
        if calladas:
            # Estabas jugando ahi cuando la subasta se fue, asi que pudiste
            # cancelarla. Solo esa maquina puede decirlo, y aun no ha vuelto.
            log.info(
                "⏳ %s de %s: sin noticias de %s desde que desaparecio, y ahi se "
                "estaba jugando. No la juzgo hasta que vuelva a exportar.",
                vigilada.character,
                vigilada.item_name,
                ", ".join(calladas),
            )
            nuevas[auction_id] = vigilada
            continue

        if vigilada.adelantada and _falta_por_hablar_el_addon(
            vigilada, dump_at, exportado_por_pj
        ):
            # Que te esten adelantando NO prueba que la hayas reposteado: el
            # aviso te manda a repostear, pero puedes no haber ido, y una
            # subasta adelantada se vende igual. Antes esto la descartaba para
            # siempre y se comia ventas de verdad. Ahora solo espera a que el
            # addon tenga ocasion de decir si la cancelaste tu.
            log.info(
                "⏳ %s de %s: te la estaban adelantando y el addon aun no ha "
                "vuelto a hablar. Le doy hasta las %s antes de decidir.",
                vigilada.character,
                vigilada.item_name,
                (vigilada.desaparecida_at + ESPERA_TRAS_UN_ADELANTAMIENTO).strftime(
                    "%H:%M"
                ),
            )
            nuevas[auction_id] = vigilada
            continue

        # Segunda pasada seguida sin aparecer y sin noticia de cancelacion.
        # Se juzga con la hora en que se fue, no con la de ahora: si no, la
        # espera empujaria la subasta mas alla de su fecha de caducidad y se
        # perderian ventas buenas.
        if vigilada.desaparecida_at < vigilada.no_caduca_antes_de:
            ventas.append(
                Venta(
                    subasta=vigilada,
                    realm_id=realm_id,
                    detectada_at=vigilada.desaparecida_at,
                    ah_cut_pct=ah_cut_pct,
                )
            )
        else:
            log.debug(
                "Tu subasta %s de %s ya podia haber caducado cuando desaparecio "
                "(su plazo vencia a las %s): no la cuento como venta.",
                auction_id,
                vigilada.item_name,
                vigilada.no_caduca_antes_de,
            )

    ventas.sort(key=lambda v: v.neto_copper, reverse=True)
    return ventas, nuevas, UltimoVolcado(dump_at, max_auction_id)


def _maquinas_por_hablar(
    desaparecida_at: datetime, actividad: Mapping[str, datetime]
) -> list[str]:
    """Las maquinas que estaban jugando al irse la subasta y siguen calladas.

    Una maquina solo puede haber cancelado algo si estaba encendida y jugando, y
    solo puede contarmelo exportando despues. Mientras la ultima senal de vida
    que tengo de ella caiga en la ventana de la desaparicion, lo que ha pasado
    es indistinguible de una cancelacion suya que no me ha llegado.

    Con el volcado al dia esto no retiene nada: en cuanto la maquina exporta
    despues de la desaparicion deja de estar callada. Solo muerde cuando una
    maquina se calla justo despues de jugar, que es exactamente cuando las
    cancelaciones se pierden.
    """
    return sorted(
        maquina
        for maquina, ultima in actividad.items()
        if desaparecida_at - MARGEN_DE_SESION <= ultima <= desaparecida_at
    )


def _falta_por_hablar_el_addon(
    vigilada: SubastaVigilada,
    dump_at: datetime,
    exportado_por_pj: Mapping[str, int],
) -> bool:
    """Si todavia merece la pena esperar antes de juzgar una adelantada.

    Se deja de esperar por cualquiera de los dos lados: porque el addon ya ha
    vuelto a volcar despues de que la subasta desapareciera --y entonces ya ha
    dicho todo lo que tenia que decir sobre tus cancelaciones-- o porque ha
    pasado tanto rato sin volcar que esta claro que no has estado jugando.
    """
    if vigilada.desaparecida_at is None:
        return False

    if dump_at - vigilada.desaparecida_at >= ESPERA_TRAS_UN_ADELANTAMIENTO:
        return False

    exportado = exportado_por_pj.get(vigilada.character)
    if exportado is None:
        # Sin subastas suyas en el volcado no hay forma de saber cuando hablo el
        # addon por ultima vez; solo queda esperar a que venza el plazo.
        return True

    volcado_at = datetime.fromtimestamp(exportado, tz=vigilada.desaparecida_at.tzinfo)
    return volcado_at <= vigilada.desaparecida_at


def _la_avala_blizzard(
    vigilada: SubastaVigilada, viva_ahora: bool, anterior: UltimoVolcado | None
) -> bool:
    """Si de esta subasta hay algo mas que la palabra de un volcado viejo.

    Lo que hay que soltar cuando el addon se queda atras son los ids zombis: los
    que el sigue cantando y Blizzard ya no tiene. Con esos no se puede afirmar
    nada, y afirmar de mas se inventa ventas.

    Pero una subasta que Blizzard lista es real por mucho que el addon lleve
    horas sin volcar, y su fecha de caducidad se mantiene con el time_left que
    manda Blizzard, sin depender del addon para nada. Igual de real es la que
    estaba viva en la pasada anterior y ahora falta: esa desaparicion es la
    prueba que hace falta para juzgarla, y soltarla es tirarla justo cuando
    acaba de llegar.

    Sin esto, el 2026-09-06 se perdio un Yelmo mistico de Ebardan de
    190.000 g: se vendio de verdad y nunca llego a haber veredicto.
    """
    if viva_ahora or vigilada.desaparecida_at is not None:
        return True

    # Sin foto anterior no se sabe si estaba viva hace una pasada, y en la duda
    # se suelta: perder un aviso es mejor que inventarse una venta.
    return anterior is not None and vigilada.visto_at >= anterior.dump_at
