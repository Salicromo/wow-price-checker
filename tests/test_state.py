import json
from dataclasses import dataclass

from wowalerts.state import ItemIdCache, NotifiedAuctions, NotifiedUndercuts


@dataclass
class FakeDeal:
    realm_id: int
    auction_id: int


def test_una_subasta_nueva_lo_es_hasta_que_se_marca(tmp_path):
    state = NotifiedAuctions(tmp_path / "notified.json")

    assert state.is_new(1305, 999)
    state.mark(1305, 999)
    assert not state.is_new(1305, 999)


def test_la_memoria_sobrevive_entre_ejecuciones(tmp_path):
    path = tmp_path / "notified.json"

    primera = NotifiedAuctions(path)
    primera.mark(1305, 999)
    primera.save()

    segunda = NotifiedAuctions(path)
    assert not segunda.is_new(1305, 999)
    assert segunda.is_new(1305, 1000)


def test_el_contador_de_ejecuciones_avanza(tmp_path):
    path = tmp_path / "notified.json"

    primera = NotifiedAuctions(path)
    assert primera.run == 1
    primera.save()

    assert NotifiedAuctions(path).run == 2


def test_mismo_id_de_subasta_en_reinos_distintos_no_colisiona(tmp_path):
    state = NotifiedAuctions(tmp_path / "notified.json")
    state.mark(1305, 42)
    assert state.is_new(1378, 42)


def test_filter_new_descarta_lo_ya_avisado(tmp_path):
    state = NotifiedAuctions(tmp_path / "notified.json")
    state.mark(1305, 1)

    nuevos = state.filter_new([FakeDeal(1305, 1), FakeDeal(1305, 2)])

    assert [d.auction_id for d in nuevos] == [2]


def test_olvida_las_subastas_antiguas(tmp_path):
    path = tmp_path / "notified.json"

    primera = NotifiedAuctions(path, retention_runs=2)
    primera.mark(1305, 1)
    primera.save()

    # Dos pasadas mas sin volver a ver esa subasta.
    for _ in range(2):
        siguiente = NotifiedAuctions(path, retention_runs=2)
        siguiente.save()

    assert len(NotifiedAuctions(path, retention_runs=2)) == 0


def test_un_fichero_de_estado_corrupto_no_rompe_la_ejecucion(tmp_path):
    path = tmp_path / "notified.json"
    path.write_text("{esto no es json", encoding="utf-8")

    state = NotifiedAuctions(path)

    assert state.is_new(1305, 1)
    state.save()
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_el_estado_se_escribe_aunque_la_carpeta_no_exista(tmp_path):
    state = NotifiedAuctions(tmp_path / "sub" / "carpeta" / "notified.json")
    state.mark(1, 1)
    state.save()
    assert (tmp_path / "sub" / "carpeta" / "notified.json").is_file()


def test_no_deja_ficheros_temporales(tmp_path):
    state = NotifiedAuctions(tmp_path / "notified.json")
    state.save()
    assert [p.name for p in tmp_path.iterdir()] == ["notified.json"]


def test_cache_de_ids_de_objeto(tmp_path):
    path = tmp_path / "item_ids.json"

    cache = ItemIdCache(path)
    assert cache.get("Botas") is None
    cache.set("Botas", 12345)
    cache.save()

    assert ItemIdCache(path).get("Botas") == 12345


# -- Memoria de undercuts ---------------------------------------------------


def test_undercut_nuevo_es_nuevo(tmp_path):
    memoria = NotifiedUndercuts(tmp_path / "u.json")
    assert memoria.is_new(memoria.key(1379, 1, 99))


def test_undercut_ya_avisado_no_se_repite(tmp_path):
    path = tmp_path / "u.json"
    memoria = NotifiedUndercuts(path)
    memoria.mark(memoria.key(1379, 1, 99))
    memoria.save()

    otra = NotifiedUndercuts(path)
    assert not otra.is_new(otra.key(1379, 1, 99))


def test_repostear_reabre_el_aviso(tmp_path):
    path = tmp_path / "u.json"
    memoria = NotifiedUndercuts(path)
    memoria.mark(memoria.key(1379, 1, 99))
    memoria.save()

    # Reposteas: tu subasta pasa a ser la 2. Mismo rival, pareja nueva.
    otra = NotifiedUndercuts(path)
    assert otra.is_new(otra.key(1379, 2, 99))


def test_un_rival_nuevo_reabre_el_aviso(tmp_path):
    path = tmp_path / "u.json"
    memoria = NotifiedUndercuts(path)
    memoria.mark(memoria.key(1379, 1, 99))
    memoria.save()

    assert NotifiedUndercuts(path).is_new(NotifiedUndercuts(path).key(1379, 1, 98))


def test_los_undercuts_no_pisan_a_los_chollos(tmp_path):
    # Cada memoria usa su propia seccion, asi que pueden compartir carpeta.
    path = tmp_path / "compartido.json"
    chollos = NotifiedAuctions(path)
    chollos.mark(1379, 1)
    chollos.save()

    assert NotifiedUndercuts(path).is_new(NotifiedUndercuts(path).key(1379, 1, 99))
