from datetime import datetime, timedelta, timezone

import pytest

from estado import MINUTO_CRON, esta_pendiente, slot_de, slots_esperados

# Los tests fijan el minuto a proposito, para no romperse cada vez que cambie el
# horario real del cron.
MIN = 33


def utc(dia, hora, minuto):
    return datetime(2026, 8, dia, hora, minuto, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "inicio,slot_esperado",
    [
        # Puntual.
        (utc(30, 15, MIN), utc(30, 15, MIN)),
        # Con retraso, que es lo habitual cuando lo lanza el cron de GitHub.
        (utc(30, 15, 52), utc(30, 15, MIN)),
        (utc(30, 16, MIN - 1), utc(30, 15, MIN)),
        # Pasada la hora siguiente, ya cuenta como el slot siguiente.
        (utc(30, 16, MIN), utc(30, 16, MIN)),
        # Retraso que cruza la medianoche.
        (utc(31, 0, 10), utc(30, 23, MIN)),
    ],
)
def test_una_ejecucion_se_asigna_a_su_slot(inicio, slot_esperado):
    assert slot_de(inicio, minuto=MIN) == slot_esperado


def test_la_red_de_seguridad_cuenta_como_pasada_de_esa_hora():
    """El 'schedule' del workflow va a y 35, dos minutos tras el disparo externo."""
    assert slot_de(utc(30, 15, 35), minuto=MIN) == utc(30, 15, MIN)


def test_los_slots_esperados_son_uno_por_hora():
    esperados = slots_esperados(utc(30, 14, 31), horas=6, minuto=MIN)

    assert len(esperados) == 6
    assert all(s.minute == MIN for s in esperados)
    assert esperados == sorted(esperados)
    diferencias = {b - a for a, b in zip(esperados, esperados[1:])}
    assert diferencias == {timedelta(hours=1)}


def test_no_se_espera_un_slot_que_aun_no_ha_llegado():
    esperados = slots_esperados(utc(30, 14, MIN - 2), horas=24, minuto=MIN)

    assert esperados[-1] == utc(30, 13, MIN)


def test_el_slot_recien_cumplido_si_se_espera():
    esperados = slots_esperados(utc(30, 14, MIN + 1), horas=24, minuto=MIN)

    assert esperados[-1] == utc(30, 14, MIN)


def test_la_ventana_acota_por_abajo():
    esperados = slots_esperados(utc(30, 14, MIN + 1), horas=3, minuto=MIN)

    assert esperados[0] == utc(30, 12, MIN)
    assert len(esperados) == 3


def test_no_se_reclaman_pasadas_de_antes_de_que_existiera_el_workflow():
    """Sin esto, la herramienta inventaba huecos donde no habia nada que correr."""
    esperados = slots_esperados(
        utc(30, 14, MIN + 1), horas=24, no_antes_de=utc(30, 12, 0), minuto=MIN
    )

    assert esperados == [utc(30, 12, MIN), utc(30, 13, MIN), utc(30, 14, MIN)]


def test_un_recorte_anterior_a_la_ventana_no_la_amplia():
    esperados = slots_esperados(
        utc(30, 14, MIN + 1), horas=3, no_antes_de=utc(1, 0, 0), minuto=MIN
    )

    assert len(esperados) == 3
    assert esperados[0] == utc(30, 12, MIN)


def test_sin_recorte_se_comporta_igual_que_antes():
    assert slots_esperados(
        utc(30, 14, MIN + 1), horas=3, minuto=MIN
    ) == slots_esperados(utc(30, 14, MIN + 1), horas=3, no_antes_de=None, minuto=MIN)


def test_un_slot_recien_cumplido_esta_pendiente_no_fallido():
    """GitHub lanza tarde con normalidad: no hay que darlo por perdido enseguida."""
    assert esta_pendiente(utc(30, 14, MIN), ahora=utc(30, 14, MIN + 1))
    assert esta_pendiente(utc(30, 14, MIN), ahora=utc(30, 15, 10))


def test_pasado_el_margen_ya_cuenta_como_fallo():
    assert not esta_pendiente(utc(30, 14, MIN), ahora=utc(30, 15, 20))


def test_el_minuto_por_defecto_es_el_del_cron_configurado():
    assert slot_de(utc(30, 15, MINUTO_CRON)).minute == MINUTO_CRON
