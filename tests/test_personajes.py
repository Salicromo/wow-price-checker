"""Lectura del listado de personajes y a quien mandar a por un chollo."""

import json

from wowalerts.personajes import (
    Personaje,
    escribir_personajes,
    leer_personajes,
    leer_roster,
    leer_rosters,
    por_nombre_de_reino,
    quien_puede_comprar,
)


def wow_falso(tmp_path, estructura):
    """Crea un arbol de WTF como el del juego: cuenta / reino / personaje."""
    for cuenta, reinos in estructura.items():
        base = tmp_path / "WTF" / "Account" / cuenta
        (base / "SavedVariables").mkdir(parents=True, exist_ok=True)
        (base / "SavedVariables" / "Algo.lua").write_text("", encoding="utf-8")
        for reino, personajes in reinos.items():
            for nombre in personajes:
                (base / reino / nombre).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_lee_los_personajes_con_su_reino_y_su_cuenta(tmp_path):
    raiz = wow_falso(tmp_path, {"403840080#2": {"Kazzak": ["Kbardan"]}})

    assert leer_personajes(raiz) == [
        Personaje("Kbardan", "Kazzak", "kazzak", 2)
    ]


def test_savedvariables_no_es_un_reino(tmp_path):
    raiz = wow_falso(tmp_path, {"403840080#1": {"Norgannon": ["Nbargor"]}})

    reinos = {p.realm for p in leer_personajes(raiz)}
    assert reinos == {"Norgannon"}


def test_lee_varias_cuentas(tmp_path):
    raiz = wow_falso(
        tmp_path,
        {
            "403840080#1": {"Norgannon": ["Nbargor"]},
            "403840080#3": {"Garona": ["Gbarbar", "Obardan"]},
        },
    )

    assert [(p.name, p.account) for p in leer_personajes(raiz)] == [
        ("Nbargor", 1),
        ("Gbarbar", 3),
        ("Obardan", 3),
    ]


def test_la_etiqueta_lleva_el_personaje_y_la_cuenta():
    assert Personaje("Kbardan", "Kazzak", "kazzak", 2).etiqueta == "Kbardan · WoW 2"


def test_sin_cuenta_la_etiqueta_es_solo_el_nombre():
    assert Personaje("Kbardan", "Kazzak", "kazzak", None).etiqueta == "Kbardan"


def test_el_roster_va_y_vuelve(tmp_path):
    personajes = [Personaje("Kbardan", "Kazzak", "kazzak", 2)]
    path = tmp_path / "mis_personajes.json"

    assert escribir_personajes(path, personajes) is True
    assert leer_roster(path) == personajes


def test_el_mismo_roster_no_cuenta_como_cambio(tmp_path):
    personajes = [Personaje("Kbardan", "Kazzak", "kazzak", 2)]
    path = tmp_path / "mis_personajes.json"

    escribir_personajes(path, personajes)
    assert escribir_personajes(path, personajes) is False


def test_un_roster_que_no_existe_son_cero_personajes(tmp_path):
    assert leer_roster(tmp_path / "no-existe.json") == []


def test_un_roster_corrupto_no_tumba_la_pasada(tmp_path):
    path = tmp_path / "roto.json"
    path.write_text("{esto no es json", encoding="utf-8")
    assert leer_roster(path) == []


def test_dice_con_quien_entrar():
    indice = por_nombre_de_reino([Personaje("Kbardan", "Kazzak", "kazzak", 2)])
    assert quien_puede_comprar(indice, "Kazzak") == "Kbardan · WoW 2"


def test_encuentra_al_personaje_en_un_reino_conectado_con_varios():
    """La API devuelve los connected realms como 'Dun Modr / Sanguino', y tu
    personaje puede estar en cualquiera de los dos."""
    indice = por_nombre_de_reino([Personaje("Sbardan", "Sanguino", "sanguino", 1)])
    assert quien_puede_comprar(indice, "Dun Modr / Sanguino") == "Sbardan · WoW 1"


def test_junta_los_personajes_de_los_reinos_hermanados():
    indice = por_nombre_de_reino(
        [
            Personaje("Dbarwen", "Dun Modr", "dun-modr", 1),
            Personaje("Sbardan", "Sanguino", "sanguino", 1),
        ]
    )
    texto = quien_puede_comprar(indice, "Dun Modr / Sanguino")

    assert "Dbarwen" in texto
    assert "Sbardan" in texto


def test_un_reino_ruso_se_encuentra_por_su_nombre():
    """Del cirilico no sale slug, pero el nombre casa tal cual."""
    indice = por_nombre_de_reino(
        [Personaje("Rbarhal", "Ревущий фьорд", "", 1)]
    )
    assert quien_puede_comprar(indice, "Ревущий фьорд") == "Rbarhal · WoW 1"


def test_sin_personaje_en_ese_reino_lo_dice():
    """Saber que no puedes llegar al chollo ahorra el viaje."""
    indice = por_nombre_de_reino([Personaje("Kbardan", "Kazzak", "kazzak", 2)])
    assert quien_puede_comprar(indice, "Ysondre") == "no tienes personaje en ese reino"


def test_con_muchos_personajes_muestra_unos_pocos():
    indice = por_nombre_de_reino(
        [Personaje(f"Pj{i}", "Kazzak", "kazzak", 2) for i in range(5)]
    )
    texto = quien_puede_comprar(indice, "Kazzak")

    assert "Pj0" in texto
    assert "Pj1" in texto
    assert "y 3 mas" in texto
    assert "Pj4" not in texto


def test_une_los_personajes_de_dos_maquinas(tmp_path):
    """En la Deck solo estan los personajes con los que has jugado alli."""
    escribir_personajes(
        tmp_path / "pc.json", [Personaje("Uno", "Kazzak", "kazzak", 2)]
    )
    escribir_personajes(
        tmp_path / "deck.json", [Personaje("Dos", "Ysondre", "ysondre", 3)]
    )

    assert {p.name for p in leer_rosters(tmp_path)} == {"Uno", "Dos"}


def test_un_personaje_en_las_dos_maquinas_se_cuenta_una_vez(tmp_path):
    kazza = Personaje("Kbardan", "Kazzak", "kazzak", 2)
    escribir_personajes(tmp_path / "pc.json", [kazza])
    escribir_personajes(tmp_path / "deck.json", [kazza])

    assert leer_rosters(tmp_path) == [kazza]


# -- Orden de los avisos ----------------------------------------------------

from wowalerts.personajes import orden_de_personajes


def test_el_orden_sale_del_roster():
    roster = [
        Personaje(name="Ana", realm="Elune", realm_slug="elune", account=2),
        Personaje(name="Luis", realm="Onyxia", realm_slug="onyxia", account=2),
        Personaje(name="Eva", realm="Azshara", realm_slug="azshara", account=3),
    ]
    orden = orden_de_personajes(roster)
    assert orden[("Ana", "Elune")] < orden[("Luis", "Onyxia")]
    assert orden[("Luis", "Onyxia")] < orden[("Eva", "Azshara")]


def test_las_cuentas_van_primero_aunque_el_fichero_las_mezcle():
    """WoW 1 antes que WoW 2, sea cual sea el orden en que se leyeron."""
    roster = [
        Personaje(name="Eva", realm="Azshara", realm_slug="azshara", account=3),
        Personaje(name="Ana", realm="Elune", realm_slug="elune", account=1),
    ]
    orden = orden_de_personajes(roster)
    assert orden[("Ana", "Elune")] < orden[("Eva", "Azshara")]


def test_un_personaje_que_no_esta_en_el_roster_va_al_final():
    orden = orden_de_personajes([Personaje(name="Ana", realm="Elune", realm_slug="elune", account=1)])
    assert orden.get(("Desconocido", "X")) is None
