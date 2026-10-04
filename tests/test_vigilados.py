"""El fichero que le dice al addon que objetos repostear."""

from __future__ import annotations

from pathlib import Path

import pytest

import generar_vigilados
from generar_vigilados import a_lua, duracion_de, objetos_a_repostear, personajes_a_lua
from wowalerts.blizzard import BlizzardAuthError
from wowalerts.config import ConfigError, ItemRule, load_config

RAIZ = Path(__file__).resolve().parent.parent
GENERADO = RAIZ / "addon" / "WowAlertsExport" / "Vigilados.lua"

CONFIG_MINIMO = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Otro"
    max_price: 100
"""

CONFIG_REPOSTEO_SIN_UNDERCUT = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Receta"
    max_price: 100
    avisar_undercut: false
    repostear: true
"""

CONFIG_UNDERCUT_SIN_REPOSTEO = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Montura"
    max_price: 100
    repostear: false
"""


def test_la_duracion_sale_de_listing_hours():
    assert duracion_de(12) == 1
    assert duracion_de(24) == 2
    assert duracion_de(48) == 3


def test_una_duracion_que_el_juego_no_admite_se_explica():
    with pytest.raises(ConfigError, match="12, 24 o 48"):
        duracion_de(6)


def test_entran_los_objetos_marcados_para_repostear():
    reglas = {
        1: ItemRule(name="Grebas", max_price=10),
        2: ItemRule(name="Patron", max_price=10, avisar_undercut=False),
        3: ItemRule(
            name="Receta", max_price=10, avisar_undercut=False, repostear=True
        ),
        4: ItemRule(name="Montura", max_price=10, repostear=False),
    }
    assert objetos_a_repostear(reglas) == {1: "Grebas", 3: "Receta"}


def test_las_mascotas_no_entran_en_objetos_a_repostear():
    reglas = {
        1: ItemRule(name="Grebas", max_price=10),
        2: ItemRule(name="Mascota", max_price=10, pet_species_id=123),
    }
    assert objetos_a_repostear(reglas) == {1: "Grebas"}


def test_el_lua_generado_se_carga_y_escapa_las_comillas():
    lupa = pytest.importorskip("lupa")
    nombre = 'Grebas "raras"\ncon barra\\y salto'
    texto = a_lua({271440: nombre}, 1)

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    vigilados = lua.globals().WowAlertsVigilados
    assert vigilados.objetos[271440] == nombre
    assert len(vigilados.personajes) == 0
    assert vigilados.duracion == 1


def test_personajes_lua_rellena_la_lista_despues_de_vigilados():
    """El .toc carga Personajes.lua justo detras de Vigilados.lua."""
    lupa = pytest.importorskip("lupa")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(a_lua({271440: "Grebas"}, 1))
    lua.execute(personajes_a_lua(["Pepe", 'Con "comillas"']))
    vigilados = lua.globals().WowAlertsVigilados
    assert list(vigilados.personajes.values()) == ["Pepe", 'Con "comillas"']


def test_el_repositorio_no_lleva_nombres_de_personaje():
    """Vigilados.lua se sube a git y el repositorio es publico."""
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(GENERADO.read_text(encoding="utf-8"))
    assert len(lua.globals().WowAlertsVigilados.personajes) == 0


def test_el_fichero_del_repositorio_esta_al_dia_con_config_yaml():
    """Si cambias config.yaml y no regeneras, el addon repostea otra cosa.

    Arreglo: .venv\\Scripts\\python.exe generar_vigilados.py
    """
    lupa = pytest.importorskip("lupa")
    config = load_config(RAIZ / "config.yaml")
    texto = GENERADO.read_text(encoding="utf-8")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(texto)
    vigilados = lua.globals().WowAlertsVigilados

    esperados = {r.name for r in config.items if r.se_repostea and not r.es_mascota}
    assert set(vigilados.objetos.values()) == esperados
    assert vigilados.duracion == duracion_de(config.settings.listing_hours)


def _ejecutar_main(tmp_path, monkeypatch, config_text, resolver):
    """Llama a generar_vigilados.main() sobre un config.yaml de prueba.

    Parchea `load_dotenv` (no hace falta leer un .env real) y `resolve_item_ids`
    con `resolver`, escribe `config_text` como config.yaml en `tmp_path` y
    devuelve (codigo, salida) para que cada test compruebe lo que le importa.
    """
    monkeypatch.setattr(generar_vigilados, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(generar_vigilados, "resolve_item_ids", resolver)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    salida = tmp_path / "Vigilados.lua"

    codigo = generar_vigilados.main(
        [
            "--config", str(config_path),
            "--state-dir", str(tmp_path / "estado"),
            "--salida", str(salida),
        ]
    )
    return codigo, salida


def test_credenciales_invalidas_no_rompen_con_traceback(tmp_path, monkeypatch):
    """Un fallo de credenciales debe parar limpio, no reventar con traceback."""

    def _falla(client, config, cache):
        raise BlizzardAuthError("credenciales invalidas")

    codigo, salida = _ejecutar_main(tmp_path, monkeypatch, CONFIG_MINIMO, _falla)

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()


def test_falta_un_repostear_sin_undercut_no_escribe_nada_y_avisa(tmp_path, monkeypatch):
    """Un objeto con `repostear: true` y `avisar_undercut: false` sin id
    resuelto debe avisar igual: no lleva undercut, pero si tiene que repostearse.
    """

    def _resuelve_a_medias(client, config, cache):
        # Falta "Receta": simula que no se ha podido identificar su id.
        return {1: ItemRule(name="Grebas", max_price=100)}

    codigo, salida = _ejecutar_main(
        tmp_path, monkeypatch, CONFIG_REPOSTEO_SIN_UNDERCUT, _resuelve_a_medias
    )

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()


def test_repostear_false_no_exige_id_resuelto(tmp_path, monkeypatch):
    """Un objeto con `repostear: false` no tiene que estar en Vigilados.lua,
    asi que no debe exigirse que se resuelva su id.
    """

    def _resuelve_a_medias(client, config, cache):
        # Falta "Montura": no hace falta resolverla, porque no se repostea.
        return {1: ItemRule(name="Grebas", max_price=100)}

    codigo, salida = _ejecutar_main(
        tmp_path, monkeypatch, CONFIG_UNDERCUT_SIN_REPOSTEO, _resuelve_a_medias
    )

    assert codigo == generar_vigilados.EXIT_OK
    assert salida.exists()
    assert "Montura" not in salida.read_text(encoding="utf-8")


def test_un_objeto_no_resuelto_no_escribe_nada_y_avisa(tmp_path, monkeypatch):
    """Si falta el id de un objeto, el script no debe escribir un fichero incompleto."""

    def _resuelve_a_medias(client, config, cache):
        # Falta "Otro": simula que no se ha podido identificar su id.
        return {1: ItemRule(name="Grebas", max_price=100)}

    codigo, salida = _ejecutar_main(
        tmp_path, monkeypatch, CONFIG_MINIMO, _resuelve_a_medias
    )

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()


def test_personajes_lua_sale_aunque_blizzard_falle(tmp_path, monkeypatch):
    """En la Deck no hay credenciales: Personajes.lua no puede depender de ellas."""

    def _falla(client, config, cache):
        raise BlizzardAuthError("credenciales invalidas")

    (tmp_path / "personajes.yaml").write_text(
        "orden_personajes:\n  - Pepe\n", encoding="utf-8"
    )
    codigo, salida = _ejecutar_main(tmp_path, monkeypatch, CONFIG_MINIMO, _falla)

    assert codigo == generar_vigilados.EXIT_ERROR
    assert not salida.exists()
    assert '"Pepe"' in (tmp_path / "Personajes.lua").read_text(encoding="utf-8")


def test_solo_personajes_no_habla_con_blizzard(tmp_path, monkeypatch):
    def _no_deberia_llamarse(client, config, cache):
        raise AssertionError("--solo-personajes no resuelve ids")

    monkeypatch.setattr(generar_vigilados, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(generar_vigilados, "resolve_item_ids", _no_deberia_llamarse)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_MINIMO, encoding="utf-8")
    (tmp_path / "personajes.yaml").write_text(
        "orden_personajes:\n  - Pepe\n", encoding="utf-8"
    )

    codigo = generar_vigilados.main(
        ["--config", str(config_path), "--salida", str(tmp_path / "Vigilados.lua"),
         "--solo-personajes"]
    )

    assert codigo == generar_vigilados.EXIT_OK
    assert not (tmp_path / "Vigilados.lua").exists()
    assert (tmp_path / "Personajes.lua").is_file()
