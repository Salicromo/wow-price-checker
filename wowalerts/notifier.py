"""Envio de avisos a Discord.

La construccion de los embeds es una funcion pura (`build_messages`) para poder
comprobar el formato en los tests sin enviar nada, y el envio real es una capa
fina encima.
"""

from __future__ import annotations

import logging
import os
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

    El ancla final no le dice nada a Wowhead, pero hace que cada embed tenga una
    url distinta. Discord fusiona en uno solo los embeds de un mismo mensaje que
    comparten url (es su galeria de imagenes), y sin esto varias subastas del
    mismo objeto se veian como una sola.

    Las mascotas van por /pet: todas comparten el objeto 82800, asi que un
    enlace /item las llevaria a la jaula vacia en vez de a la mascota.
    """
    destino = (
        f"pet={deal.pet_species_id}"
        if deal.pet_species_id is not None
        else f"item={deal.item_id}"
    )
    return f"https://www.wowhead.com/{destino}#a{deal.auction_id}"


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


def build_embed(
    deal: Deal,
    realm_name: str,
    icon_url: str | None = None,
    snapshot_at: datetime | None = None,
    quien_compra: str | None = None,
) -> dict[str, Any]:
    """Tarjeta de Discord para un chollo."""
    if deal.sin_ilvl:
        # Un patron no escala, asi que no hay ilvl del que hablar. El separador
        # viaja dentro del texto para no dejar un punto suelto colgando.
        ilvl_text = ""
    elif deal.ilvl_confirmed:
        ilvl_text = f"  ·  ilvl **{deal.ilvl}**"
    else:
        ilvl_text = "  ·  ilvl **sin confirmar**"

    description = (
        f"**{format_gold(deal.price_gold)} de oro**{ilvl_text}\n"
        f"Un {deal.discount_pct:.0f}% por debajo de tu limite "
        f"({format_gold(deal.threshold_gold)} de oro)."
    )
    if not deal.ilvl_confirmed and not deal.sin_ilvl:
        description += (
            "\n\n> No he podido determinar el ilvl de esta subasta, asi que la "
            "he comparado con tu precio mas bajo para ese objeto. Comprueba el "
            "ilvl en el juego antes de comprar."
        )

    fields = [
        {"name": "Reino", "value": realm_name, "inline": True},
        {
            "name": "Tiempo restante",
            "value": _time_left_label(deal.time_left),
            "inline": True,
        },
    ]
    if deal.quantity > 1:
        fields.append(
            {"name": "Cantidad", "value": str(deal.quantity), "inline": True}
        )
    if quien_compra:
        # Un chollo en un reino donde no tienes a nadie no se puede comprar, y
        # saberlo antes de abrir el juego ahorra el viaje.
        fields.append({"name": "Ir con", "value": quien_compra, "inline": False})

    # Cuando el aviso llega y ves que a ese precio no era chollo, lo que sobra es
    # el tope, no la subasta. Esto lleva al formulario con el objeto y el ilvl
    # ya puestos, para corregirlo sin abrir config.yaml.
    fields.append({
        "name": "Ajustar tope",
        "value": f"[cambiar el limite]({_ajustar_tope_url(deal)})",
        "inline": False,
    })

    embed: dict[str, Any] = {
        "title": deal.item_name,
        # El ancla final no le dice nada a Wowhead, pero hace que cada embed
        # tenga una url distinta. Discord fusiona en uno solo los embeds de un
        # mismo mensaje que comparten url (es su galeria de imagenes), y sin
        # esto varias subastas del mismo objeto se veian como una sola.
        "url": _wowhead_url(deal),
        "color": _color_for(deal),
        "description": description,
        "fields": fields,
        "footer": {"text": f"Subasta {deal.auction_id} · reino {deal.realm_id}"},
    }

    if icon_url:
        embed["thumbnail"] = {"url": icon_url}

    if snapshot_at:
        # Discord lo pinta junto al pie y lo convierte a la zona horaria de cada
        # lector. Es la hora del volcado de Blizzard, no la del envio: lo que
        # importa es cuando se vio ese precio.
        # Discord pinta el pie como "texto • fecha", asi que el texto se corta
        # aqui para que se lea "... · precio visto • 30/08/2026 13:31".
        embed["timestamp"] = snapshot_at.isoformat()
        embed["footer"]["text"] += " · precio visto"

    return embed


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
    """Convierte los chollos en mensajes listos para el webhook.

    Se agrupan de diez en diez (el maximo que admite Discord por mensaje) y se
    recorta a `MAX_DEALS_PER_RUN`, avisando de cuantos quedan pendientes.
    """
    if not deals:
        return []

    shown = deals_to_send(deals)
    omitted = len(deals) - len(shown)

    plural = "chollos" if len(shown) != 1 else "chollo"
    header = f"🚨 **{len(shown)} {plural}** por debajo de tus precios"
    if omitted:
        header += f" (y {omitted} mas que te envio en la proxima pasada)"

    messages: list[dict[str, Any]] = []
    for start in range(0, len(shown), MAX_EMBEDS_PER_MESSAGE):
        chunk = shown[start : start + MAX_EMBEDS_PER_MESSAGE]
        message: dict[str, Any] = {
            "embeds": [
                build_embed(
                    deal,
                    realm_names.get(deal.realm_id, f"Reino {deal.realm_id}"),
                    (icon_urls or {}).get(deal.item_id),
                    snapshot_at,
                    (compradores or {}).get(deal.realm_id),
                )
                for deal in chunk
            ]
        }
        if start == 0:
            message["content"] = header
        messages.append(message)

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
        linea = f"### • {character} — {len(suyas)}"
        # Las caras son las que mas merece la pena ir a recolocar primero.
        caras = sum(1 for u in suyas if u.my_price_gold > UNDERCUT_CARO_GOLD)
        if caras:
            linea += f" (💰 {caras})"
        por_cuenta.setdefault(account, []).append(linea)

    bloques = []
    for account, lineas in por_cuenta.items():
        cabecera = f"## WoW {account}" if account is not None else "## Otros"
        bloques.append("\n".join([cabecera, *lineas]))
    descripcion = "\n\n".join(bloques)
    if panel_url:
        descripcion += f"\n\n[📊 Ver el panel con todas]({panel_url})"

    plural = "subastas" if len(todas) != 1 else "subasta"
    mensaje = {
        "embeds": [
            {
                "title": f"⚔️ Te han adelantado — {len(todas)} {plural}",
                "description": descripcion,
                "color": COLOR_UNDERCUT,
            }
        ]
    }
    return [(mensaje, todas)]


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
        messages = build_messages(
            deals, realm_names, icon_urls, snapshot_at, compradores
        )
        shown = deals_to_send(deals)
        for indice, message in enumerate(messages):
            try:
                self._post(message)
            except DiscordError as exc:
                # Van de diez en diez: lo de los mensajes anteriores ya llego.
                exc.entregados = shown[: indice * MAX_EMBEDS_PER_MESSAGE]
                raise
        return shown

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
