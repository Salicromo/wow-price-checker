"""Envio de avisos a Discord.

La construccion de los embeds es una funcion pura (`build_messages`) para poder
comprobar el formato en los tests sin enviar nada, y el envio real es una capa
fina encima.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode

import requests

from .scanner import Deal
from .undercut import Undercut
from .ventas import Venta

log = logging.getLogger(__name__)

# Limites del webhook de Discord.
MAX_EMBEDS_PER_MESSAGE = 10
# Texto total entre todos los embeds de un mensaje.
MAX_CHARS_PER_MESSAGE = 6000
# Tope propio: mas de esto en una pasada es ruido, no una oportunidad.
MAX_DEALS_PER_RUN = 50

COLOR_UNCONFIRMED = 0x95A5A6  # gris: ilvl sin confirmar
COLOR_GOOD = 0xE67E22        # naranja: por debajo del umbral
COLOR_GREAT = 0xF1C40F       # amarillo: bastante por debajo
COLOR_STEAL = 0x2ECC71       # verde: chollo serio
COLOR_WARNING = 0xE74C3C     # rojo: aviso de salud del bot
COLOR_UNDERCUT = 0xC0392B    # rojo oscuro: te han adelantado
COLOR_VENTA = 0xD4AF37       # oro viejo: dinero que entra
# Limite duro de Discord para la descripcion de un embed.
MAX_EMBED_DESCRIPTION = 4096
# Tope propio de lineas por mensaje: mas de esto ya no se lee de un vistazo.
MAX_UNDERCUT_LINES_PER_MESSAGE = 20
# A partir de este precio (el tuyo) una subasta adelantada se marca en el aviso.
UNDERCUT_CARO_GOLD = 80_000
# Cuantas veces se espera lo que pide un 429 antes de rendirse. Es generoso a
# proposito: esperar sale gratis y el aviso llega, rendirse lo pierde.
MAX_ESPERAS_POR_LIMITE = 5
# Los nombres de objeto de WoW no pasan de 60 caracteres, pero recortarlos
# garantiza que una linea suelta nunca pueda desbordar un mensaje entero.
MAX_ITEM_NAME = 100

# Donde vive el repositorio, para el enlace de "Ajustar tope". En Actions lo
# pone el propio runner; fuera se usa este, que es el unico sitio del proyecto
# que necesita saberlo.
REPO_POR_DEFECTO = "Salicromo/wow-price-checker"
PLANTILLA_TOPE = "tope-aviso.yml"

TIME_LEFT_ES = {
    "SHORT": "menos de 30 min",
    "MEDIUM": "30 min - 2 h",
    "LONG": "2 - 12 h",
    "VERY_LONG": "mas de 12 h",
}


class DiscordError(Exception):
    """No se ha podido entregar el aviso a Discord.

    `entregados` son los avisos que si llegaron antes del fallo: un envio va en
    varios mensajes, y si cae el tercero los dos primeros ya estan en Discord.
    Quien llama los marca como avisados para no repetirlos la pasada siguiente.
    """

    def __init__(self, mensaje: str, entregados: Sequence[Any] = ()) -> None:
        super().__init__(mensaje)
        self.entregados = list(entregados)


def format_gold(amount: int) -> str:
    """120000 -> '120.000' (separador de miles a la espanola)."""
    return f"{amount:,}".replace(",", ".")


def _time_left_label(raw: str) -> str:
    return TIME_LEFT_ES.get(raw.upper(), raw or "desconocido")


def _wowhead_url(deal) -> str:
    """Enlace a la ficha de lo subastado.

    Las mascotas van por /pet: todas comparten el objeto 82800, asi que un
    enlace /item las llevaria a la jaula vacia en vez de a la mascota.
    """
    destino = (
        f"pet={deal.pet_species_id}"
        if deal.pet_species_id is not None
        else f"item={deal.item_id}"
    )
    return f"https://www.wowhead.com/{destino}"


def _repo() -> str:
    return os.getenv("GITHUB_REPOSITORY") or REPO_POR_DEFECTO


def _ajustar_tope_url(deal: Deal) -> str:
    """Enlace al formulario que cambia el tope de este objeto.

    El aviso ya te dice contra que limite se ha comparado, asi que es el sitio
    natural para corregirlo cuando ves que ese limite esta alto. Lleva el objeto
    y el ilvl puestos: lo unico que se teclea es el numero.

    Se prerrellena por 'objeto' e 'ilvl', que son los ids de los campos de
    tope-aviso.yml. Esa plantilla usa campos de texto y no desplegables
    justamente por esto: GitHub no sabe prerrellenar un dropdown.
    """
    parametros = {"template": PLANTILLA_TOPE, "objeto": deal.item_name}

    # El ilvl solo se prerrellena cuando se sabe cual es. Con un ilvl en duda,
    # ponerlo invitaria a cambiar el tope del escalon equivocado.
    if deal.ilvl is not None and deal.ilvl_confirmed and not deal.sin_ilvl:
        parametros["ilvl"] = str(deal.ilvl)

    return f"https://github.com/{_repo()}/issues/new?{urlencode(parametros)}"


def _color_for(deal: Deal) -> int:
    if not deal.ilvl_confirmed and not deal.sin_ilvl:
        return COLOR_UNCONFIRMED
    if deal.discount_pct >= 50:
        return COLOR_STEAL
    if deal.discount_pct >= 25:
        return COLOR_GREAT
    return COLOR_GOOD


def _cabecera(deal: Deal) -> str:
    """El subtitulo de un objeto: su nombre con el ilvl y su tope.

    El mismo objeto a otro ilvl es otro producto con su propio tope, asi que va
    en su propio subtitulo. El nombre enlaza a Wowhead y el tope al formulario
    para cambiarlo: cuando ves que a ese precio no era chollo, lo que sobra es
    el tope, no la subasta, y el formulario llega con el objeto y el ilvl ya
    puestos.
    """
    if deal.sin_ilvl:
        # Un patron no escala, asi que no hay ilvl del que hablar.
        nombre = nombre_con_ilvl(deal.item_name, None)
    elif deal.ilvl_confirmed:
        nombre = nombre_con_ilvl(deal.item_name, deal.ilvl)
    else:
        nombre = nombre_con_ilvl(deal.item_name, None) + " (ilvl ⚠️)"
    return (
        f"**[{nombre}]({_wowhead_url(deal)})** · "
        f"[tope {format_gold(deal.threshold_gold)}]({_ajustar_tope_url(deal)})"
    )


# El tiempo restante solo se ensena cuando aprieta: "mas de 12 h" es lo normal
# y repetirlo en cada linea solo hacia ruido.
TIEMPOS_QUE_APRIETAN = {"SHORT", "MEDIUM", "LONG"}


def _deal_line(deal: Deal, quien: str) -> str:
    """Una subasta bajo el subtitulo de su objeto: precio y con quien ir.

    Con quien ir va en lugar del reino porque es lo que decide el viaje: el
    personaje y la cuenta con que entrar.
    """
    linea = "• "
    if deal.quantity > 1:
        linea += f"×{deal.quantity} — "
    linea += (
        f"**{format_gold(deal.price_gold)} g** "
        f"(−{deal.discount_pct:.0f}%) · {quien}"
    )
    if deal.time_left.upper() in TIEMPOS_QUE_APRIETAN:
        linea += f" · ⏳ {_time_left_label(deal.time_left)}"
    return linea


NOTA_ILVL_SIN_CONFIRMAR = (
    "> ⚠️ ilvl sin confirmar: comparado con tu precio mas bajo para ese "
    "objeto. Comprueba el ilvl en el juego antes de comprar."
)


def _orden_ilvl(deal: Deal) -> tuple[int, int]:
    """Los objetos de mayor a menor ilvl, y despues los de ilvl dudoso y lo
    que no escala, que no tienen sitio en esa escala."""
    if deal.sin_ilvl:
        return (2, 0)
    if not deal.ilvl_confirmed or deal.ilvl is None:
        return (1, 0)
    return (0, -deal.ilvl)


def _con_quien(
    deal: Deal, realm_names: Mapping[int, str], compradores: Mapping[int, str]
) -> str:
    """Con quien comprar el chollo; el reino solo si no se sabe."""
    quien = compradores.get(deal.realm_id)
    if quien:
        return quien.replace("\n", ", ")
    return realm_names.get(deal.realm_id, f"Reino {deal.realm_id}")


def _cuenta(quien: str) -> int:
    """La cuenta mas baja con la que se puede ir, para ordenar por cuenta.

    Sale del texto porque es lo unico que llega aqui; el formato lo pone
    `Personaje.etiqueta` ('Kbardan · WoW 2'). Sin cuenta conocida, al final.
    """
    cuentas = [int(n) for n in re.findall(r"WoW (\d+)", quien)]
    return min(cuentas, default=sys.maxsize)


def _deal_embeds(
    deals: Sequence[Deal],
    realm_names: Mapping[int, str],
    icon_urls: Mapping[int, str],
    snapshot_at: datetime | None,
    compradores: Mapping[int, str],
) -> list[tuple[dict[str, Any], list[Deal]]]:
    """Las tarjetas del aviso: un subtitulo por objeto y una linea por subasta.

    Una tarjeta por subasta obligaba a hacer scroll sin fin. Todo va en una
    tarjeta mientras quepa; si no, sigue en otra, y un objeto partido entre
    dos repite su subtitulo para que ninguna linea quede huerfana.
    """
    # dict normal: dentro del mismo ilvl, los objetos salen en el orden de su
    # primer chollo. La cabecera ya distingue objeto, ilvl y tope.
    por_objeto: dict[str, list[Deal]] = {}
    for deal in sorted(deals, key=_orden_ilvl):
        por_objeto.setdefault(_cabecera(deal), []).append(deal)

    hay_dudosos = any(not d.ilvl_confirmed and not d.sin_ilvl for d in deals)
    presupuesto = MAX_EMBED_DESCRIPTION
    if hay_dudosos:
        presupuesto -= len(NOTA_ILVL_SIN_CONFIRMAR) + 2

    tarjetas: list[tuple[list[str], list[Deal]]] = []
    lineas: list[str] = []
    suyos: list[Deal] = []
    largo = 0
    for cabecera, del_objeto in por_objeto.items():
        # Por cuenta (WoW 1, 2, 3...), que es el orden en que entras al juego,
        # y dentro de cada cuenta de la mas barata a la mas cara.
        con_quien = [(d, _con_quien(d, realm_names, compradores)) for d in del_objeto]
        con_quien.sort(key=lambda par: (_cuenta(par[1]), par[0].price_copper))
        for indice, (deal, quien) in enumerate(con_quien):
            linea = _deal_line(deal, quien)
            nuevas = [cabecera, linea] if indice == 0 else [linea]
            tamano = sum(len(l) + 1 for l in nuevas)
            if suyos and (
                largo + tamano > presupuesto
                or len(suyos) >= MAX_UNDERCUT_LINES_PER_MESSAGE
            ):
                tarjetas.append((lineas, suyos))
                lineas, suyos, largo = [], [], 0
                nuevas = [cabecera, linea]
                tamano = sum(len(l) + 1 for l in nuevas)
            lineas.extend(nuevas)
            suyos.append(deal)
            largo += tamano
    tarjetas.append((lineas, suyos))

    resultado: list[tuple[dict[str, Any], list[Deal]]] = []
    for lineas, suyos in tarjetas:
        descripcion = "\n".join(lineas)
        if any(not d.ilvl_confirmed and not d.sin_ilvl for d in suyos):
            descripcion += "\n\n" + NOTA_ILVL_SIN_CONFIRMAR

        embed: dict[str, Any] = {
            # El color del mejor chollo de la tarjeta: es lo que hace mirarla.
            "color": _color_for(max(suyos, key=lambda d: d.discount_pct)),
            "description": descripcion,
        }
        icono = icon_urls.get(suyos[0].item_id)
        if icono and len({d.item_id for d in suyos}) == 1:
            # Discord no admite imagenes dentro del texto, solo una en la
            # esquina. Va solo cuando la tarjeta es un unico objeto: con
            # varios, un unico icono diria que es lo que no es.
            embed["thumbnail"] = {"url": icono}
        if snapshot_at:
            # Discord lo pinta junto al pie en la zona horaria de cada lector.
            # Es la hora del volcado de Blizzard, no la del envio: lo que
            # importa es cuando se vio ese precio.
            embed["timestamp"] = snapshot_at.isoformat()
            embed["footer"] = {"text": "precio visto"}

        resultado.append((embed, suyos))
    return resultado


def _embed_chars(embed: Mapping[str, Any]) -> int:
    """Lo que Discord cuenta para su limite de texto por mensaje."""
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    total += sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    return total + len(embed.get("footer", {}).get("text", ""))


def deals_to_send(deals: Sequence[Deal]) -> list[Deal]:
    """Los chollos que caben en un aviso.

    Lo que sobre NO se pierde: al no marcarse como avisado, la pasada siguiente
    lo vuelve a encontrar y lo envia entonces.
    """
    return list(deals[:MAX_DEALS_PER_RUN])


def build_messages(
    deals: Sequence[Deal],
    realm_names: Mapping[int, str],
    icon_urls: Mapping[int, str] | None = None,
    snapshot_at: datetime | None = None,
    compradores: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Los mensajes del aviso de chollos; ver `_deal_messages`."""
    return [
        mensaje
        for mensaje, _ in _deal_messages(
            deals, realm_names, icon_urls, snapshot_at, compradores
        )
    ]


def _deal_messages(
    deals: Sequence[Deal],
    realm_names: Mapping[int, str],
    icon_urls: Mapping[int, str] | None = None,
    snapshot_at: datetime | None = None,
    compradores: Mapping[int, str] | None = None,
) -> list[tuple[dict[str, Any], list[Deal]]]:
    """Los mensajes listos para el webhook, junto con los chollos de cada uno.

    Tantas tarjetas por mensaje como admite Discord (diez, y 6000 caracteres
    entre todas). Se recorta a `MAX_DEALS_PER_RUN`, avisando de cuantos quedan
    pendientes.
    """
    if not deals:
        return []

    shown = deals_to_send(deals)
    omitted = len(deals) - len(shown)

    plural = "chollos" if len(shown) != 1 else "chollo"
    header = f"🚨 **{len(shown)} {plural}** por debajo de tus precios"
    if omitted:
        header += f" (y {omitted} mas que te envio en la proxima pasada)"

    tarjetas = _deal_embeds(
        shown, realm_names, icon_urls or {}, snapshot_at, compradores or {}
    )

    messages: list[tuple[dict[str, Any], list[Deal]]] = []
    embeds: list[dict[str, Any]] = []
    lleva: list[Deal] = []
    largo = len(header)
    for embed, suyos in tarjetas:
        tamano = _embed_chars(embed)
        if embeds and (
            len(embeds) >= MAX_EMBEDS_PER_MESSAGE
            or largo + tamano > MAX_CHARS_PER_MESSAGE
        ):
            messages.append(({"embeds": embeds}, lleva))
            embeds, lleva, largo = [], [], 0
        embeds.append(embed)
        lleva.extend(suyos)
        largo += tamano
    messages.append(({"embeds": embeds}, lleva))

    messages[0][0]["content"] = header
    return messages


def _en_orden(grupos: dict, orden: Mapping[tuple[str, str], int] | None) -> list:
    """Los grupos en el orden en que quieres leerlos.

    Sin esto salen en el orden en que tocara descargar los reinos, que cambia de
    una pasada a otra: no puedes acostumbrarte a mirar siempre al mismo sitio.
    """
    if not orden:
        return list(grupos.items())
    return sorted(
        grupos.items(),
        key=lambda par: orden.get((par[0][0], par[0][1]), len(orden)),
    )


def nombre_con_ilvl(item_name: str, ilvl: int | None) -> str:
    """El nombre del objeto con su ilvl detras: 'Grebas (308)'.

    El mismo objeto se pone a la venta a muchos ilvl a la vez, y cada uno es un
    producto distinto con su propio precio: sin el ilvl no sabes cual de ellas
    es la que te han adelantado o la que se ha vendido.

    Lo que no escala (patrones, decoracion) sale del juego con ilvl 1, que no
    dice nada, y va sin el; igual que en la ventana del addon.
    """
    nombre = item_name
    if len(nombre) > MAX_ITEM_NAME:
        nombre = nombre[: MAX_ITEM_NAME - 1].rstrip() + "…"
    if ilvl and ilvl > 1:
        nombre += f" ({ilvl})"
    return nombre


def _repartir(lineas: list[str], presupuesto: int) -> list[list[str]]:
    """Parte las lineas en grupos que quepan en un mensaje de Discord."""
    grupos: list[list[str]] = []
    actual: list[str] = []
    largo = 0

    for linea in lineas:
        cabe = largo + len(linea) + 1 <= presupuesto
        if actual and (not cabe or len(actual) >= MAX_UNDERCUT_LINES_PER_MESSAGE):
            grupos.append(actual)
            actual, largo = [], 0
        actual.append(linea)
        largo += len(linea) + 1

    if actual:
        grupos.append(actual)
    return grupos


def build_undercut_messages(
    undercuts: Sequence[Undercut],
    ya_avisados: Sequence[Undercut] = (),
    panel_url: str | None = None,
    orden: Mapping[tuple[str, str], int] | None = None,
) -> list[dict[str, Any]]:
    """El resumen por personaje; ver `_undercut_messages`."""
    return [
        mensaje
        for mensaje, _ in _undercut_messages(undercuts, ya_avisados, panel_url, orden)
    ]


def _undercut_messages(
    undercuts: Sequence[Undercut],
    ya_avisados: Sequence[Undercut] = (),
    panel_url: str | None = None,
    orden: Mapping[tuple[str, str], int] | None = None,
) -> list[tuple[dict[str, Any], list[Undercut]]]:
    """El aviso de undercut junto con los undercuts que lleva dentro.

    Un solo mensaje: que personajes tienen algo adelantado y cuantas, por
    cuenta y en el orden en que los tienes en el selector. Es la lista de
    buzones por los que pasar; el detalle de cada subasta lo da la ventana del
    addon en el juego, que ademas esta al minuto y el volcado de Blizzard no.

    Las de `ya_avisados` cuentan igual que las nuevas: lo accionable es todo lo
    que sigue adelantado, no cuando se dijo. Solo hay mensaje si hay alguna
    nueva, que es lo que evita repetir el mismo aviso cada pasada.
    """
    if not undercuts:
        return []

    todas = list(undercuts) + list(ya_avisados)

    # dict normal: conserva el orden de llegada para quien no este en `orden`.
    por_personaje: dict[tuple[str, str, object], list[Undercut]] = {}
    for undercut in todas:
        clave = (
            undercut.mine.character,
            undercut.mine.realm,
            undercut.mine.account,
        )
        por_personaje.setdefault(clave, []).append(undercut)

    # Las cuentas salen en el orden de su primer personaje, asi que el orden de
    # personajes.yaml decide tambien que cuenta va primero.
    por_cuenta: dict[object, list[str]] = {}
    for (character, _realm, account), suyas in _en_orden(por_personaje, orden):
        linea = f"• {character} — {len(suyas)}"
        # Las caras son las que mas merece la pena ir a recolocar primero.
        caras = sum(1 for u in suyas if u.my_price_gold > UNDERCUT_CARO_GOLD)
        if caras:
            linea += f" (💰 {caras})"
        por_cuenta.setdefault(account, []).append(linea)

    plural = "subastas" if len(todas) != 1 else "subasta"
    # Una columna por cuenta, lado a lado: inline hace que Discord las ponga en
    # la misma fila (en el movil se apilan).
    columnas = [
        {
            "name": f"WoW {account}" if account is not None else "Otros",
            "value": "\n".join(lineas),
            "inline": True,
        }
        for account, lineas in por_cuenta.items()
    ]
    embed: dict[str, Any] = {
        "title": f"⚔️ Te han adelantado — {len(todas)} {plural}",
        "color": COLOR_UNDERCUT,
        "fields": columnas,
    }
    if panel_url:
        embed["description"] = f"[📊 Ver el panel con todas]({panel_url})"
    return [({"embeds": [embed]}, todas)]


def _venta_line(venta: Venta) -> str:
    """Una linea del aviso: que se ha vendido y cuanto llega al buzon."""
    nombre = nombre_con_ilvl(venta.subasta.item_name, venta.subasta.ilvl)
    if venta.subasta.quantity > 1:
        nombre += f" ×{venta.subasta.quantity}"
    return f"• {nombre} — **{format_gold(venta.neto_gold)} g**"


def build_venta_messages(
    ventas: Sequence[Venta], orden: Mapping[tuple[str, str], int] | None = None
) -> list[dict[str, Any]]:
    """Un mensaje por personaje, con lo que se le ha vendido esta hora.

    Se agrupa por personaje por el mismo motivo que los undercuts: cada mensaje
    es un viaje al buzon de un personaje concreto. Las cifras van en neto, que
    es lo que de verdad te llega tras la comision de la casa de subastas.
    """
    if not ventas:
        return []

    shown = list(ventas[:MAX_DEALS_PER_RUN])

    por_personaje: dict[tuple[str, str, object], list[Venta]] = {}
    for venta in shown:
        clave = (
            venta.subasta.character,
            venta.subasta.realm,
            venta.subasta.account,
        )
        por_personaje.setdefault(clave, []).append(venta)

    messages: list[dict[str, Any]] = []
    for (character, _realm, account), suyas in _en_orden(por_personaje, orden):
        quien = f"💰 {character}"
        if account is not None:
            quien += f" · WoW {account}"

        plural = "ventas" if len(suyas) != 1 else "venta"
        titulo = f"{quien} — {len(suyas)} {plural}"
        continuacion = f"{quien} · sigue"

        lineas = [_venta_line(v) for v in suyas]
        if len(suyas) > 1:
            total = sum(v.neto_gold for v in suyas)
            lineas.append(f"**Total: {format_gold(total)} g**")

        grupos = _repartir(lineas, MAX_EMBED_DESCRIPTION)
        for indice, grupo in enumerate(grupos):
            messages.append(
                {
                    "embeds": [
                        {
                            "title": titulo if indice == 0 else continuacion,
                            "description": "\n".join(grupo),
                            "color": COLOR_VENTA,
                            # La hora del volcado en que se noto la
                            # desaparicion, no la del envio. Discord la pinta en
                            # la zona horaria de quien lee.
                            "timestamp": suyas[0].detectada_at.isoformat(),
                        }
                    ]
                }
            )

    return messages


class DiscordNotifier:
    """Cliente minimo del webhook de Discord."""

    def __init__(
        self,
        webhook_url: str,
        session: requests.Session | None = None,
        timeout: int = 15,
        max_retries: int = 3,
        sleep: Any = None,
    ) -> None:
        if not webhook_url:
            raise DiscordError(
                "Falta DISCORD_WEBHOOK_URL.\n"
                "En Discord: Ajustes del canal > Integraciones > Webhooks > "
                "Nuevo webhook > Copiar URL. Ponlo en el fichero .env (en local) "
                "o en los secrets del repositorio (en GitHub Actions)."
            )
        self.webhook_url = webhook_url
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep if sleep is not None else time.sleep

    def send_deals(
        self,
        deals: Sequence[Deal],
        realm_names: Mapping[int, str],
        icon_urls: Mapping[int, str] | None = None,
        snapshot_at: datetime | None = None,
        compradores: Mapping[int, str] | None = None,
    ) -> list[Deal]:
        """Envia los chollos y devuelve exactamente los que se han entregado.

        Devolver la lista, y no un simple recuento, es lo que permite a quien
        llama marcar como avisados solo los que de verdad han salido. Marcarlos
        todos haria desaparecer para siempre los que no cupieron en el aviso.
        """
        entregados: list[Deal] = []
        for message, lleva in _deal_messages(
            deals, realm_names, icon_urls, snapshot_at, compradores
        ):
            try:
                self._post(message)
            except DiscordError as exc:
                # Lo de los mensajes anteriores ya llego.
                exc.entregados = entregados
                raise
            entregados.extend(lleva)
        return entregados

    def send_undercuts(
        self,
        undercuts: Sequence[Undercut],
        ya_avisados: Sequence[Undercut] = (),
        panel_url: str | None = None,
        orden: Mapping[tuple[str, str], int] | None = None,
    ) -> list[Undercut]:
        """Envia los undercuts y devuelve los nuevos que de verdad han salido."""
        # Por identidad y no por igualdad: una ya avisada puede ser igual a una
        # nueva, y esa no es de las que hay que marcar ahora.
        nuevas = {id(u) for u in undercuts}
        entregados: list[Undercut] = []
        for message, lleva in _undercut_messages(
            undercuts, ya_avisados, panel_url, orden
        ):
            try:
                self._post(message)
            except DiscordError as exc:
                exc.entregados = entregados
                raise
            entregados.extend(u for u in lleva if id(u) in nuevas)
        return entregados

    def send_ventas(
        self, ventas: Sequence[Venta], orden: Mapping[tuple[str, str], int] | None = None
    ) -> list[Venta]:
        """Envia las ventas y devuelve las que de verdad han salido."""
        for message in build_venta_messages(ventas, orden):
            self._post(message)
        return list(ventas[:MAX_DEALS_PER_RUN])

    def panel_url(self, message_id: str) -> str | None:
        """Enlace directo al mensaje del panel.

        El panel se crea una vez y se edita en su sitio, asi que nunca sube al
        final del canal y es dificil de encontrar. Con el enlace se llega de un
        clic desde cualquier aviso.

        El id del servidor y el del canal los da el propio webhook; si no
        estuviera en un servidor no habria enlace posible, y entonces se
        devuelve None en vez de montar una url rota.
        """
        try:
            respuesta = self.session.get(self.webhook_url, timeout=self.timeout)
            datos = respuesta.json()
        except (requests.RequestException, requests.exceptions.JSONDecodeError):
            return None

        guild = datos.get("guild_id")
        canal = datos.get("channel_id")
        if not guild or not canal:
            return None
        return f"https://discord.com/channels/{guild}/{canal}/{message_id}"

    def upsert_panel(self, payload: Mapping[str, Any], message_id: str | None) -> str | None:
        """Crea el mensaje del panel o reescribe el que ya existe.

        Devuelve el id del mensaje, que hay que guardar para poder reescribirlo
        en la pasada siguiente en vez de ir dejando uno nuevo cada hora.

        Si el guardado ya no existe (lo borraste, o se perdio la memoria), se
        crea uno nuevo en vez de fallar: el panel es informativo y no merece
        tumbar la pasada.
        """
        if message_id:
            respuesta = self._post_raw(
                f"{self.webhook_url}/messages/{message_id}", payload, method="PATCH"
            )
            if respuesta is not None and respuesta.status_code in (200, 204):
                return message_id
            log.warning(
                "El mensaje del panel %s ya no existe; creo uno nuevo.", message_id
            )

        # wait=true hace que Discord devuelva el mensaje creado, que es de donde
        # sale el id para poder reescribirlo despues.
        respuesta = self._post_raw(f"{self.webhook_url}?wait=true", payload)
        if respuesta is None or respuesta.status_code not in (200, 204):
            log.warning("No he podido publicar el panel.")
            return None

        try:
            return str(respuesta.json().get("id") or "") or None
        except requests.exceptions.JSONDecodeError:
            return None

    def _post_raw(
        self, url: str, payload: Mapping[str, Any], method: str = "POST"
    ) -> requests.Response | None:
        """Peticion suelta al webhook, sin reintentos ni excepciones.

        El panel es un extra: si falla, se avisa en el log y la pasada sigue.
        Los avisos de verdad usan `_post`, que si reintenta y protesta.
        """
        try:
            return self.session.request(
                method, url, json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            log.warning("Fallo hablando con Discord para el panel: %s", exc)
            return None

    def send_warning(self, title: str, text: str) -> None:
        """Aviso sobre el estado del propio bot, no sobre precios."""
        self._post(
            {
                "embeds": [
                    {"title": f"⚠️ {title}", "description": text, "color": COLOR_WARNING}
                ]
            }
        )

    def send_test(self) -> None:
        self._post(
            {
                "content": "✅ Prueba de conexion",
                "embeds": [
                    {
                        "title": "El vigilante de precios puede escribir aqui",
                        "description": (
                            "Si ves este mensaje, el webhook esta bien configurado. "
                            "Los avisos de chollos llegaran a este canal."
                        ),
                        "color": COLOR_STEAL,
                    }
                ],
            }
        )

    def _post(self, payload: Mapping[str, Any]) -> None:
        last_error = "motivo desconocido"
        # Los 429 llevan su propia cuenta: no son un fallo, Discord dice cuanto
        # esperar y despues acepta. Contados con los fallos de verdad, tres 429
        # seguidos en una rafaga tiraban un aviso bueno.
        fallos = 0
        limitados = 0

        while True:
            try:
                response = self.session.post(
                    self.webhook_url, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if response.status_code in (200, 204):
                    self._respetar_ritmo(response)
                    return
                if response.status_code == 429:
                    last_error = "Discord esta limitando los envios (HTTP 429)"
                    limitados += 1
                    if limitados > MAX_ESPERAS_POR_LIMITE:
                        break
                    self._sleep(_discord_retry_after(response))
                    continue
                if response.status_code in (401, 403, 404):
                    raise DiscordError(
                        f"Discord rechaza el webhook (HTTP {response.status_code}). "
                        "Comprueba que la URL es correcta y que el webhook no se "
                        "ha borrado."
                    )
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            if fallos >= self.max_retries:
                break
            self._sleep(2**fallos)
            fallos += 1

        raise DiscordError(f"No he podido enviar el aviso a Discord: {last_error}")

    def _respetar_ritmo(self, response: requests.Response) -> None:
        """Espera si Discord dice que ya no quedan envios en esta ventana.

        Un webhook admite unos pocos mensajes seguidos, y una pasada con muchos
        personajes adelantados manda uno por personaje. Discord dice en cada
        respuesta cuantos quedan y cuando se recargan: esperar al llegar a cero
        es mas rapido y mas limpio que chocar con el 429 y reintentar.
        """
        if response.headers.get("X-RateLimit-Remaining") != "0":
            return
        try:
            espera = float(response.headers.get("X-RateLimit-Reset-After", ""))
        except ValueError:
            return
        if espera > 0:
            self._sleep(min(espera, 60.0))


def _discord_retry_after(response: requests.Response) -> float:
    """Segundos que Discord pide esperar tras un 429."""
    try:
        value = float(response.json().get("retry_after", 1.0))
    except (ValueError, AttributeError, requests.exceptions.JSONDecodeError):
        value = 1.0
    return min(max(value, 0.5), 60.0)


def realm_names_for(deals: Iterable[Deal], lookup) -> dict[int, str]:
    """Resuelve el nombre de cada reino implicado, una sola vez por reino."""
    names: dict[int, str] = {}
    for deal in deals:
        if deal.realm_id not in names:
            names[deal.realm_id] = lookup(deal.realm_id)
    return names
