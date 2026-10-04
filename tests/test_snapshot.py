from datetime import datetime, timedelta, timezone

import pytest

from wowalerts.snapshot import (
    MAX_DUMP_AGE_MINUTES,
    dump_age,
    dump_is_stale,
    falta_para_el_siguiente,
)

# El margen con el que se juzga si Blizzard va tarde. Los tests lo fijan aparte
# para no romperse si cambia el valor por defecto.
MAX = 65


def utc(dia, hora, minuto):
    return datetime(2026, 8, dia, hora, minuto, tzinfo=timezone.utc)


def test_el_volcado_recien_salido_no_esta_viejo():
    assert not dump_is_stale(utc(30, 13, 23), utc(30, 13, 33), max_age_minutes=MAX)


def test_el_de_la_hora_anterior_si_lo_esta():
    """El caso que motiva el reintento: Blizzard va tarde y seguimos con datos viejos."""
    assert dump_is_stale(utc(30, 12, 23), utc(30, 13, 33), max_age_minutes=MAX)


def test_una_pasada_a_mano_a_media_hora_no_cuenta_como_vieja():
    """A y 58 el volcado de y 23 tiene 35 min, pero es el ultimo que existe."""
    assert not dump_is_stale(utc(30, 12, 23), utc(30, 12, 58), max_age_minutes=MAX)


def test_una_pasada_justo_antes_del_siguiente_volcado_tampoco():
    """A y 20 el de y 23 de la hora anterior tiene 57 min y aun no toca otro."""
    assert not dump_is_stale(utc(30, 12, 23), utc(30, 13, 20), max_age_minutes=MAX)


@pytest.mark.parametrize("minuto_de_publicacion", [5, 23, 31, 47, 59])
def test_da_igual_el_minuto_al_que_publique_blizzard(minuto_de_publicacion):
    """La regresion que motivo el cambio: con un minuto fijo, moverlo rompia todo.

    Blizzard paso de publicar a y 31 a hacerlo a y 23 sin avisar. Publique
    cuando publique, un volcado de hace 10 minutos es el bueno y uno de hace
    hora y pico no.
    """
    publicado = utc(30, 13, minuto_de_publicacion)
    assert not dump_is_stale(
        publicado, publicado + timedelta(minutes=10), max_age_minutes=MAX
    )
    assert dump_is_stale(
        publicado, publicado + timedelta(minutes=70), max_age_minutes=MAX
    )


def test_el_margen_por_defecto_pasa_de_una_hora():
    """Por debajo de 60 se marcaria como retrasado el volcado bueno."""
    assert MAX_DUMP_AGE_MINUTES > 60


def test_sin_marca_de_tiempo_no_se_reintenta():
    """Si ningun reino dio Last-Modified, el problema es otro y esperar no ayuda."""
    assert not dump_is_stale(None, utc(30, 13, 33), max_age_minutes=MAX)


@pytest.mark.parametrize(
    "publicado,ahora,faltan",
    [
        # Recien salido: queda casi la hora entera.
        ((13, 23), (13, 25), 58),
        # El caso feo: el disparo se ha quedado justo por delante y tenemos
        # delante un volcado casi caduco.
        ((12, 31), (13, 25), 6),
        # Ya deberia haber salido: van tarde.
        ((12, 23), (13, 33), -10),
    ],
)
def test_cuanto_falta_para_el_siguiente(publicado, ahora, faltan):
    assert falta_para_el_siguiente(utc(30, *publicado), utc(30, *ahora)) == faltan


def test_la_antiguedad_es_la_diferencia():
    assert dump_age(utc(30, 13, 23), utc(30, 13, 33)) == timedelta(minutes=10)
