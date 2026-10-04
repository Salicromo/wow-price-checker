import pytest

from wowalerts.config import ConfigError, load_config

VALID = """
region: eu
items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
  - name: "Venom Rite Mantle"
    item_id: 12345
    max_price_by_ilvl: { 311: 120000 }
bonus_ilvl_map:
  12843: 311
settings:
  max_workers: 4
"""


def write(tmp_path, text, name="config.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_carga_una_configuracion_valida(tmp_path):
    config = load_config(write(tmp_path, VALID))

    assert config.region == "eu"
    assert config.locale == "en_GB"
    assert len(config.items) == 2
    assert config.items[0].max_price_by_ilvl == {298: 9000, 311: 90000}
    assert config.items[1].item_id == 12345
    assert config.bonus_ilvl_map == {12843: 311}
    assert config.settings.max_workers == 4
    # Las opciones no indicadas conservan su valor por defecto.
    assert config.settings.state_retention_runs == 72


def test_umbral_mas_barato_de_un_objeto(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.items[0].cheapest_threshold_gold == 9000


def test_threshold_gold_devuelve_none_para_un_ilvl_no_listado(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.items[0].threshold_gold(311) == 90000
    assert config.items[0].threshold_gold(305) is None


def test_fichero_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="No encuentro el fichero"):
        load_config(tmp_path / "no-existe.yaml")


def test_yaml_invalido(tmp_path):
    with pytest.raises(ConfigError, match="no es YAML valido"):
        load_config(write(tmp_path, "items: [oops\n  - :"))


def test_region_desconocida(tmp_path):
    with pytest.raises(ConfigError, match="'region'"):
        load_config(write(tmp_path, "region: marte\nitems:\n  - name: x\n    max_price_by_ilvl: {1: 1}\n"))


def test_lista_de_objetos_vacia(tmp_path):
    with pytest.raises(ConfigError, match="'items'"):
        load_config(write(tmp_path, "region: eu\nitems: []\n"))


def test_objeto_repetido(tmp_path):
    text = """
region: eu
items:
  - name: "Repetido"
    max_price_by_ilvl: { 311: 1 }
  - name: "Repetido"
    max_price_by_ilvl: { 311: 2 }
"""
    with pytest.raises(ConfigError, match="repetido"):
        load_config(write(tmp_path, text))


def test_objeto_sin_tabla_de_precios(tmp_path):
    text = 'region: eu\nitems:\n  - name: "Sin precios"\n'
    with pytest.raises(ConfigError, match="max_price_by_ilvl"):
        load_config(write(tmp_path, text))


def test_precio_negativo(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: -5 }\n'
    with pytest.raises(ConfigError, match="mayor que 0"):
        load_config(write(tmp_path, text))


def test_precio_no_numerico(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: "barato" }\n'
    with pytest.raises(ConfigError, match="numeros enteros"):
        load_config(write(tmp_path, text))


def test_ilvl_escrito_como_texto_se_convierte(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { "311": "90000" }\n'
    config = load_config(write(tmp_path, text))
    assert config.items[0].max_price_by_ilvl == {311: 90000}


def test_opcion_de_settings_desconocida(tmp_path):
    text = VALID + "\n  tipo_mal_escrito: 3\n"
    with pytest.raises(ConfigError, match="no reconozco"):
        load_config(write(tmp_path, text))


def test_max_workers_invalido(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\nsettings:\n  max_workers: 0\n'
    with pytest.raises(ConfigError, match="max_workers"):
        load_config(write(tmp_path, text))


def test_umbral_de_fallos_fuera_de_rango(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\nsettings:\n  failure_ratio_threshold: 1.5\n'
    with pytest.raises(ConfigError, match="failure_ratio_threshold"):
        load_config(write(tmp_path, text))


def test_el_config_del_repositorio_es_valido():
    """El config.yaml que se entrega tiene que cargar sin tocarlo."""
    config = load_config("config.yaml")
    assert config.items
    assert config.bonus_ilvl_map


def test_valores_por_defecto_del_reintento_por_volcado_viejo(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings

    assert settings.max_dump_age_minutes == 61
    assert settings.stale_retries == 2
    assert settings.stale_retry_wait_seconds == 120
    assert settings.dump_poll_seconds == 15


def test_se_puede_desactivar_el_reintento(tmp_path):
    text = VALID + "  stale_retries: 0\n"

    assert load_config(write(tmp_path, text)).settings.stale_retries == 0


def test_un_margen_de_menos_de_una_hora_no_vale(tmp_path):
    """Por debajo de 60 se daria por retrasado el volcado bueno."""
    with pytest.raises(ConfigError, match="pasar de 60"):
        load_config(write(tmp_path, VALID + "  max_dump_age_minutes: 45\n"))


def test_el_ajuste_viejo_explica_como_migrar(tmp_path):
    """Quien tenga el 'dump_minute' de antes merece algo mejor que "no lo reconozco"."""
    with pytest.raises(ConfigError, match="max_dump_age_minutes"):
        load_config(write(tmp_path, VALID + "  dump_minute: 31\n"))


def test_dump_poll_seconds_debe_ser_positivo(tmp_path):
    with pytest.raises(ConfigError, match="al menos 1 segundo"):
        load_config(write(tmp_path, VALID + "  dump_poll_seconds: 0\n"))


def test_stale_retries_negativo(tmp_path):
    with pytest.raises(ConfigError, match="no puede ser negativo"):
        load_config(write(tmp_path, VALID + "  stale_retries: -1\n"))


def test_espera_entre_reintentos_demasiado_corta(tmp_path):
    with pytest.raises(ConfigError, match="al menos 1 segundo"):
        load_config(write(tmp_path, VALID + "  stale_retry_wait_seconds: 0\n"))


# -- Ajustes de las ventas --------------------------------------------------


def test_ajustes_de_venta_por_defecto(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings
    assert settings.ah_cut_pct == 5
    assert settings.listing_hours == 12


def test_ah_cut_pct_se_puede_cambiar(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  ah_cut_pct: 0\n"
    )
    assert load_config(write(tmp_path, text)).settings.ah_cut_pct == 0


def test_ah_cut_pct_fuera_de_rango(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  ah_cut_pct: 100\n"
    )
    with pytest.raises(ConfigError, match="ah_cut_pct"):
        load_config(write(tmp_path, text))


def test_listing_hours_fuera_de_rango(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  listing_hours: 0\n"
    )
    with pytest.raises(ConfigError, match="listing_hours"):
        load_config(write(tmp_path, text))


# -- Ventana de silencio ----------------------------------------------------


def test_sin_ventana_de_silencio_por_defecto(tmp_path):
    settings = load_config(write(tmp_path, VALID)).settings
    assert settings.silencio_desde == 0
    assert settings.silencio_hasta == 0
    assert settings.zona_horaria == "Europe/Madrid"


def test_la_ventana_de_silencio_se_lee(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  silencio_desde: 1\n  silencio_hasta: 9\n"
    )
    settings = load_config(write(tmp_path, text)).settings
    assert (settings.silencio_desde, settings.silencio_hasta) == (1, 9)


def test_una_hora_que_no_es_del_reloj_da_error(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        "settings:\n  silencio_desde: 24\n"
    )
    with pytest.raises(ConfigError, match="silencio_desde"):
        load_config(write(tmp_path, text))


def test_una_zona_horaria_inventada_se_detecta_al_arrancar(tmp_path):
    """Mejor fallar al cargar el config que a las 3 de la manana."""
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'
        'settings:\n  zona_horaria: "Europa/Madriz"\n'
    )
    with pytest.raises(ConfigError, match="zona_horaria"):
        load_config(write(tmp_path, text))


SIN_ILVL = """
region: eu
items:
  - name: "Pattern: Arcanoweave Cord"
    max_price: 60000
    avisar_undercut: false
"""


def test_objeto_con_precio_unico_sin_tabla_de_ilvl(tmp_path):
    config = load_config(write(tmp_path, SIN_ILVL))
    regla = config.items[0]

    assert regla.sin_ilvl
    assert regla.max_price == 60000
    # Sea cual sea el ilvl que traiga la subasta, el limite es el mismo.
    assert regla.threshold_gold(311) == 60000
    assert regla.threshold_gold(1) == 60000
    assert regla.cheapest_threshold_gold == 60000
    assert regla.avisar_undercut is False


def test_los_objetos_normales_avisan_de_undercut_por_defecto(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.items[0].avisar_undercut is True
    assert config.items[0].sin_ilvl is False


def test_no_se_puede_poner_las_dos_formas_de_precio(tmp_path):
    text = (
        'region: eu\nitems:\n  - name: "X"\n    max_price: 100\n'
        "    max_price_by_ilvl: { 311: 1 }\n"
    )
    with pytest.raises(ConfigError, match="'max_price' o 'max_price_by_ilvl'"):
        load_config(write(tmp_path, text))


def test_un_objeto_sin_ningun_precio(tmp_path):
    with pytest.raises(ConfigError, match="'max_price' o 'max_price_by_ilvl'"):
        load_config(write(tmp_path, 'region: eu\nitems:\n  - name: "X"\n'))


def test_max_price_tiene_que_ser_un_entero_positivo(tmp_path):
    with pytest.raises(ConfigError, match="max_price"):
        load_config(write(tmp_path, 'region: eu\nitems:\n  - name: "X"\n    max_price: 0\n'))
    with pytest.raises(ConfigError, match="max_price"):
        load_config(
            write(tmp_path, 'region: eu\nitems:\n  - name: "X"\n    max_price: barato\n')
        )


def test_avisar_undercut_tiene_que_ser_si_o_no(tmp_path):
    text = 'region: eu\nitems:\n  - name: "X"\n    max_price: 10\n    avisar_undercut: quizas\n'
    with pytest.raises(ConfigError, match="avisar_undercut"):
        load_config(write(tmp_path, text))


# -- mascotas ---------------------------------------------------------------


def test_una_mascota_se_declara_por_especie(tmp_path):
    config = load_config(write(
        tmp_path,
        """
        region: eu
        items:
          - name: "Gusting Grimoire"
            pet_species_id: 1174
            max_price: 100000
        """,
    ))
    regla = config.items[0]

    assert regla.es_mascota
    assert regla.pet_species_id == 1174
    assert regla.max_price == 100_000


def test_una_mascota_no_puede_llevar_tambien_item_id(tmp_path):
    """Una mascota no tiene objeto propio: en subastas todas son la 82800."""
    with pytest.raises(ConfigError, match="no los dos"):
        load_config(write(
            tmp_path,
            """
            region: eu
            items:
              - name: "Gusting Grimoire"
                pet_species_id: 1174
                item_id: 82800
                max_price: 100000
            """,
        ))


def test_una_mascota_no_lleva_tabla_por_ilvl(tmp_path):
    with pytest.raises(ConfigError, match="no tienen ilvl"):
        load_config(write(
            tmp_path,
            """
            region: eu
            items:
              - name: "Gusting Grimoire"
                pet_species_id: 1174
                max_price_by_ilvl: { 311: 90000 }
            """,
        ))


def test_la_especie_tiene_que_ser_un_numero(tmp_path):
    with pytest.raises(ConfigError, match="pet_species_id"):
        load_config(write(
            tmp_path,
            """
            region: eu
            items:
              - name: "Gusting Grimoire"
                pet_species_id: "mil ciento setenta y cuatro"
                max_price: 100000
            """,
        ))


# -- repostear ----------------------------------------------------------------


CON_RECETA = """
region: eu
items:
  - name: "Grebas"
    max_price: 100
  - name: "Patron"
    max_price: 100
    avisar_undercut: false
  - name: "Receta"
    max_price: 100
    avisar_undercut: false
    repostear: true
  - name: "Montura"
    max_price: 100
    repostear: false
"""


def test_repostear_sin_valor_sigue_a_avisar_undercut(tmp_path):
    config = load_config(write(tmp_path, CON_RECETA))
    grebas, patron, _, _ = config.items

    assert grebas.se_repostea is True
    assert patron.se_repostea is False


def test_repostear_se_enciende_y_se_apaga_aparte_de_los_avisos(tmp_path):
    config = load_config(write(tmp_path, CON_RECETA))
    _, _, receta, montura = config.items

    assert receta.avisar_undercut is False
    assert receta.se_repostea is True
    assert montura.avisar_undercut is True
    assert montura.se_repostea is False


def test_repostear_solo_admite_true_o_false(tmp_path):
    texto = """
region: eu
items:
  - name: "Patron"
    max_price: 100
    repostear: "si"
"""
    with pytest.raises(ConfigError, match="'repostear' solo admite true o false"):
        load_config(write(tmp_path, texto))


def test_repostear_nulo_sigue_a_avisar_undercut(tmp_path):
    texto = """
region: eu
items:
  - name: "Patron"
    max_price: 100
    avisar_undercut: false
    repostear:
"""
    config = load_config(write(tmp_path, texto))

    assert config.items[0].se_repostea is False


def test_personajes_yaml_manda_sobre_config_yaml(tmp_path):
    write(tmp_path, VALID + "orden_personajes:\n  - Publico\n")
    write(tmp_path, "orden_personajes:\n  - Uno\n  - Dos\n", name="personajes.yaml")

    config = load_config(tmp_path / "config.yaml")

    assert config.orden_personajes == ("Uno", "Dos")


def test_sin_personajes_yaml_vale_lo_de_config_yaml(tmp_path):
    config = load_config(write(tmp_path, VALID + "orden_personajes:\n  - Publico\n"))

    assert config.orden_personajes == ("Publico",)


def test_personajes_yaml_sin_la_clave_se_explica(tmp_path):
    write(tmp_path, VALID)
    write(tmp_path, "- Uno\n", name="personajes.yaml")

    with pytest.raises(ConfigError, match="orden_personajes"):
        load_config(tmp_path / "config.yaml")


# -- Pausa de avisos desde la app -------------------------------------------

BASE_PAUSA = 'region: eu\nitems:\n  - name: "X"\n    max_price_by_ilvl: { 311: 1 }\n'


def test_los_avisos_no_estan_pausados_por_defecto(tmp_path):
    assert load_config(write(tmp_path, VALID)).settings.avisos_pausados is False


def test_la_pausa_de_avisos_se_lee(tmp_path):
    text = BASE_PAUSA + "settings:\n  avisos_pausados: true\n"
    assert load_config(write(tmp_path, text)).settings.avisos_pausados is True


def test_una_pausa_que_no_es_si_o_no_da_error(tmp_path):
    """Un 'avisos_pausados: "false"' entre comillas es una cadena, y una cadena
    no vacia es verdadera: se pausaria justo cuando pides lo contrario."""
    text = BASE_PAUSA + 'settings:\n  avisos_pausados: "false"\n'
    with pytest.raises(ConfigError, match="avisos_pausados"):
        load_config(write(tmp_path, text))
