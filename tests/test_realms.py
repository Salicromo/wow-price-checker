"""Traduccion de nombre de reino a connected realm id."""

import pytest

from wowalerts.blizzard import BlizzardError
from wowalerts.realms import RealmResolutionError, resolve_connected_realms
from wowalerts.state import RealmIdCache


class ClienteFalso:
    def __init__(self, por_slug=None, indice=None, fallos=()):
        self.por_slug = por_slug or {}
        self.indice = indice or []
        self.fallos = set(fallos)
        self.slugs_pedidos = []

    def connected_realm_id_for(self, slug):
        self.slugs_pedidos.append(slug)
        if slug in self.fallos:
            raise BlizzardError("boom")
        return self.por_slug.get(slug)

    def realm_index(self):
        return self.indice


def cache(tmp_path):
    return RealmIdCache(tmp_path / "realm_ids.json")


def test_resuelve_por_el_slug_deducido_del_nombre(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    assert resolve_connected_realms(cliente, cache(tmp_path), ["Sanguino"]) == {
        "Sanguino": 1379
    }


def test_usa_la_cache_y_no_repite_la_peticion(tmp_path):
    guardada = cache(tmp_path)
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    resolve_connected_realms(cliente, guardada, ["Sanguino"])
    guardada.save()

    otro = ClienteFalso()
    assert resolve_connected_realms(otro, cache(tmp_path), ["Sanguino"]) == {
        "Sanguino": 1379
    }
    assert otro.slugs_pedidos == []


def test_cae_al_indice_cuando_el_slug_no_vale(tmp_path):
    cliente = ClienteFalso(
        por_slug={"dun-modr": 1379},
        indice=[{"slug": "dun-modr", "names": ["Dun Modr"]}],
    )
    assert resolve_connected_realms(cliente, cache(tmp_path), ["DunModr"]) == {
        "DunModr": 1379
    }
    assert cliente.slugs_pedidos == ["dunmodr", "dun-modr"]


def test_resuelve_un_reino_ruso_por_su_nombre(tmp_path):
    """De un nombre en cirilico no sale ningun slug: quitarle lo que no es A-Z
    deja la cadena vacia. La unica via es el nombre en el indice."""
    cliente = ClienteFalso(
        por_slug={"revushchiy-fiord": 1929},
        indice=[
            {"slug": "revushchiy-fiord", "names": ["Ревущий фьорд", "Howling Fjord"]}
        ],
    )
    assert resolve_connected_realms(
        cliente, cache(tmp_path), ["Ревущий фьорд"]
    ) == {"Ревущий фьорд": 1929}
    # No se ha llegado a preguntar por un slug vacio.
    assert cliente.slugs_pedidos == ["revushchiy-fiord"]


def test_reino_desconocido_da_error_con_su_nombre(tmp_path):
    cliente = ClienteFalso(por_slug={}, indice=[])
    with pytest.raises(RealmResolutionError, match="Inventado"):
        resolve_connected_realms(cliente, cache(tmp_path), ["Inventado"])


def test_un_reino_que_falla_no_tumba_a_los_demas(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379}, fallos=["roto"], indice=[])
    resultado = resolve_connected_realms(
        cliente, cache(tmp_path), ["Sanguino", "Roto"], strict=False
    )
    assert resultado == {"Sanguino": 1379}


def test_no_repite_la_consulta_de_un_reino_duplicado(tmp_path):
    cliente = ClienteFalso(por_slug={"sanguino": 1379})
    resolve_connected_realms(cliente, cache(tmp_path), ["Sanguino", "Sanguino"])
    assert cliente.slugs_pedidos == ["sanguino"]
