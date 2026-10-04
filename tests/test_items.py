import pytest

from wowalerts.blizzard import BlizzardAuthError, BlizzardError
from wowalerts.config import Config, ItemRule, Settings
from wowalerts.items import ItemResolutionError, resolve_item_ids
from wowalerts.state import ItemIdCache


class FakeClient:
    """Cliente de mentira que devuelve ids fijos o revienta a voluntad."""

    def __init__(self, ids=None, fallan=(), error=BlizzardError("la API se ha caido")):
        self.ids = ids or {}
        self.fallan = set(fallan)
        self.error = error
        self.buscados = []

    def search_item_id(self, name):
        self.buscados.append(name)
        if name in self.fallan:
            raise self.error
        return self.ids.get(name)


def make_config(*rules):
    return Config(region="eu", items=tuple(rules), bonus_ilvl_map={}, settings=Settings())


def rule(name, item_id=None):
    return ItemRule(name=name, max_price_by_ilvl={311: 1000}, item_id=item_id)


def test_resuelve_los_nombres_por_la_api(tmp_path):
    client = FakeClient({"Botas": 1, "Casco": 2})
    config = make_config(rule("Botas"), rule("Casco"))

    resultado = resolve_item_ids(client, config, ItemIdCache(tmp_path / "c.json"))

    assert {i: r.name for i, r in resultado.items()} == {1: "Botas", 2: "Casco"}


def test_un_item_id_del_config_evita_la_busqueda(tmp_path):
    client = FakeClient()
    config = make_config(rule("Botas", item_id=777))

    resultado = resolve_item_ids(client, config, ItemIdCache(tmp_path / "c.json"))

    assert list(resultado) == [777]
    assert client.buscados == []


def test_los_ids_encontrados_quedan_en_cache(tmp_path):
    path = tmp_path / "c.json"
    cache = ItemIdCache(path)

    resolve_item_ids(FakeClient({"Botas": 1}), make_config(rule("Botas")), cache)
    cache.save()

    assert ItemIdCache(path).get("Botas") == 1


def test_si_la_busqueda_falla_se_usa_la_cache(tmp_path):
    path = tmp_path / "c.json"
    cache = ItemIdCache(path)
    cache.set("Botas", 1)

    resultado = resolve_item_ids(
        FakeClient(fallan={"Botas"}), make_config(rule("Botas")), cache
    )

    assert list(resultado) == [1]


def test_un_objeto_no_encontrado_no_impide_vigilar_los_demas(tmp_path, caplog):
    client = FakeClient({"Casco": 2})
    config = make_config(rule("Nombre Mal Escrito"), rule("Casco"))

    resultado = resolve_item_ids(client, config, ItemIdCache(tmp_path / "c.json"))

    assert list(resultado) == [2]
    assert "Nombre Mal Escrito" in caplog.text


def test_si_no_se_identifica_ninguno_es_un_error(tmp_path):
    config = make_config(rule("Fantasma"))

    with pytest.raises(ItemResolutionError, match="ninguno de los objetos"):
        resolve_item_ids(FakeClient(), config, ItemIdCache(tmp_path / "c.json"))


def test_un_fallo_de_credenciales_corta_de_inmediato(tmp_path):
    """No tiene sentido intentar los nueve objetos con credenciales invalidas."""
    client = FakeClient(
        fallan={"Botas", "Casco"}, error=BlizzardAuthError("credenciales invalidas")
    )
    config = make_config(rule("Botas"), rule("Casco"))

    with pytest.raises(BlizzardAuthError):
        resolve_item_ids(client, config, ItemIdCache(tmp_path / "c.json"))

    assert client.buscados == ["Botas"]


def test_dos_objetos_con_el_mismo_id_no_se_pisan(tmp_path, caplog):
    client = FakeClient({"Botas": 1, "Botas (duplicado)": 1})
    config = make_config(rule("Botas"), rule("Botas (duplicado)"))

    resultado = resolve_item_ids(client, config, ItemIdCache(tmp_path / "c.json"))

    assert len(resultado) == 1
    assert resultado[1].name == "Botas"
    assert "comparten el id" in caplog.text
