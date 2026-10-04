import pytest
import requests

from wowalerts.blizzard import (
    TOKEN_URL,
    BlizzardAuthError,
    BlizzardClient,
    BlizzardError,
    _realm_id_from_href,
)

AUCTIONS_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/1305/auctions"
INDEX_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/index"
SEARCH_URL = "https://eu.api.blizzard.com/data/wow/search/item"
REALM_URL = "https://eu.api.blizzard.com/data/wow/connected-realm/1305"


@pytest.fixture
def client():
    return BlizzardClient(
        "id", "secret", session=requests.Session(), sleep=lambda _: None
    )


def give_token(requests_mock):
    requests_mock.post(TOKEN_URL, json={"access_token": "tok", "expires_in": 3600})


def test_sin_credenciales_avisa_de_que_faltan():
    client = BlizzardClient("", "", session=requests.Session())
    with pytest.raises(BlizzardAuthError, match="BLIZZARD_CLIENT_ID"):
        _ = client.token


def test_credenciales_rechazadas(requests_mock, client):
    requests_mock.post(TOKEN_URL, status_code=401)
    with pytest.raises(BlizzardAuthError, match="rechaza las credenciales"):
        _ = client.token


def test_el_token_se_pide_una_sola_vez(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, json={"auctions": []})

    client.auctions(1305)
    client.auctions(1305)

    token_calls = [r for r in requests_mock.request_history if r.url.startswith(TOKEN_URL)]
    assert len(token_calls) == 1


def test_las_peticiones_van_firmadas(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, json={"auctions": []})

    client.auctions(1305)

    assert requests_mock.last_request.headers["Authorization"] == "Bearer tok"


def test_reintenta_ante_un_error_temporal(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        [{"status_code": 503}, {"status_code": 200, "json": {"auctions": [{"id": 1}]}}],
    )

    assert client.auctions(1305).auctions == [{"id": 1}]


def test_un_403_pasajero_se_reintenta(requests_mock, client):
    """El 2026-09-02 toda la API dio 403 un minuto y la pasada murio en 21 s.

    Un 403 normalmente significa "no tienes permiso" y no se reintenta, pero con
    Blizzard es pasajero: las credenciales malas de verdad salen como 401 al
    pedir el token, y de eso se encarga BlizzardAuthError.
    """
    give_token(requests_mock)
    requests_mock.get(
        INDEX_URL,
        [
            {"status_code": 403},
            {
                "status_code": 200,
                "json": {"connected_realms": [{"href": f"{REALM_URL}"}]},
            },
        ],
    )

    assert client.connected_realm_ids() == [1305]


def test_lee_la_hora_del_volcado_de_la_cabecera(requests_mock, client):
    """Last-Modified trae la hora del volcado, no la de la respuesta."""
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        json={"auctions": []},
        headers={"Last-Modified": "Sun, 30 Aug 2026 11:31:16 GMT"},
    )

    taken_at = client.auctions(1305).taken_at

    assert taken_at is not None
    assert taken_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-08-30 11:31:16"


def test_el_sondeo_da_la_hora_del_volcado(requests_mock, client):
    """El reloj barato para saber si ya ha salido el volcado de esta hora."""
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        json={"auctions": [{"id": 1}]},
        headers={"Last-Modified": "Wed, 2 Sep 2026 02:23:30 GMT"},
    )

    publicado = client.auction_dump_time(1305)

    assert publicado is not None
    assert publicado.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-02 02:23:30"


def test_el_sondeo_no_se_baja_el_cuerpo(requests_mock, client):
    """Lo que justifica sondear a menudo: la region entera son casi 500 MB.

    Se pide en modo flujo y se cierra tras leer la cabecera, asi que el cuerpo
    no llega a transferirse. Aqui se comprueba lo unico observable desde fuera:
    que la peticion sale con stream activado.
    """
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, json={"auctions": []})

    client.auction_dump_time(1305)

    peticion = requests_mock.request_history[-1]
    assert peticion.path.endswith("/auctions")
    assert peticion.stream is True


def test_un_sondeo_fallido_no_inventa_una_hora(requests_mock, client):
    """None significa "no me consta que haya nada nuevo", que es lo prudente."""
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, status_code=503)

    assert client.auction_dump_time(1305) is None


@pytest.mark.parametrize("cabecera", [None, "", "esto no es una fecha"])
def test_una_cabecera_de_fecha_ausente_o_rara_no_rompe(requests_mock, client, cabecera):
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        json={"auctions": []},
        headers={"Last-Modified": cabecera} if cabecera is not None else {},
    )

    assert client.auctions(1305).taken_at is None


def test_respeta_el_retry_after_de_blizzard(requests_mock):
    esperas = []
    client = BlizzardClient("id", "secret", session=requests.Session(), sleep=esperas.append)
    give_token(requests_mock)
    requests_mock.get(
        AUCTIONS_URL,
        [
            {"status_code": 429, "headers": {"Retry-After": "3"}},
            {"status_code": 200, "json": {"auctions": []}},
        ],
    )

    client.auctions(1305)

    assert esperas == [3.0]


def test_un_reino_que_falla_siempre_lanza_error(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(AUCTIONS_URL, status_code=500)

    with pytest.raises(BlizzardError, match="1305"):
        client.auctions(1305)


def test_lista_de_reinos_conectados(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        INDEX_URL,
        json={
            "connected_realms": [
                {"href": "https://eu.api.blizzard.com/data/wow/connected-realm/1305?namespace=dynamic-eu"},
                {"href": "https://eu.api.blizzard.com/data/wow/connected-realm/509?namespace=dynamic-eu"},
                {"href": "esto no vale"},
            ]
        },
    )

    assert client.connected_realm_ids() == [509, 1305]


def test_nombre_del_reino(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL, json={"realms": [{"name": "Dun Modr"}, {"name": "Sanguino"}]}
    )

    assert client.connected_realm_name(1305) == "Dun Modr / Sanguino"


def test_un_reino_ruso_se_muestra_en_cirilico(requests_mock, client):
    """Asi es como aparece en el juego a quien juega ahi."""
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={
            "realms": [
                {
                    "locale": "ruRU",
                    "name": {"en_GB": "Howling Fjord", "ru_RU": "Ревущий фьорд"},
                }
            ]
        },
    )

    assert client.connected_realm_name(1305) == "Ревущий фьорд"


def test_varios_reinos_rusos_agrupados(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={
            "realms": [
                {"locale": "ruRU", "name": {"en_GB": "Goldrinn", "ru_RU": "Голдринн"}},
                {"locale": "ruRU", "name": {"en_GB": "Greymane", "ru_RU": "Седогрив"}},
            ]
        },
    )

    assert client.connected_realm_name(1305) == "Голдринн / Седогрив"


def test_un_reino_no_ruso_conserva_su_nombre(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={"realms": [{"locale": "enGB", "name": {"en_GB": "Kazzak", "ru_RU": "Каззак"}}]},
    )

    assert client.connected_realm_name(1305) == "Kazzak"


def test_sin_el_idioma_propio_cae_al_del_cliente(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={"realms": [{"locale": "xxYY", "name": {"en_GB": "Silvermoon"}}]},
    )

    assert client.connected_realm_name(1305) == "Silvermoon"


def test_el_nombre_del_reino_se_pide_sin_locale(requests_mock, client):
    """Con locale, Blizzard devuelve un solo idioma y no se puede elegir."""
    give_token(requests_mock)
    requests_mock.get(REALM_URL, json={"realms": []})

    client.connected_realm_name(1305)

    assert "locale" not in requests_mock.last_request.qs


def test_nombre_del_reino_cae_al_id_si_falla(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(REALM_URL, status_code=404)

    assert client.connected_realm_name(1305) == "Reino 1305"


def test_busqueda_exige_coincidencia_exacta_de_nombre(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        SEARCH_URL,
        json={
            "results": [
                {"data": {"id": 1, "name": {"en_GB": "Slitherscale Girdle of Doom"}}},
                {"data": {"id": 2, "name": {"en_GB": "Slitherscale Girdle"}}},
            ]
        },
    )

    assert client.search_item_id("Slitherscale Girdle") == 2


def test_busqueda_sin_coincidencia_devuelve_none(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(SEARCH_URL, json={"results": []})

    assert client.search_item_id("Objeto Inventado") is None


@pytest.mark.parametrize(
    "href,esperado",
    [
        ("https://eu.api.blizzard.com/data/wow/connected-realm/1305?namespace=dynamic-eu", 1305),
        ("https://eu.api.blizzard.com/data/wow/connected-realm/509", 509),
        ("https://eu.api.blizzard.com/data/wow/realm/509", None),
        ("", None),
    ],
)
def test_extraccion_del_id_de_reino(href, esperado):
    assert _realm_id_from_href(href) == esperado


def test_item_names_devuelve_todos_los_idiomas(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/271440",
        json={
            "name": {
                "en_GB": "Greaves of the Noxious Depths",
                "es_ES": "Grebas de las profundidades nocivas",
                "de_DE": "Beinschienen der schädlichen Tiefen",
            }
        },
    )
    nombres = client.item_names(271440)
    assert nombres["es_ES"] == "Grebas de las profundidades nocivas"
    assert len(nombres) == 3


def test_item_names_con_un_nombre_suelto_lo_pone_en_el_locale_del_cliente(
    requests_mock, client
):
    """Algunos objetos vuelven con `name` como cadena y no como diccionario."""
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/1", json={"name": "Suelto"}
    )
    assert client.item_names(1) == {client.locale: "Suelto"}


def test_item_names_de_un_objeto_que_no_existe_es_vacio(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get("https://eu.api.blizzard.com/data/wow/item/2", status_code=404)
    assert client.item_names(2) == {}


def test_item_names_descarta_los_idiomas_vacios(requests_mock, client):
    """Blizzard manda la clave con cadena vacía para idiomas sin traducir."""
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/3",
        json={"name": {"en_GB": "Algo", "ko_KR": "", "it_IT": None}},
    )
    assert client.item_names(3) == {"en_GB": "Algo"}


def test_item_names_se_pide_sin_locale(client, requests_mock):
    """Con locale, Blizzard devuelve un solo idioma y no se puede elegir.

    Es el mismo motivo por el que `connected_realm_name` lo pide sin locale.
    Sin esta comprobación el fallo es invisible: el mock responde con el
    diccionario de idiomas mires lo que mires en la petición.
    """
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/271440",
        json={"name": {"en_GB": "Algo", "es_ES": "Cosa"}},
    )
    client.item_names(271440)
    assert "locale" not in requests_mock.last_request.qs


def test_item_name_sigue_dando_un_solo_idioma(requests_mock, client):
    """El vigilante usa item_name y no se entera de que existe item_names."""
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/4",
        json={"name": {"en_GB": "Solo este", "es_ES": "Este no"}},
    )
    assert client.item_name(4) == "Solo este"


# -- Atributos del objeto ----------------------------------------------------
#
# Los filtros de la casa de subastas (categoria, subcategoria, calidad, hueco,
# nivel) vienen en la MISMA respuesta de la que sale el nombre. `item_names` la
# pedia y tiraba todo menos `name`; esto la aprovecha entera, sin una peticion
# mas por objeto.


def doc_objeto(**cambios):
    doc = {
        "id": 271440,
        "name": {"en_GB": "Greaves of the Noxious Depths"},
        "item_class": {"id": 4, "name": {"en_GB": "Armor", "es_ES": "Armadura"}},
        "item_subclass": {"id": 3, "name": {"en_GB": "Mail", "es_ES": "Malla"}},
        "quality": {"type": "EPIC", "name": {"en_GB": "Epic"}},
        "inventory_type": {"type": "FEET", "name": {"en_GB": "Feet"}},
        "level": 219,
        "required_level": 90,
    }
    doc.update(cambios)
    return doc


def test_los_datos_del_objeto_salen_de_una_sola_peticion(requests_mock, client):
    give_token(requests_mock)
    m = requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/271440", json=doc_objeto()
    )

    datos = client.item_datos(271440)

    assert m.call_count == 1
    assert datos["nombres"]["en_GB"] == "Greaves of the Noxious Depths"
    assert datos["clase"] == "Armor"
    assert datos["subclase"] == "Mail"
    assert datos["calidad"] == "EPIC"
    assert datos["hueco"] == "FEET"
    assert datos["nivel"] == 219
    assert datos["nivel_requerido"] == 90


def test_la_categoria_se_guarda_en_ingles(requests_mock, client):
    """De aqui salen las URLs (/items/armor/mail) y esas no se traducen."""
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/271440", json=doc_objeto()
    )

    datos = client.item_datos(271440)

    assert datos["clase"] == "Armor" and datos["subclase"] == "Mail"


def test_el_id_de_la_categoria_viaja_con_su_nombre(requests_mock, client):
    """El nombre lo pueden cambiar; el id de Blizzard es lo estable."""
    give_token(requests_mock)
    requests_mock.get(
        "https://eu.api.blizzard.com/data/wow/item/271440", json=doc_objeto()
    )

    datos = client.item_datos(271440)

    assert datos["clase_id"] == 4
    assert datos["subclase_id"] == 3


def test_un_objeto_sin_categoria_no_da_atributos(requests_mock, client):
    """Sin categoria no se puede colocar en ninguna pagina de /items.

    Devolver una fila a medias seria peor: entraria en la base con clase vacia
    y habria que filtrarla en cada consulta.
    """
    give_token(requests_mock)
    doc = doc_objeto()
    del doc["item_class"]
    requests_mock.get("https://eu.api.blizzard.com/data/wow/item/271440", json=doc)

    assert client.item_datos(271440) is None


def test_un_consumible_no_tiene_hueco_de_equipo(requests_mock, client):
    """Una pocion no se equipa: `hueco` sale None, no cadena vacia."""
    give_token(requests_mock)
    doc = doc_objeto(inventory_type={"type": "NON_EQUIP", "name": {"en_GB": "Non-equippable"}})
    requests_mock.get("https://eu.api.blizzard.com/data/wow/item/271440", json=doc)

    assert client.item_datos(271440)["hueco"] is None


def test_un_objeto_que_no_existe_no_tumba_la_pasada(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get("https://eu.api.blizzard.com/data/wow/item/271440", status_code=404)

    assert client.item_datos(271440) is None


def test_la_ficha_del_grupo_trae_nombres_y_slugs(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(
        REALM_URL,
        json={
            "realms": [
                {"slug": "sanguino", "name": {"en_GB": "Sanguino"}},
                {"slug": "dun-modr", "name": {"en_GB": "Dun Modr"}},
            ]
        },
    )

    assert client.connected_realm_ficha(1305) == (
        "Sanguino / Dun Modr", ["dun-modr", "sanguino"]
    )


def test_la_ficha_del_grupo_es_none_si_falla(requests_mock, client):
    give_token(requests_mock)
    requests_mock.get(REALM_URL, status_code=404)

    assert client.connected_realm_ficha(1305) is None
