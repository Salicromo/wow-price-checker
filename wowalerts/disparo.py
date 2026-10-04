"""Mantener el disparo del cron pegado a la hora a la que publica Blizzard.

El volcado de subastas no sale siempre al mismo minuto: el 2026-08-31 salia a
las :31:22 y el 2026-09-02 a las :23:30. Cuando se mueve no se rompe nada, solo
llegan los avisos mas tarde, que es la clase de deterioro del que no te enteras
nunca. Y perseguirlo a mano exige leerse el log de Actions cada semana.

Asi que la pasada apunta a que minuto ha publicado Blizzard, y cuando varias
seguidas coinciden en que el disparo se ha quedado descolgado, lo mueve.

El disparo vive en cron-job.org, fuera de este repositorio, asi que moverlo es
una llamada a su API. Sin credenciales configuradas no se mueve nada y se avisa
por Discord para que lo cambies tu.

Durante las horas de silencio no se mide nada, porque esto acaba mandando un
aviso. No se pierde: un cambio de horario dura semanas y quedan 16 pasadas
despiertas al dia para cazarlo.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

MINUTOS = 60

# Cuantas pasadas seguidas tienen que coincidir antes de mover el disparo. Una
# sola no vale: si Blizzard tiene un mal dia y publica tarde una hora suelta,
# mover el cron detras de ese tropiezo lo dejaria mal puesto el resto del dia.
PASADAS_QUE_TIENEN_QUE_COINCIDIR = 3

# Cuanto pueden bailar entre si esas pasadas y seguir contando como acuerdo.
# Blizzard no publica al segundo exacto y un minuto de vaiven es normal.
VAIVEN_TOLERADO = 1

# Margen entre la publicacion y el disparo, en minutos.
#
# Fue 2 mientras llegar pronto salia caro. Ya no: si la pasada se encuentra el
# volcado sin publicar, espera sondeando cada 15 segundos y escanea en cuanto
# sale, asi que adelantarse ya no cuesta la hora.
#
# Y llegar tarde si cuesta: de los 135 segundos que tardaba un aviso en salir,
# 90 eran este colchon. Con 1 se recortan a 30 y el aviso sale a los 75 s de
# publicarse, la mitad que antes.
#
# No se baja a 0. Disparar en el minuto exacto de la publicacion obliga a
# esperar medio minuto casi siempre, y GitHub redondea cada trabajo al minuto
# entero: pasariamos de 1 a 2 minutos facturados por pasada --el doble de
# cuota-- para ganar 40 segundos.
COLCHON_TRAS_EL_VOLCADO = 1

# Cuanto puede descolgarse el disparo antes de que merezca la pena moverlo.
#
# Era 6, y eso toleraba hasta seis minutos de latencia regalada: el aviso salia
# hasta seis minutos mas tarde de lo necesario y nada lo corregia. Como el
# colchon bueno es de 1 minuto, cualquier cosa que se pase de ahi ya es peor de
# lo que se puede tener.
#
# No baja de 1 para no perseguir el vaiven normal de Blizzard, que no publica al
# segundo exacto.
DESCUELGUE_QUE_MERECE_MOVERLO = 1

# Un reajuste de este tamano o menor se hace igual, pero sin avisar por Discord:
# es afinar, no arreglar una averia, y no merece una notificacion.
REAJUSTE_QUE_NO_MERECE_AVISO = 2


class DisparoError(Exception):
    """No se ha podido mover el disparo."""


def distancia(desde: int, hasta: int) -> int:
    """Minutos que hay que avanzar en el reloj para ir de uno a otro.

    En circulo, porque el reloj da la vuelta: de y 58 a y 03 hay 5 minutos, no
    55 hacia atras.
    """
    return (hasta - desde) % MINUTOS


def hay_acuerdo(minutos: list[int]) -> bool:
    """Si esas observaciones apuntan todas al mismo momento.

    Se mira en circulo para que publicar a y 59 y a y 00 cuente como acuerdo, y
    no como el desacuerdo mas grande posible.
    """
    if len(minutos) < PASADAS_QUE_TIENEN_QUE_COINCIDIR:
        return False
    referencia = minutos[-1]
    return all(
        min(distancia(referencia, m), distancia(m, referencia)) <= VAIVEN_TOLERADO
        for m in minutos
    )


def minuto_recomendado(publicado: int) -> int:
    return (publicado + COLCHON_TRAS_EL_VOLCADO) % MINUTOS


def la_mas_tardia(minutos: list[int]) -> int:
    """De unas publicaciones que ya sabemos parecidas, la que llego mas tarde.

    Sirve de referencia estable. Si se tomara la ultima observacion a secas y
    Blizzard alternase entre y 23 y y 24, el objetivo bailaria entre y 24 y y 25
    y el cron se pasaria el dia moviendose de uno a otro.

    Se mide en circulo respecto a la ultima para que publicar a y 59 y a y 00 no
    se lea como 59 minutos de diferencia: ahi la mas tardia es la de y 00.
    """
    referencia = minutos[-1]
    desfases = [((m - referencia + 30) % 60) - 30 for m in minutos]
    return (referencia + max(desfases)) % MINUTOS


def conviene_mover(observadas: list[int], disparo_actual: int) -> int | None:
    """A que minuto mover el disparo, o None si esta bien donde esta.

    `observadas` son los minutos a los que Blizzard ha publicado en las ultimas
    pasadas, la mas reciente al final.
    """
    ultimas = observadas[-PASADAS_QUE_TIENEN_QUE_COINCIDIR:]
    if not hay_acuerdo(ultimas):
        return None

    publicado = la_mas_tardia(ultimas)

    # Cuanto tarda el disparo en llegar despues de la publicacion. Medido en
    # circulo, asi que disparar ANTES de que publiquen sale como un numero
    # enorme, que es justo lo que queremos: es el caso mas urgente de arreglar,
    # porque la espera esta acotada y pasarse pierde la hora entera.
    descuelgue = distancia(publicado, disparo_actual)
    if descuelgue <= DESCUELGUE_QUE_MERECE_MOVERLO:
        return None

    objetivo = minuto_recomendado(publicado)
    return objetivo if objetivo != disparo_actual else None


@dataclass(frozen=True)
class CronJobOrg:
    """El trocito de la API de cron-job.org que hace falta para esto.

    Documentado en https://docs.cron-job.org/rest-api.html: se autentica con un
    token Bearer y el horario se cambia con un PATCH del trabajo.
    """

    api_key: str
    job_id: str
    timeout: int = 30
    base_url: str = "https://api.cron-job.org"

    def mover_a(self, minuto: int) -> None:
        """Deja el trabajo disparando una vez por hora, a ese minuto."""
        try:
            respuesta = requests.patch(
                f"{self.base_url}/jobs/{self.job_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"job": {"schedule": {"minutes": [minuto]}}},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DisparoError(f"No he podido hablar con cron-job.org: {exc}") from exc

        if respuesta.status_code >= 400:
            raise DisparoError(
                f"cron-job.org ha respondido HTTP {respuesta.status_code} al mover "
                f"el disparo al minuto {minuto}."
            )
