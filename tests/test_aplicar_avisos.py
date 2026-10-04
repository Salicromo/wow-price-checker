"""Pausar y reanudar los avisos desde la app, via issue."""

import pytest

import aplicar_avisos
from aplicar_avisos import parsear
from wowalerts.avisos import AvisosError, poner_pausa
from wowalerts.config import load_config

CONFIG = """\
region: eu

items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl: { 311: 90000 }

settings:
  # Un comentario que no se toca.
  max_workers: 8
  silencio_desde: 1
  silencio_hasta: 9
"""

PAUSAR = "### Avisos\n\nPausar\n"
REANUDAR = "### Avisos\n\nReanudar\n"


def cargar(tmp_path, texto):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return load_config(ruta)


# -- Leer la issue -----------------------------------------------------------


def test_lee_pausar():
    assert parsear(PAUSAR) is True


def test_lee_reanudar():
    assert parsear(REANUDAR) is False


def test_da_igual_mayusculas_y_espacios():
    assert parsear("### Avisos\n\n  pausar  \n") is True


def test_una_orden_desconocida_se_rechaza():
    with pytest.raises(AvisosError, match="Pausar"):
        parsear("### Avisos\n\nQuizas\n")


def test_sin_el_campo_se_rechaza():
    with pytest.raises(AvisosError):
        parsear("### Otra cosa\n\nPausar\n")


# -- Editar config.yaml ------------------------------------------------------


def test_pausar_anade_la_linea_dentro_de_settings(tmp_path):
    nuevo = poner_pausa(CONFIG, True)
    assert cargar(tmp_path, nuevo).settings.avisos_pausados is True


def test_reanudar_cambia_la_linea_que_ya_hay(tmp_path):
    nuevo = poner_pausa(poner_pausa(CONFIG, True), False)
    assert cargar(tmp_path, nuevo).settings.avisos_pausados is False
    assert nuevo.count("avisos_pausados:") == 1


def test_no_toca_nada_mas(tmp_path):
    nuevo = poner_pausa(CONFIG, True)
    antes = cargar(tmp_path, CONFIG)
    despues = cargar(tmp_path, nuevo)
    assert despues.items == antes.items
    assert despues.settings.silencio_desde == 1
    assert "# Un comentario que no se toca." in nuevo


def test_pedir_lo_que_ya_hay_no_cambia_el_fichero():
    pausado = poner_pausa(CONFIG, True)
    assert poner_pausa(pausado, True) == pausado


def test_sin_bloque_settings_lo_crea(tmp_path):
    sin_settings = CONFIG.split("settings:")[0]
    nuevo = poner_pausa(sin_settings, True)
    assert cargar(tmp_path, nuevo).settings.avisos_pausados is True


def test_respeta_un_comentario_al_final_de_la_linea(tmp_path):
    con_comentario = CONFIG + "  avisos_pausados: false  # desde la app\n"
    nuevo = poner_pausa(con_comentario, True)
    assert "avisos_pausados: true  # desde la app" in nuevo
    assert cargar(tmp_path, nuevo).settings.avisos_pausados is True


# -- De punta a punta --------------------------------------------------------


def test_main_pausa_y_comenta(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PAUSAR))

    assert aplicar_avisos.main(["--config", str(ruta)]) == aplicar_avisos.EXIT_OK

    assert load_config(ruta).settings.avisos_pausados is True
    assert "pausados" in capsys.readouterr().out.lower()


def test_main_con_una_orden_mala_no_escribe(tmp_path, monkeypatch, capsys):
    ruta = tmp_path / "config.yaml"
    ruta.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("### Avisos\n\nx\n"))

    assert aplicar_avisos.main(["--config", str(ruta)]) == aplicar_avisos.EXIT_ERROR

    assert ruta.read_text(encoding="utf-8") == CONFIG
    assert "No he cambiado nada" in capsys.readouterr().out
