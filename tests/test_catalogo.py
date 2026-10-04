import json

from wowalerts.catalogo import CLASE_MISCELANEA, SUBCLASE_MONTURA, cargar, construir


class ClienteFalso:
    """Un cliente que cuenta cuantas veces le preguntan."""

    def __init__(self):
        self.llamadas = 0

    def item_ids_por_subclase(self, clase, subclase):
        assert (clase, subclase) == (CLASE_MISCELANEA, SUBCLASE_MONTURA)
        self.llamadas += 1
        return [100, 200, 100]

    def toy_ids(self):
        self.llamadas += 1
        return [1, 2, 3]

    def toy_item_id(self, toy_id):
        self.llamadas += 1
        return {1: 500, 2: 600, 3: None}[toy_id]


def test_construye_las_dos_listas_sin_repetidos():
    catalogo = construir(ClienteFalso(), max_workers=2)

    assert catalogo["monturas"] == [100, 200]
    # El juguete sin objeto asociado no entra: no hay id que cruzar.
    assert catalogo["juguetes"] == [500, 600]


def test_se_guarda_en_disco_y_no_se_vuelve_a_pedir(tmp_path):
    ruta = tmp_path / "sub" / "catalogo.json"
    cliente = ClienteFalso()

    primero = cargar(cliente, ruta, max_workers=2)
    pedidas = cliente.llamadas
    segundo = cargar(cliente, ruta, max_workers=2)

    assert primero == segundo == {"monturas": {100, 200}, "juguetes": {500, 600}}
    assert cliente.llamadas == pedidas, "la segunda vez debe salir del disco"
    assert json.loads(ruta.read_text(encoding="utf-8"))["monturas"] == [100, 200]


def test_refrescar_vuelve_a_preguntar(tmp_path):
    ruta = tmp_path / "catalogo.json"
    cliente = ClienteFalso()

    cargar(cliente, ruta, max_workers=2)
    pedidas = cliente.llamadas
    cargar(cliente, ruta, refrescar=True, max_workers=2)

    assert cliente.llamadas > pedidas
