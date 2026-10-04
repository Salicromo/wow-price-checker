import tempfile
from pathlib import Path

import pytest

from wowalerts.config import load_config
from wowalerts.topes import TopeError, cambiar_tope

# Una copia reducida de config.yaml que conserva lo que importa aqui: los
# comentarios, el mapa en linea partido en dos lineas, y dos objetos con tablas
# identicas.
CONFIG = """\
# ============================================================================
#  Configuracion del vigilante de precios
# ============================================================================

region: eu

items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl:
      { 295: 6999, 298: 12000, 305: 40000, 308: 60000, 311: 90000,
        318: 200000, 321: 200000, 324: 200000 }

  - name: "Temple Delver's Mystic Helm"
    max_price_by_ilvl:
      { 295: 9000, 298: 12000, 305: 40000, 308: 60000, 311: 90000,
        318: 200000, 321: 200000, 324: 200000 }

  # Los patrones no escalan: un solo precio.
  - name: "Pattern: Arcanoweave Cord"
    item_id: 258126
    max_price: 60000
    avisar_undercut: false

  - name: "Nightsaber Cub"
    pet_species_id: 303
    max_price: 100000
    avisar_undercut: false

bonus_ilvl_map:
  12843: 311

settings:
  max_workers: 4
"""


def test_cambia_un_ilvl_suelto():
    nuevo, viejo = cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", 295, 4000)

    assert viejo == 9000
    assert '{ 295: 4000, 298: 12000, 305: 40000, 308: 60000, 311: 90000,' in nuevo


def test_el_resto_del_fichero_queda_identico():
    """Lo unico que puede cambiar es la linea del tope pedido.

    Es la garantia que hace seguro editar por texto: los comentarios de
    config.yaml son la mitad del valor del fichero y no se pueden perder.
    """
    nuevo, _ = cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", 295, 4000)

    antes = CONFIG.splitlines()
    despues = nuevo.splitlines()
    assert len(antes) == len(despues)

    distintas = [i for i, (a, b) in enumerate(zip(antes, despues)) if a != b]
    assert len(distintas) == 1
    assert "295: 9000" in antes[distintas[0]]
    assert "295: 4000" in despues[distintas[0]]


def test_no_reformatea_el_mapa_en_linea():
    """El ajuste de lineas del mapa se respeta: cambia el numero, nada mas."""
    nuevo, _ = cambiar_tope(CONFIG, "Greaves of the Noxious Depths", 324, 150000)

    assert "        318: 200000, 321: 200000, 324: 150000 }" in nuevo


def test_cambia_un_max_price_de_precio_unico():
    nuevo, viejo = cambiar_tope(CONFIG, "Pattern: Arcanoweave Cord", None, 45000)

    assert viejo == 60000
    assert "    max_price: 45000\n" in nuevo
    # El del otro objeto de precio unico no se toca.
    assert "    max_price: 100000\n" in nuevo


def test_una_mascota_va_por_nombre_como_todo_lo_demas():
    nuevo, viejo = cambiar_tope(CONFIG, "Nightsaber Cub", None, 80000)

    assert viejo == 100000
    assert "    max_price: 80000\n" in nuevo


def test_dos_tablas_identicas_y_solo_cambia_la_pedida():
    """Los dos objetos comparten los mismos ocho escalones salvo el 295.

    Sin anclar la busqueda al bloque del objeto, un reemplazo por valor
    cambiaria el escalon de los dos.
    """
    nuevo, _ = cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", 311, 70000)

    config = load_from(nuevo)
    porNombre = {r.name: r for r in config.items}
    assert porNombre["Temple Delver's Mystic Helm"].max_price_by_ilvl[311] == 70000
    assert porNombre["Greaves of the Noxious Depths"].max_price_by_ilvl[311] == 90000


def test_el_resultado_sigue_cargando():
    nuevo, _ = cambiar_tope(CONFIG, "Greaves of the Noxious Depths", 305, 33000)

    config = load_from(nuevo)
    assert config.items[0].max_price_by_ilvl[305] == 33000
    assert config.region == "eu"
    assert config.settings.max_workers == 4


def test_objeto_inexistente():
    with pytest.raises(TopeError, match="Molten Helm"):
        cambiar_tope(CONFIG, "Molten Helm", 295, 4000)


def test_un_nombre_que_es_prefijo_de_otro_no_se_confunde():
    texto = CONFIG.replace(
        '  - name: "Nightsaber Cub"',
        '  - name: "Nightsaber"\n'
        "    pet_species_id: 999\n"
        "    max_price: 5000\n\n"
        '  - name: "Nightsaber Cub"',
    )
    nuevo, viejo = cambiar_tope(texto, "Nightsaber", None, 7000)

    assert viejo == 5000
    assert "    max_price: 7000\n" in nuevo
    # El Cub, que empieza igual, se queda como estaba.
    assert "    max_price: 100000\n" in nuevo


def test_ilvl_que_no_esta_en_la_tabla():
    with pytest.raises(TopeError) as fallo:
        cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", 302, 4000)

    # El mensaje dice cuales si valen, que es lo unico accionable.
    assert "295" in str(fallo.value)
    assert "324" in str(fallo.value)


def test_ilvl_sobre_un_objeto_de_precio_unico():
    with pytest.raises(TopeError, match="no depende del ilvl"):
        cambiar_tope(CONFIG, "Pattern: Arcanoweave Cord", 295, 4000)


def test_sin_ilvl_sobre_un_objeto_con_tabla():
    with pytest.raises(TopeError, match="lleva tabla por ilvl"):
        cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", None, 4000)


@pytest.mark.parametrize("tope", [0, -1])
def test_tope_no_positivo(tope):
    with pytest.raises(TopeError, match="mayor que cero"):
        cambiar_tope(CONFIG, "Temple Delver's Mystic Helm", 295, tope)


def load_from(texto):
    """Carga un config.yaml desde texto, que load_config solo lee de disco."""
    carpeta = Path(tempfile.mkdtemp())
    ruta = carpeta / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return load_config(ruta)


def test_contra_el_config_yaml_de_verdad():
    """La copia de arriba esta reducida; esta prueba usa el fichero real.

    Se elige el objeto sobre la marcha en vez de fijarlo, para que la prueba
    siga valiendo cuando cambie la lista de objetos vigilados.
    """
    ruta = Path(__file__).resolve().parent.parent / "config.yaml"
    texto = ruta.read_text(encoding="utf-8")
    config = load_config(ruta)

    con_tabla = next(r for r in config.items if r.max_price_by_ilvl)
    ilvl = min(con_tabla.max_price_by_ilvl)
    antes = con_tabla.max_price_by_ilvl[ilvl]

    nuevo, viejo = cambiar_tope(texto, con_tabla.name, ilvl, antes + 1)
    assert viejo == antes

    # Una sola linea distinta en las 441 del fichero.
    distintas = [
        i for i, (a, b) in enumerate(zip(texto.splitlines(), nuevo.splitlines()))
        if a != b
    ]
    assert len(distintas) == 1

    # Y sigue cargando, con ese tope movido y ningun otro.
    despues = load_from(nuevo)
    for vieja, nueva in zip(config.items, despues.items):
        if vieja.name == con_tabla.name:
            continue
        assert vieja.max_price_by_ilvl == nueva.max_price_by_ilvl
        assert vieja.max_price == nueva.max_price


def test_contra_el_config_yaml_de_verdad_precio_unico():
    ruta = Path(__file__).resolve().parent.parent / "config.yaml"
    texto = ruta.read_text(encoding="utf-8")
    config = load_config(ruta)

    unico = next(r for r in config.items if r.max_price is not None)
    nuevo, viejo = cambiar_tope(texto, unico.name, None, unico.max_price + 1)

    assert viejo == unico.max_price
    assert load_from(nuevo).items != []
