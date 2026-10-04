"""La lectura de la traza de reposteo que el addon deja en SavedVariables."""

from __future__ import annotations

import pytest

from wowalerts.misubastas import MisSubastasError
from wowalerts.traza import (
    analizar,
    extraer_lineas,
    formatear,
    leer_traza,
    parsear,
    partir_sesiones,
)


def envolver(*lineas: str) -> str:
    """Un SavedVariables con esas lineas de traza dentro, como lo escribe WoW."""
    cuerpo = "\n".join(f'\t\t"{linea}",' for linea in lineas)
    return 'WowAlertsExportDB = {\n\t["trazaReposteo"] = {\n' + cuerpo + "\n\t},\n}\n"


# ---------------------------------------------------------------------------
#  Sacar las lineas del fichero
# ---------------------------------------------------------------------------


def test_extrae_las_cadenas_de_la_tabla():
    texto = envolver("11:29:56 5174.9 casa abierta", "11:29:57 5175.1 busco 1:2:0 (1/1)")
    assert extraer_lineas(texto) == [
        "11:29:56 5174.9 casa abierta",
        "11:29:57 5175.1 busco 1:2:0 (1/1)",
    ]


def test_sin_traza_devuelve_una_lista_vacia():
    # Con TRAZA apagada, o antes de usar el reposteo, el campo no existe. No es
    # un error: el resto del volcado sigue siendo valido.
    assert extraer_lineas('WowAlertsExportDB = {\n\t["huella"] = "{}",\n}\n') == []


def test_deshace_los_escapes_de_wow():
    texto = envolver('el juego dice: \\"No se ha encontrado el objeto\\"')
    assert extraer_lineas(texto) == ['el juego dice: "No se ha encontrado el objeto"']


def test_deshace_los_codigos_decimales():
    # WoW escribe los caracteres no imprimibles como \ddd.
    assert extraer_lineas(envolver("roto\\195\\169")) == ["rotoÃ©"]


def test_una_cadena_sin_cerrar_es_un_fichero_corrupto():
    with pytest.raises(MisSubastasError):
        extraer_lineas('["trazaReposteo"] = {\n\t"sin cerrar,\n')


def test_no_se_come_lo_que_hay_detras_de_la_tabla():
    texto = envolver("11:29:56 5174.9 casa abierta") + '["huella"] = "no soy traza",\n'
    assert extraer_lineas(texto) == ["11:29:56 5174.9 casa abierta"]


# ---------------------------------------------------------------------------
#  Partir cada linea
# ---------------------------------------------------------------------------


def test_parte_hora_reloj_y_texto():
    (linea,) = parsear(["15:45:56 20535.1 busco 271440:308:0 (1/9)"])
    assert linea.hora == "15:45:56"
    assert linea.reloj == pytest.approx(20535.1)
    assert linea.texto == "busco 271440:308:0 (1/9)"


def test_una_linea_que_no_encaja_se_salta():
    # La traza se escribe con pcall y un formato fallido deja el texto crudo:
    # que eso no tumbe la lectura del resto.
    assert parsear(["basura sin marca de tiempo"]) == []


# ---------------------------------------------------------------------------
#  Sesiones
# ---------------------------------------------------------------------------


def test_el_reloj_hacia_atras_corta_la_sesion():
    # GetTime() cuenta desde que arranco el juego: si baja, es otra sesion.
    lineas = parsear(
        [
            "11:00:00 100.0 casa abierta",
            "11:00:01 101.0 casa abierta",
            "18:00:00 50.0 casa abierta",
        ]
    )
    assert [len(s) for s in partir_sesiones(lineas)] == [2, 1]


def test_un_hueco_entre_sesiones_no_cuenta_como_espera():
    # Sin cortar, el buzon de una sesion y el de la siguiente darian un hueco
    # de miles de segundos que no espero nadie.
    lineas = parsear(
        [
            "11:00:00 100.0 buzon: recojo la carta 1 (1:1)",
            "18:00:00 50.0 buzon: recojo la carta 1 (1:1)",
        ]
    )
    assert analizar(lineas).cartas == []


# ---------------------------------------------------------------------------
#  Las busquedas
# ---------------------------------------------------------------------------


def test_mide_lo_que_tarda_cada_busqueda():
    lineas = parsear(
        [
            "15:45:56 20535.1 busco 271440:308:0 (1/1)",
            "15:45:56 20535.4 271440:308:0: 2 resultados, 1 tuyas, 0 adelantadas, 0 devueltas",
        ]
    )
    (latencia,) = analizar(lineas).latencias
    assert latencia == pytest.approx(0.3)


def test_la_respuesta_de_otro_objeto_no_cierra_la_busqueda_en_curso():
    lineas = parsear(
        [
            "15:45:56 20535.1 busco 271440:308:0 (1/1)",
            "15:45:56 20535.4 999999:1:0: 1 resultados, 0 tuyas, 0 adelantadas, 0 devueltas",
        ]
    )
    assert analizar(lineas).latencias == []


def test_cuenta_las_busquedas_sin_respuesta():
    lineas = parsear(
        [
            "15:45:56 20535.1 busco 271440:308:0 (1/1)",
            "15:46:06 20545.1 sin respuesta de 271440:308:0 en 10 s: se salta",
        ]
    )
    informe = analizar(lineas)
    assert informe.sin_respuesta == 1
    assert informe.latencias == []


def test_mide_el_escaneo_entero():
    lineas = parsear(
        [
            "15:45:56 20535.0 busco 1:1:0 (1/2)",
            "15:45:56 20535.2 1:1:0: 1 resultados, 1 tuyas, 0 adelantadas, 0 devueltas",
            "15:45:57 20536.0 busco 2:1:0 (2/2)",
            "15:45:57 20536.2 2:1:0: 1 resultados, 1 tuyas, 0 adelantadas, 0 devueltas",
            "15:45:58 20537.0 busqueda terminada. Cola: 0 por cancelar",
        ]
    )
    assert analizar(lineas).escaneos == [(2, pytest.approx(2.0))]


def test_cuenta_las_esperas_por_la_casa_ocupada():
    lineas = parsear(["15:45:56 20535.1 casa ocupada: la busqueda 3/9 espera"])
    assert analizar(lineas).casa_ocupada == 1


# ---------------------------------------------------------------------------
#  Las pulsaciones
# ---------------------------------------------------------------------------


def test_separa_las_pulsaciones_que_hicieron_algo():
    lineas = parsear(
        [
            "15:34:21 19840.6 [Postear] -> postear 271440 ilvl 305 a 74999g"
            " (pide confirmar: false). Ahora dice [Posteando...]",
            "15:34:22 19840.8 [Postear] -> nada: la casa esta ocupada con otra"
            " consulta. Ahora dice [Postear]",
        ]
    )
    informe = analizar(lineas)
    assert informe.utiles == {"postear": 1}
    assert informe.vacias == {"la casa esta ocupada con otra consulta": 1}
    assert informe.pulsaciones == 2


def test_el_mismo_motivo_con_distintos_numeros_se_agrupa():
    lineas = parsear(
        [
            "15:45:55 20534.6 [Buscando 1/9...] -> nada: buscando 1/9. Ahora dice [Buscando 1/9...]",
            "15:45:56 20535.2 [Buscando 2/9...] -> nada: buscando 2/9. Ahora dice [Buscando 2/9...]",
        ]
    )
    assert analizar(lineas).vacias == {"buscando N/N": 2}


def test_el_volcado_de_la_cola_no_hace_unico_cada_motivo():
    lineas = parsear(
        [
            "15:34:23 19841.7 [Nada que repostear] -> nada: nada que cancelar ni"
            " postear. Cola: 0 por cancelar (0 sin confirmar), 0 cancelando."
            " Ahora dice [Nada que repostear]",
            "15:34:23 19841.9 [Nada que repostear] -> nada: nada que cancelar ni"
            " postear. Cola: 1 por cancelar (1 sin confirmar), 0 cancelando."
            " Ahora dice [Nada que repostear]",
        ]
    )
    assert analizar(lineas).vacias == {"nada que cancelar ni postear": 2}


# ---------------------------------------------------------------------------
#  El buzon
# ---------------------------------------------------------------------------


def test_mide_el_ritmo_entre_cartas():
    lineas = parsear(
        [
            "15:34:19 19838.5 buzon: recojo la carta 1 (271444:308)",
            "15:34:20 19838.8 buzon: recojo la carta 1 (271440:305)",
        ]
    )
    (hueco,) = analizar(lineas).cartas
    assert hueco == pytest.approx(0.3)


def test_dos_viajes_al_buzon_no_se_miden_como_uno():
    # Entre tanda y tanda esta el tiempo que tardas tu en volver, no el addon.
    lineas = parsear(
        [
            "15:34:19 19838.5 buzon: recojo la carta 1 (271444:308)",
            "15:40:00 20180.0 buzon: recojo la carta 1 (271440:305)",
        ]
    )
    assert analizar(lineas).cartas == []


# ---------------------------------------------------------------------------
#  El informe y la lectura de fichero
# ---------------------------------------------------------------------------


def test_lee_un_fichero_de_savedvariables(tmp_path):
    fichero = tmp_path / "WowAlertsExport.lua"
    fichero.write_text(envolver("11:29:56 5174.9 casa abierta"), encoding="utf-8")
    (linea,) = leer_traza(fichero)
    assert linea.texto == "casa abierta"


def test_un_fichero_que_no_existe_lo_dice_claro(tmp_path):
    with pytest.raises(MisSubastasError):
        leer_traza(tmp_path / "no_existe.lua")


def test_el_informe_de_una_traza_vacia_no_revienta():
    texto = formatear(analizar([]), "cuenta")
    assert "Sin traza" in texto


def test_el_informe_lleva_las_cifras_principales():
    lineas = parsear(
        [
            "15:45:56 20535.0 busco 1:1:0 (1/1)",
            "15:45:56 20535.2 1:1:0: 1 resultados, 1 tuyas, 0 adelantadas, 0 devueltas",
            "15:45:57 20536.0 busqueda terminada. Cola: 0 por cancelar",
            "15:45:58 20537.0 [Postear] -> postear 1 ilvl 1 a 1g. Ahora dice [Posteando...]",
        ]
    )
    texto = formatear(analizar(lineas), "403840080#2")
    assert "403840080#2" in texto
    assert "1 respondidas" in texto
    assert "postear 1" in texto
