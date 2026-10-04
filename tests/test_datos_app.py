import datos_app
from datos_app import fichas_de_grupos


class ClienteFalso:
    def __init__(self, fichas):
        self.fichas = fichas
        self.pedidas = []

    def connected_realm_ficha(self, realm_id):
        self.pedidas.append(realm_id)
        return self.fichas.get(realm_id)


def test_las_fichas_se_cachean_y_no_se_vuelven_a_pedir(tmp_path):
    cliente = ClienteFalso({1305: ("Aszune / Shadowsong", ["aszune", "shadowsong"])})
    primera = fichas_de_grupos(cliente, [1305], tmp_path)
    segunda = fichas_de_grupos(cliente, [1305], tmp_path)

    assert primera == segunda == {1305: ("Aszune / Shadowsong", ["aszune", "shadowsong"])}
    assert cliente.pedidas == [1305], "la segunda vez debe salir del disco"


def test_un_grupo_que_no_se_puede_leer_no_se_cachea(tmp_path):
    """El nombre de relleno no debe quedarse para siempre."""
    cliente = ClienteFalso({})
    assert fichas_de_grupos(cliente, [9], tmp_path) == {9: ("Reino 9", [])}
    fichas_de_grupos(cliente, [9], tmp_path)
    assert cliente.pedidas == [9, 9]


class ClienteSinNombres:
    def __init__(self):
        self.pedidas = []

    def item_names(self, item_id):
        self.pedidas.append(item_id)
        return {}

    def item_icon_url(self, item_id):
        return None


def test_los_vigilados_tienen_nombre_sin_pedirlo(tmp_path):
    """Salen en el buscador desde la primera pasada, sin esperar a los plazos."""
    from datos_app import completar_nombres
    from wowalerts.mercado import TIPO_OBJETO, Clave

    cliente = ClienteSinNombres()
    ofertas = {Clave(TIPO_OBJETO, 212000, 305): [(0, 1, 1)]}
    vigilados = [{"id": 212000, "es": "Grebas", "en": "Greaves", "icono": "x.jpg"}]

    nombres = completar_nombres(cliente, ofertas, tmp_path, vigilados)

    assert nombres["o:212000"] == {"es": "Grebas", "en": "Greaves", "icono": "x.jpg"}
    assert cliente.pedidas == []


def test_el_historial_se_guarda_entre_pasadas(tmp_path):
    from wowalerts.mercado import TIPO_OBJETO, Clave

    grebas = Clave(TIPO_OBJETO, 212000, 305)
    grupos = [("Aszune", ["aszune"], 1), ("Kazzak", ["kazzak"], 1)]
    # 2026-09-27 a las 10:00 y a las 11:00 UTC: el mismo dia.
    datos_app.actualizar_historial({grebas: [(0, 20_000_000, 1)]}, {212000}, grupos, tmp_path, 1790503200)
    fichero = datos_app.actualizar_historial(
        {grebas: [(1, 15_000_000, 1)]}, {212000}, grupos, tmp_path, 1790506800
    )
    assert fichero["objetos"] == {"212000": {"305": [["2026-09-27", 1500, "Kazzak"]]}}
