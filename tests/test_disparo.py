"""Mantener el disparo del cron pegado a la hora a la que publica Blizzard."""

import pytest
import requests

from wowalerts.disparo import (
    CronJobOrg,
    DisparoError,
    conviene_mover,
    distancia,
    hay_acuerdo,
    minuto_recomendado,
)

API = "https://api.cron-job.org/jobs/7788"


# -- La cuenta en circulo ---------------------------------------------------


@pytest.mark.parametrize(
    "desde,hasta,esperado",
    [
        (23, 25, 2),
        (25, 23, 58),
        # Dando la vuelta al reloj: de y 58 a y 03 hay 5 minutos.
        (58, 3, 5),
        (0, 0, 0),
    ],
)
def test_la_distancia_se_mide_en_circulo(desde, hasta, esperado):
    assert distancia(desde, hasta) == esperado


def test_publicar_a_y_59_recomienda_pasar_de_la_hora():
    assert minuto_recomendado(59) == 0


# -- Cuando hay acuerdo entre pasadas ---------------------------------------


def test_tres_pasadas_iguales_son_acuerdo():
    assert hay_acuerdo([23, 23, 23])


def test_un_minuto_de_vaiven_sigue_siendo_acuerdo():
    """Blizzard no publica al segundo exacto."""
    assert hay_acuerdo([23, 24, 23])


def test_dos_pasadas_no_bastan():
    """Una coincidencia corta no distingue un cambio de un mal rato."""
    assert not hay_acuerdo([23, 23])


def test_una_pasada_discordante_rompe_el_acuerdo():
    assert not hay_acuerdo([23, 40, 23])


def test_el_acuerdo_tambien_cuenta_dando_la_vuelta_al_reloj():
    """Publicar a y 59 y a y 00 es un minuto de diferencia, no 59."""
    assert hay_acuerdo([59, 0, 59])


# -- La decision ------------------------------------------------------------


def test_si_el_disparo_se_ha_quedado_atras_se_mueve():
    """El caso real: Blizzard paso de publicar a y 31 a hacerlo a y 23."""
    assert conviene_mover([23, 23, 23], disparo_actual=33) == 24


def test_si_el_disparo_va_por_delante_tambien():
    """Peor que llegar tarde: la espera esta acotada y perderias la hora."""
    assert conviene_mover([23, 23, 23], disparo_actual=20) == 24


def test_un_disparo_bien_puesto_no_se_toca():
    assert conviene_mover([23, 23, 23], disparo_actual=24) is None


def test_disparar_en_el_minuto_justo_de_publicar_tampoco_se_toca():
    """Un minuto de vaiven es el ruido normal de Blizzard, no un desajuste."""
    assert conviene_mover([23, 23, 23], disparo_actual=23) is None


def test_dos_minutos_de_retraso_ya_merecen_moverlo():
    """Lo que motivo apretar la tolerancia de 6 a 1.

    Con 6, un cron a y 25 publicando a y 23 se daba por bueno y el aviso salia
    un minuto mas tarde de lo necesario, para siempre y sin que nada lo dijera.
    """
    assert conviene_mover([23, 23, 23], disparo_actual=25) == 24


def test_un_vaiven_de_publicacion_no_mueve_el_cron():
    """Si Blizzard alterna entre y 23 y y 24, el objetivo no puede bailar.

    Se toma como referencia la publicacion mas tardia de las observadas, no la
    ultima: con la ultima a secas, el objetivo saltaria entre y 24 y y 25 y el
    cron se pasaria el dia moviendose de uno a otro.
    """
    # La mas tardia de las dos es y 24, asi que el objetivo es y 25 en los dos
    # casos, venga la ultima observacion de donde venga.
    assert conviene_mover([24, 23, 24], disparo_actual=25) is None
    assert conviene_mover([23, 24, 23], disparo_actual=25) is None


def test_sin_acuerdo_no_se_mueve_nada():
    """Un tropiezo suelto de Blizzard dejaria el cron mal puesto el resto del dia."""
    assert conviene_mover([23, 45, 23], disparo_actual=33) is None


def test_sin_historial_suficiente_no_se_mueve_nada():
    assert conviene_mover([23], disparo_actual=33) is None


def test_si_blizzard_vuelve_a_publicar_mas_tarde_se_recoloca():
    """El escenario feo: el disparo se queda justo por delante de la publicacion.

    Con el cron a y 24 y Blizzard publicando otra vez a y 31, cada pasada se
    encuentra el volcado de la hora anterior. No se pierde ninguno --la pasada
    de las 10:24 lee el de las 09:31, la de las 11:24 el de las 10:31-- pero se
    leen con casi una hora de retraso. Tiene que recolocarse solo.

    Que salga como 53 minutos de descuelgue y no como 7 de adelanto es lo que
    hace que se detecte: por eso la cuenta va en circulo.
    """
    assert distancia(31, 24) == 53
    assert conviene_mover([31, 31, 31], disparo_actual=24) == 32


def test_un_vaiven_entre_dos_minutos_no_provoca_baile():
    """Si Blizzard no se decide, mejor quedarse quieto que perseguirlo."""
    assert conviene_mover([23, 40, 23, 40], disparo_actual=33) is None


def test_solo_se_miran_las_ultimas_pasadas():
    """Lo de hace horas no cuenta: importa donde publican ahora."""
    assert conviene_mover([31, 31, 31, 23, 23, 23], disparo_actual=33) == 24


# -- Hablar con cron-job.org ------------------------------------------------


def test_mover_el_disparo_manda_el_patch_documentado(requests_mock):
    requests_mock.patch(API, json={})

    CronJobOrg(api_key="clave", job_id="7788").mover_a(24)

    peticion = requests_mock.request_history[-1]
    assert peticion.method == "PATCH"
    assert peticion.headers["Authorization"] == "Bearer clave"
    assert peticion.json() == {"job": {"schedule": {"minutes": [24]}}}


def test_un_error_de_cron_job_org_se_cuenta(requests_mock):
    requests_mock.patch(API, status_code=401)

    with pytest.raises(DisparoError, match="401"):
        CronJobOrg(api_key="mala", job_id="7788").mover_a(25)


def test_si_no_se_puede_ni_hablar_tampoco_se_traga(requests_mock):
    requests_mock.patch(API, exc=requests.ConnectionError("sin red"))

    with pytest.raises(DisparoError, match="cron-job.org"):
        CronJobOrg(api_key="clave", job_id="7788").mover_a(24)
