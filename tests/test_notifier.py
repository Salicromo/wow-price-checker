import re

import pytest
import requests

from wowalerts.config import COPPER_PER_GOLD
from wowalerts.notifier import (
    COLOR_STEAL,
    COLOR_UNCONFIRMED,
    MAX_DEALS_PER_RUN,
    DiscordError,
    DiscordNotifier,
    _embed_chars,
    build_messages,
    format_gold,
    realm_names_for,
)
from wowalerts.scanner import Deal

WEBHOOK = "https://discord.com/api/webhooks/1/abc"
REALMS = {1305: "Dun Modr / Sanguino"}


def make_deal(
    auction_id=1,
    price_gold=45_000,
    threshold_gold=90_000,
    confirmed=True,
    ilvl=311,
    item_id=5000,
    item_name="Greaves of the Noxious Depths",
    realm_id=1305,
    time_left="VERY_LONG",
):
    return Deal(
        auction_id=auction_id,
        item_id=item_id,
        item_name=item_name,
        ilvl=ilvl if confirmed else None,
        ilvl_confirmed=confirmed,
        price_copper=price_gold * COPPER_PER_GOLD,
        threshold_copper=threshold_gold * COPPER_PER_GOLD,
        realm_id=realm_id,
        time_left=time_left,
    )


def tarjetas(deals, realms=REALMS, **kwargs):
    return [e for m in build_messages(deals, realms, **kwargs) for e in m["embeds"]]


def lineas(embed):
    """Las lineas de subasta, sin los subtitulos de objeto."""
    return [l for l in embed["description"].splitlines() if l.startswith("• ")]


def subtitulos(embed):
    return [l for l in embed["description"].splitlines() if l.startswith("**[")]


def test_formato_de_oro_a_la_espanola():
    assert format_gold(1_234_567) == "1.234.567"
    assert format_gold(999) == "999"


def test_el_subtitulo_lleva_objeto_ilvl_y_tope_y_la_linea_precio_y_reino():
    embed = tarjetas([make_deal()])[0]

    assert embed["color"] == COLOR_STEAL
    [subtitulo] = subtitulos(embed)
    assert subtitulo.startswith(
        "**[Greaves of the Noxious Depths (311)](https://www.wowhead.com/item=5000)** · [tope 90.000]("
    )
    assert lineas(embed) == ["• **45.000 g** (−50%) · Dun Modr / Sanguino"]


def test_el_aviso_avisa_cuando_el_ilvl_no_esta_confirmado():
    embed = tarjetas([make_deal(confirmed=False)])[0]

    assert "Greaves of the Noxious Depths (ilvl ⚠️)" in subtitulos(embed)[0]
    assert "antes de comprar" in embed["description"]
    assert embed["color"] == COLOR_UNCONFIRMED


def test_una_sola_tarjeta_con_un_subtitulo_por_objeto_e_ilvl():
    """Agrupar evita una tarjeta por subasta y el scroll sin fin."""
    deals = [
        make_deal(1, ilvl=308),
        make_deal(2, item_id=6000, item_name="Venom Rite Mantle", ilvl=308),
        make_deal(3, ilvl=328),
        make_deal(4, ilvl=308, price_gold=40_000),
        make_deal(5, confirmed=False),
        make_deal_sin_ilvl(),
    ]

    messages = build_messages(deals, REALMS)

    assert len(messages) == 1
    [embed] = messages[0]["embeds"]
    nombres = [s.split("](")[0].lstrip("*[") for s in subtitulos(embed)]
    # De mayor a menor ilvl; el dudoso y lo que no escala, al final.
    assert nombres == [
        "Greaves of the Noxious Depths (328)",
        "Greaves of the Noxious Depths (308)",
        "Venom Rite Mantle (308)",
        "Greaves of the Noxious Depths (ilvl ⚠️)",
        "Pattern: Arcanoweave Cord",
    ]
    assert len(lineas(embed)) == len(deals)


def test_dentro_de_un_objeto_las_subastas_van_de_mas_barata_a_mas_cara():
    embed = tarjetas([make_deal(1, price_gold=50_000), make_deal(2, price_gold=40_000)])[0]

    assert [l.split("**")[1] for l in lineas(embed)] == ["40.000 g", "50.000 g"]


def test_dentro_de_un_objeto_van_por_cuenta_y_luego_por_precio():
    """Primero todo lo de WoW 1, despues WoW 2 y despues WoW 3: es el orden en
    que entras, y mezclarlas obligaba a saltar de cuenta en cuenta."""
    deals = [
        make_deal(1, price_gold=10_000, realm_id=1),
        make_deal(2, price_gold=12_000, realm_id=2),
        make_deal(3, price_gold=12_000, realm_id=3),
        make_deal(4, price_gold=11_000, realm_id=4),
        make_deal(5, price_gold=9_000, realm_id=5),
    ]
    compradores = {
        1: "Ийфьордщ · WoW 1",
        2: "Nemesigoldu · WoW 2",
        3: "Жнецце · WoW 1",
        4: "Kbardan · WoW 3\nRavengoldu · WoW 1",
        5: "Twistgoldus · WoW 3",
    }

    embed = tarjetas(deals, compradores=compradores)[0]

    assert [l.split(") · ")[1] for l in lineas(embed)] == [
        "Ийфьордщ · WoW 1",
        "Kbardan · WoW 3, Ravengoldu · WoW 1",
        "Жнецце · WoW 1",
        "Nemesigoldu · WoW 2",
        "Twistgoldus · WoW 3",
    ]


def test_cada_linea_dice_con_quien_ir_en_lugar_del_reino():
    embed = tarjetas(
        [make_deal(1), make_deal(2, realm_id=1084)],
        realms={**REALMS, 1084: "Dentarg / Tarren Mill"},
        compradores={1305: "Pepe · WoW 1\nJuan · WoW 3", 1084: "Ana · WoW 2"},
    )[0]

    assert lineas(embed) == [
        "• **45.000 g** (−50%) · Pepe · WoW 1, Juan · WoW 3",
        "• **45.000 g** (−50%) · Ana · WoW 2",
    ]
    assert "Dun Modr" not in embed["description"]


def test_el_tiempo_restante_solo_sale_cuando_aprieta():
    largo = tarjetas([make_deal(time_left="VERY_LONG")])[0]
    corto = tarjetas([make_deal(time_left="MEDIUM")])[0]

    assert "⏳" not in largo["description"]
    assert lineas(corto)[0].endswith("· ⏳ 30 min - 2 h")


def test_el_icono_solo_cuando_la_tarjeta_es_un_unico_objeto():
    icono = {5000: "https://icono/5000.jpg"}
    solo = tarjetas([make_deal(1), make_deal(2)], icon_urls=icono)[0]
    mezcla = tarjetas([make_deal(1), make_deal(2, item_id=5002)], icon_urls=icono)[0]

    assert solo["thumbnail"] == {"url": "https://icono/5000.jpg"}
    assert "thumbnail" not in mezcla


def test_sin_chollos_no_se_genera_ningun_mensaje():
    assert build_messages([], REALMS) == []


def test_un_solo_mensaje_con_cabecera_para_pocos_chollos():
    messages = build_messages([make_deal(1), make_deal(2)], REALMS)

    assert len(messages) == 1
    assert "2 chollos" in messages[0]["content"]
    assert len(messages[0]["embeds"]) == 1
    assert len(lineas(messages[0]["embeds"][0])) == 2


def test_cabecera_en_singular_con_un_solo_chollo():
    messages = build_messages([make_deal()], REALMS)
    assert "1 chollo" in messages[0]["content"]
    assert "chollos" not in messages[0]["content"]


def test_muchos_chollos_respetan_los_limites_de_discord():
    deals = [
        make_deal(i, item_id=i, item_name=f"Objeto con un nombre largo {i}")
        for i in range(MAX_DEALS_PER_RUN)
    ]

    messages = build_messages(deals, REALMS, compradores={1305: "Pepe · WoW 1"})

    assert len(messages) > 1
    assert sum(len(lineas(e)) for m in messages for e in m["embeds"]) == len(deals)
    for m in messages:
        assert len(m["embeds"]) <= 10
        assert sum(_embed_chars(e) for e in m["embeds"]) + len(m.get("content", "")) <= 6000
        assert all(len(e["description"]) <= 4096 for e in m["embeds"])
    # Solo el primer mensaje lleva cabecera, para no repetirla.
    assert "content" in messages[0]
    assert all("content" not in m for m in messages[1:])


def test_un_objeto_partido_entre_tarjetas_repite_su_subtitulo():
    """Ninguna linea queda sin saber de que objeto es."""
    deals = [make_deal(i) for i in range(30)]

    embeds = tarjetas(deals)

    assert len(embeds) > 1
    assert all(e["description"].startswith("**[Greaves") for e in embeds)
    assert sum(len(lineas(e)) for e in embeds) == 30


def test_se_recorta_y_se_avisa_de_los_omitidos():
    messages = build_messages([make_deal(i) for i in range(MAX_DEALS_PER_RUN + 7)], REALMS)

    total = sum(len(lineas(e)) for m in messages for e in m["embeds"])
    assert total == MAX_DEALS_PER_RUN
    assert "7 mas" in messages[0]["content"]


def test_reino_desconocido_se_muestra_por_su_id():
    embed = tarjetas([make_deal()], realms={})[0]
    assert "Reino 1305" in embed["description"]


def test_realm_names_for_consulta_una_vez_por_reino():
    llamadas = []

    def lookup(realm_id):
        llamadas.append(realm_id)
        return f"Reino {realm_id}"

    deals = [make_deal(1), make_deal(2), make_deal(3)]
    names = realm_names_for(deals, lookup)

    assert llamadas == [1305]
    assert names == {1305: "Reino 1305"}


def test_webhook_vacio_da_un_error_explicativo():
    with pytest.raises(DiscordError, match="DISCORD_WEBHOOK_URL"):
        DiscordNotifier("")


def test_envio_correcto(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    deal = make_deal()
    assert notifier.send_deals([deal], REALMS) == [deal]
    assert requests_mock.call_count == 1


def test_send_deals_devuelve_solo_lo_que_ha_salido(requests_mock):
    """Con mas chollos de los que caben, devuelve unicamente los enviados.

    Quien llama marca como avisados los devueltos: si devolviera todos, los
    que no cupieron quedarian marcados sin haberse enviado y no volverian a
    notificarse nunca.
    """
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    deals = [make_deal(auction_id=i) for i in range(MAX_DEALS_PER_RUN + 7)]

    enviados = notifier.send_deals(deals, REALMS)

    assert len(enviados) == MAX_DEALS_PER_RUN
    assert enviados == deals[:MAX_DEALS_PER_RUN]


def test_reintenta_cuando_discord_limita_los_envios(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        [
            {"status_code": 429, "json": {"retry_after": 0.5}},
            {"status_code": 204},
        ],
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_deals([make_deal()], REALMS)

    assert esperas == [0.5]
    assert requests_mock.call_count == 2


def test_un_webhook_borrado_falla_sin_reintentar(requests_mock):
    requests_mock.post(WEBHOOK, status_code=404)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=lambda _: None)

    with pytest.raises(DiscordError, match="rechaza el webhook"):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 1


def test_se_rinde_tras_agotar_los_reintentos(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=2, sleep=lambda _: None
    )

    with pytest.raises(DiscordError):
        notifier.send_deals([make_deal()], REALMS)
    assert requests_mock.call_count == 3


def test_mensaje_de_prueba(requests_mock):
    requests_mock.post(WEBHOOK, status_code=204)
    DiscordNotifier(WEBHOOK, session=requests.Session()).send_test()

    assert "Prueba de conexion" in requests_mock.last_request.json()["content"]


# -- Avisos de undercut -----------------------------------------------------

from wowalerts.misubastas import MyAuction
from wowalerts.notifier import COLOR_UNDERCUT, build_undercut_messages
from wowalerts.undercut import Undercut


def un_undercut(
    objeto="Grebas de las profundidades nocivas",
    oro_mio=9000,
    oro_rival=8000,
    personaje="Pepe",
    reino="Sanguino",
    cuenta=2,
    auction_id=1,
    ilvl=311,
):
    mine = MyAuction(
        auction_id=auction_id,
        item_id=200000,
        item_name=objeto,
        ilvl=ilvl,
        buyout_copper=oro_mio * 10_000,
        quantity=1,
        character=personaje,
        realm=reino,
        realm_slug=reino.lower(),
        account=cuenta,
    )
    return Undercut(
        mine=mine,
        realm_id=1379,
        rival_auction_id=99,
        rival_price_copper=oro_rival * 10_000,
        rivals_ahead=1,
    )


def texto(mensaje) -> str:
    """Todo el texto de la tarjeta, junto, para poder buscar en el.

    Cada columna sale como su nombre y debajo su contenido.
    """
    embed = mensaje["embeds"][0]
    partes = [embed["title"], embed.get("description", "")]
    partes += [f"{c['name']}\n{c['value']}" for c in embed.get("fields", [])]
    return "\n".join(partes)


def test_sin_undercuts_no_hay_mensajes():
    assert build_undercut_messages([]) == []


def test_todo_va_en_un_solo_mensaje():
    mensajes = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", auction_id=1),
            un_undercut(personaje="Ana", auction_id=2),
            un_undercut(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 1


def test_cada_personaje_sale_una_vez_con_su_recuento():
    contenido = texto(
        build_undercut_messages(
            [
                un_undercut(personaje="Pepe", auction_id=1),
                un_undercut(personaje="Ana", auction_id=2),
                un_undercut(personaje="Pepe", auction_id=3),
            ]
        )[0]
    )
    assert "• Pepe — 2" in contenido
    assert "• Ana — 1" in contenido
    assert contenido.count("Pepe") == 1


def test_no_lleva_el_detalle_de_cada_subasta():
    """Solo que personajes: el detalle esta en la ventana del addon."""
    contenido = texto(build_undercut_messages([un_undercut(objeto="Grebas")])[0])
    assert "Grebas" not in contenido
    assert "Sanguino" not in contenido


def test_los_personajes_van_agrupados_por_cuenta():
    contenido = texto(
        build_undercut_messages(
            [
                un_undercut(personaje="Pepe", cuenta=3, auction_id=1),
                un_undercut(personaje="Ana", cuenta=2, auction_id=2),
            ]
        )[0]
    )
    assert "WoW 3\n• Pepe" in contenido
    assert "WoW 2\n• Ana" in contenido


def test_el_orden_de_personajes_decide_tambien_el_de_las_cuentas():
    orden = {("Ana", "Sanguino"): 0, ("Pepe", "Sanguino"): 1}
    contenido = texto(
        build_undercut_messages(
            [
                un_undercut(personaje="Pepe", cuenta=3, auction_id=1),
                un_undercut(personaje="Ana", cuenta=2, auction_id=2),
            ],
            orden=orden,
        )[0]
    )
    assert contenido.index("WoW 2") < contenido.index("WoW 3")


def test_el_mismo_personaje_en_cuentas_distintas_sale_en_cada_una():
    contenido = texto(
        build_undercut_messages(
            [
                un_undercut(personaje="Pepe", cuenta=1, auction_id=1),
                un_undercut(personaje="Pepe", cuenta=3, auction_id=2),
            ]
        )[0]
    )
    assert contenido.count("• Pepe — 1") == 2


def test_sin_cuenta_conocida_va_aparte():
    contenido = texto(build_undercut_messages([un_undercut(cuenta=None)])[0])
    assert "• Pepe — 1" in contenido
    assert "WoW" not in contenido


def test_el_total_va_en_el_titulo():
    mensajes = build_undercut_messages(
        [un_undercut(auction_id=1), un_undercut(auction_id=2)]
    )
    assert "2 subastas" in mensajes[0]["embeds"][0]["title"]


def test_una_sola_subasta_va_en_singular():
    titulo = build_undercut_messages([un_undercut()])[0]["embeds"][0]["title"]
    assert "1 subasta" in titulo
    assert "subastas" not in titulo


def test_las_ya_avisadas_cuentan_con_las_nuevas():
    """El numero es lo que hay adelantado ahora, no solo lo nuevo."""
    ya = [
        un_undercut(auction_id=7),
        un_undercut(personaje="Ana", auction_id=8),
    ]
    contenido = texto(
        build_undercut_messages([un_undercut(auction_id=1)], ya_avisados=ya)[0]
    )
    assert "3 subastas" in contenido
    assert "• Pepe — 2" in contenido
    assert "• Ana — 1" in contenido


def test_sin_ninguna_nueva_no_se_avisa_de_las_ya_avisadas():
    """Si no hay novedad, el mismo aviso cada pasada seria ruido."""
    ya = [un_undercut(objeto="Zapatillas", auction_id=7)]
    assert build_undercut_messages([], ya_avisados=ya) == []


def test_no_hay_tope_de_subastas():
    """Con un personaje por linea caben todas: el recuento es el de verdad."""
    muchas = [un_undercut(auction_id=i) for i in range(1, 121)]
    mensajes = build_undercut_messages(muchas)
    assert len(mensajes) == 1
    assert "• Pepe — 120" in texto(mensajes[0])


def test_se_marcan_las_de_mas_de_80k():
    contenido = texto(
        build_undercut_messages(
            [
                un_undercut(oro_mio=120_000, oro_rival=110_000, auction_id=1),
                un_undercut(oro_mio=80_001, oro_rival=80_001, auction_id=2),
                un_undercut(oro_mio=80_000, oro_rival=70_000, auction_id=3),
            ]
        )[0]
    )
    assert "• Pepe — 3 (💰 2)" in contenido


def test_sin_ninguna_cara_no_se_marca_nada():
    contenido = texto(build_undercut_messages([un_undercut(oro_mio=9000)])[0])
    assert "💰" not in contenido


def test_una_columna_por_cuenta_lado_a_lado():
    mensaje = build_undercut_messages(
        [
            un_undercut(personaje="Pepe", cuenta=2, auction_id=1),
            un_undercut(personaje="Ana", cuenta=3, auction_id=2),
        ]
    )[0]
    embed = mensaje["embeds"][0]
    assert embed["color"] == COLOR_UNDERCUT
    assert [c["name"] for c in embed["fields"]] == ["WoW 2", "WoW 3"]
    assert all(c["inline"] for c in embed["fields"])
    assert "#" not in texto(mensaje)


# -- Panel de estado --------------------------------------------------------

from wowalerts.notifier import COLOR_UNDERCUT, build_undercut_messages as _bum  # noqa: F401

PANEL = {"embeds": [{"title": "📊 Tus subastas"}]}


def test_el_panel_se_crea_la_primera_vez_y_devuelve_su_id(requests_mock):
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "12345"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) == "12345"


def test_el_panel_reescribe_el_mensaje_que_ya_existe(requests_mock):
    editar = requests_mock.patch(WEBHOOK + "/messages/12345", status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "12345") == "12345"
    assert editar.call_count == 1


def test_si_el_mensaje_del_panel_ya_no_existe_se_crea_otro(requests_mock):
    """Lo puedes haber borrado, o haberse perdido la memoria entre pasadas."""
    requests_mock.patch(WEBHOOK + "/messages/viejo", status_code=404)
    requests_mock.post(WEBHOOK + "?wait=true", json={"id": "nuevo"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, "viejo") == "nuevo"


def test_un_fallo_del_panel_no_tumba_la_pasada(requests_mock):
    """El panel es un extra; los avisos son lo importante."""
    requests_mock.post(WEBHOOK + "?wait=true", status_code=500)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())

    assert notifier.upsert_panel(PANEL, None) is None


# -- Avisos de venta --------------------------------------------------------

from datetime import datetime, timezone

from wowalerts.notifier import COLOR_VENTA, build_venta_messages
from wowalerts.ventas import SubastaVigilada, Venta

CUANDO = datetime(2026, 8, 31, 14, 31, tzinfo=timezone.utc)


def una_venta(
    objeto="Grebas de las profundidades nocivas",
    personaje="Pepe",
    cuenta=3,
    oro=10000,
    auction_id=1,
    cantidad=1,
    ilvl=295,
):
    return Venta(
        subasta=SubastaVigilada(
            auction_id=auction_id,
            item_id=200000,
            item_name=objeto,
            ilvl=ilvl,
            buyout_copper=oro * 10_000,
            quantity=cantidad,
            character=personaje,
            realm="Sanguino",
            account=cuenta,
            no_caduca_antes_de=CUANDO,
            visto_at=CUANDO,
        ),
        realm_id=1305,
        detectada_at=CUANDO,
        ah_cut_pct=5,
    )


def test_sin_ventas_no_hay_mensajes():
    assert build_venta_messages([]) == []


def test_una_venta_muestra_el_neto():
    contenido = texto(build_venta_messages([una_venta(oro=10000)])[0])
    assert "9.500 g" in contenido


def test_el_titulo_lleva_personaje_y_cuenta():
    mensaje = build_venta_messages([una_venta()])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe · WoW 3 — 1 venta"


def test_sin_cuenta_el_titulo_solo_lleva_el_personaje():
    mensaje = build_venta_messages([una_venta(cuenta=None)])[0]
    assert mensaje["embeds"][0]["title"] == "💰 Pepe — 1 venta"


def test_una_sola_venta_no_lleva_total():
    contenido = texto(build_venta_messages([una_venta()])[0])
    assert "Total" not in contenido


def test_varias_ventas_del_mismo_personaje_llevan_total():
    mensajes = build_venta_messages(
        [
            una_venta(objeto="Grebas", oro=10000, auction_id=1),
            una_venta(objeto="Zapatillas", oro=20000, auction_id=2),
        ]
    )
    assert len(mensajes) == 1
    # 9.500 + 19.000
    assert "Total: 28.500 g" in texto(mensajes[0])


def test_cada_personaje_va_en_su_mensaje():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", auction_id=1),
            una_venta(personaje="Ana", auction_id=2),
            una_venta(personaje="Pepe", auction_id=3),
        ]
    )
    assert len(mensajes) == 2


def test_el_mismo_nombre_en_cuentas_distintas_no_se_mezcla():
    mensajes = build_venta_messages(
        [
            una_venta(personaje="Pepe", cuenta=1, auction_id=1),
            una_venta(personaje="Pepe", cuenta=3, auction_id=2),
        ]
    )
    assert len(mensajes) == 2


def test_el_embed_lleva_color_y_hora_del_volcado():
    embed = build_venta_messages([una_venta()])[0]["embeds"][0]
    assert embed["color"] == COLOR_VENTA
    assert embed["timestamp"] == CUANDO.isoformat()


def test_una_venta_de_varias_unidades_lo_dice():
    contenido = texto(build_venta_messages([una_venta(cantidad=5)])[0])
    assert "×5" in contenido


def test_muchas_ventas_de_un_personaje_se_trocean():
    """Discord tiene un tope por mensaje; el segundo se marca como sigue."""
    muchas = [una_venta(auction_id=i) for i in range(25)]
    mensajes = build_venta_messages(muchas)
    assert len(mensajes) > 1
    assert mensajes[1]["embeds"][0]["title"] == "💰 Pepe · WoW 3 · sigue"


# -- Enlace al panel --------------------------------------------------------


def test_el_enlace_del_panel_se_monta_con_los_tres_ids(requests_mock):
    requests_mock.get(
        WEBHOOK, json={"guild_id": "111", "channel_id": "222"}, status_code=200
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    assert (
        notifier.panel_url("333") == "https://discord.com/channels/111/222/333"
    )


def test_sin_guild_no_hay_enlace(requests_mock):
    """Un webhook fuera de un servidor no da guild_id; mejor sin enlace."""
    requests_mock.get(WEBHOOK, json={"channel_id": "222"}, status_code=200)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    assert notifier.panel_url("333") is None


def test_el_enlace_del_panel_va_al_final():
    mensajes = build_undercut_messages(
        [un_undercut()], panel_url="https://discord.com/channels/1/2/3"
    )
    assert mensajes[0]["embeds"][0]["description"] == (
        "[📊 Ver el panel con todas](https://discord.com/channels/1/2/3)"
    )


def make_deal_sin_ilvl(price_gold=45_000, threshold_gold=60_000):
    return Deal(
        auction_id=7,
        item_id=5001,
        item_name="Pattern: Arcanoweave Cord",
        ilvl=None,
        ilvl_confirmed=False,
        price_copper=price_gold * COPPER_PER_GOLD,
        threshold_copper=threshold_gold * COPPER_PER_GOLD,
        realm_id=1305,
        time_left="LONG",
        sin_ilvl=True,
    )


def test_un_objeto_sin_ilvl_no_se_avisa_como_ilvl_sin_confirmar():
    embed = tarjetas([make_deal_sin_ilvl()])[0]

    assert "ilvl" not in subtitulos(embed)[0].split("](")[0]
    assert "sin confirmar" not in embed["description"]
    # Y no sale en gris: el precio es tan fiable como el de cualquier otro.
    assert embed["color"] != COLOR_UNCONFIRMED


# ----------------------------------------------------------------------------
#  El enlace para ajustar el tope sin abrir config.yaml
# ----------------------------------------------------------------------------

def _url_tope(deal):
    """El enlace del tope, que va en el subtitulo del objeto."""
    [subtitulo] = subtitulos(tarjetas([deal])[0])
    return re.search(r"\[tope [^\]]+\]\(([^)]+)\)", subtitulo).group(1)


def test_el_aviso_lleva_enlace_para_ajustar_el_tope():
    from urllib.parse import parse_qs, urlparse

    partes = urlparse(_url_tope(make_deal()))
    assert partes.path.endswith("/issues/new")

    query = parse_qs(partes.query)
    assert query["template"] == ["tope-aviso.yml"]
    assert query["objeto"] == ["Greaves of the Noxious Depths"]
    assert query["ilvl"] == ["311"]


def test_el_enlace_escapa_lo_que_haga_falta():
    """Los nombres llevan apostrofos y espacios; sin escapar, la URL se rompe."""
    from urllib.parse import parse_qs, urlparse

    url = _url_tope(make_deal(item_name="Temple Delver's Mystic Helm"))
    assert " " not in url
    query = parse_qs(urlparse(url).query)
    assert query["objeto"] == ["Temple Delver's Mystic Helm"]


def test_un_chollo_de_precio_unico_no_lleva_ilvl_en_el_enlace():
    from urllib.parse import parse_qs, urlparse

    deal = make_deal()
    deal = type(deal)(**{**deal.__dict__, "sin_ilvl": True, "ilvl": None})

    assert "ilvl" not in parse_qs(urlparse(_url_tope(deal)).query)


def test_un_ilvl_sin_confirmar_no_lleva_ilvl_en_el_enlace():
    """Con el ilvl en duda, prerrellenarlo invitaria a cambiar el tope del que no es."""
    from urllib.parse import parse_qs, urlparse

    url = _url_tope(make_deal(confirmed=False))
    assert "ilvl" not in parse_qs(urlparse(url).query)


def test_el_repositorio_sale_del_entorno_en_actions(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "otro/repo")

    assert "github.com/otro/repo/issues/new" in _url_tope(make_deal())


# -- El ilvl en las lineas de venta ----------------------------


def test_una_receta_vendida_no_lleva_ilvl():
    contenido = texto(build_venta_messages([una_venta(objeto="Patrón: cordón", ilvl=1)])[0])
    assert "Patrón: cordón —" in contenido
    assert "(1)" not in contenido


def test_una_venta_de_equipo_si_lleva_el_ilvl():
    contenido = texto(build_venta_messages([una_venta(ilvl=295)])[0])
    assert "Grebas de las profundidades nocivas (295)" in contenido


# -- Ritmo de envio ---------------------------------------------------------


def test_si_discord_dice_que_no_quedan_envios_espera_antes_del_siguiente(requests_mock):
    """Con muchos personajes adelantados salen rafagas de mensajes, y el webhook
    solo admite unos pocos seguidos. Discord dice en cada respuesta cuantos
    quedan: esperando cuando llega a cero no se llega a chocar con el 429."""
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "1.25"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == [1.25]


def test_si_quedan_envios_no_espera(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "3", "X-RateLimit-Reset-After": "1.25"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == []


def test_unas_cabeceras_raras_no_rompen_el_envio(requests_mock):
    esperas = []
    requests_mock.post(
        WEBHOOK,
        status_code=204,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "mucho"},
    )
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=esperas.append)

    notifier.send_warning("titulo", "texto")

    assert esperas == []


def test_esperar_al_limite_no_gasta_los_reintentos_de_los_fallos(requests_mock):
    """Un 429 no es un fallo: Discord dice cuanto esperar y luego acepta. Con
    los reintentos contados juntos, tres 429 seguidos tiraban un aviso bueno."""
    requests_mock.post(
        WEBHOOK,
        [{"status_code": 429, "json": {"retry_after": 0.5}}] * 3 + [{"status_code": 204}],
    )
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=2, sleep=lambda _: None
    )

    notifier.send_warning("titulo", "texto")

    assert requests_mock.call_count == 4


def test_un_429_eterno_acaba_rindiendose(requests_mock):
    requests_mock.post(WEBHOOK, status_code=429, json={"retry_after": 0.5})
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session(), sleep=lambda _: None)

    with pytest.raises(DiscordError, match="429"):
        notifier.send_warning("titulo", "texto")


# -- Lo que llega antes de un fallo cuenta como entregado --------------------


def test_si_falla_a_mitad_el_error_dice_que_chollos_si_llegaron(requests_mock, monkeypatch):
    """Si cae el segundo mensaje, los chollos del primero ya estan en
    Discord y hay que poder marcarlos, o la pasada siguiente los repite."""
    requests_mock.post(WEBHOOK, [{"status_code": 204}, {"status_code": 500}])
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )
    # Con un mensaje pequeno, cada tarjeta va en el suyo.
    monkeypatch.setattr("wowalerts.notifier.MAX_CHARS_PER_MESSAGE", 1000)
    deals = [make_deal(auction_id=i) for i in range(30)]
    primero = build_messages(deals, REALMS)[0]
    en_el_primero = sum(len(lineas(e)) for e in primero["embeds"])
    assert 0 < en_el_primero < len(deals)

    with pytest.raises(DiscordError) as fallo:
        notifier.send_deals(deals, REALMS)

    assert fallo.value.entregados == deals[:en_el_primero]


def test_si_falla_el_aviso_de_undercuts_no_se_entrego_ninguno(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )
    pepe = un_undercut(personaje="Pepe", auction_id=1)

    with pytest.raises(DiscordError) as fallo:
        notifier.send_undercuts([pepe])

    assert fallo.value.entregados == []


def test_se_entregan_solo_las_nuevas(requests_mock):
    """Las ya avisadas ya constan: no hay que volver a marcarlas."""
    requests_mock.post(WEBHOOK, status_code=204)
    notifier = DiscordNotifier(WEBHOOK, session=requests.Session())
    pepe = un_undercut(personaje="Pepe", auction_id=1)
    ya = un_undercut(personaje="Pepe", auction_id=3)

    assert notifier.send_undercuts([pepe], ya_avisados=[ya]) == [pepe]


def test_si_falla_el_primero_no_se_entrego_nada(requests_mock):
    requests_mock.post(WEBHOOK, status_code=500)
    notifier = DiscordNotifier(
        WEBHOOK, session=requests.Session(), max_retries=0, sleep=lambda _: None
    )

    with pytest.raises(DiscordError) as fallo:
        notifier.send_deals([make_deal()], REALMS)

    assert fallo.value.entregados == []
