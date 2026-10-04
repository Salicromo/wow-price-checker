"""La ventana de horas en las que no quieres que suene nada."""

from datetime import datetime, timezone

import pytest

from wowalerts.silencio import HoraInvalida, en_silencio, hora_local

MADRID = "Europe/Madrid"


def utc(hora, minuto=0, dia=1):
    return datetime(2026, 9, dia, hora, minuto, tzinfo=timezone.utc)


def test_la_hora_se_mira_en_tu_zona_no_en_utc():
    """En Actions el reloj es UTC; en verano Madrid va dos horas por delante."""
    assert hora_local(utc(23), MADRID) == 1


def test_dentro_de_la_ventana_hay_silencio():
    # 23:00 UTC = 01:00 en Madrid.
    assert en_silencio(utc(23), 1, 9, MADRID) is True


def test_fuera_de_la_ventana_no_lo_hay():
    # 08:00 UTC = 10:00 en Madrid.
    assert en_silencio(utc(8), 1, 9, MADRID) is False


def test_la_ventana_cruza_la_medianoche():
    """De 1 a 9 no es "entre 1 y 9" a secas: pasa por el cambio de dia."""
    # 03:00 en Madrid: dentro.
    assert en_silencio(utc(1), 1, 9, MADRID) is True
    # 23:00 en Madrid: fuera, aunque sea un numero mayor que 9.
    assert en_silencio(utc(21), 1, 9, MADRID) is False


def test_la_hora_de_inicio_entra_y_la_de_fin_no():
    # 01:00 en Madrid, justo al empezar.
    assert en_silencio(utc(23), 1, 9, MADRID) is True
    # 09:00 en Madrid, justo al acabar: ya suena.
    assert en_silencio(utc(7), 1, 9, MADRID) is False


def test_una_ventana_sin_cruzar_medianoche_tambien_vale():
    # De 14 a 16 en Madrid; 13:00 UTC = 15:00.
    assert en_silencio(utc(13), 14, 16, MADRID) is True
    assert en_silencio(utc(15), 14, 16, MADRID) is False


def test_desde_igual_a_hasta_es_no_silenciar_nunca():
    """Una ventana vacia, no una de 24 horas: el silencio total se pide
    apagando la alerta, no configurandola."""
    for hora in range(24):
        assert en_silencio(utc(hora), 0, 0, MADRID) is False


def test_una_zona_que_no_existe_se_dice_claro():
    with pytest.raises(HoraInvalida, match="Europa/Madriz"):
        en_silencio(utc(3), 1, 9, "Europa/Madriz")


def test_el_cambio_de_hora_se_respeta():
    """En invierno Madrid va solo una hora por delante de UTC."""
    invierno = datetime(2026, 1, 15, 0, 30, tzinfo=timezone.utc)
    # 01:30 en Madrid: dentro de la ventana.
    assert en_silencio(invierno, 1, 9, MADRID) is True
    # La misma hora UTC en verano seria 02:30, tambien dentro; la que cambia
    # es 23:30 UTC, que en invierno son las 00:30 y aun no toca callarse.
    nochevieja = datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc)
    assert en_silencio(nochevieja, 1, 9, MADRID) is False
