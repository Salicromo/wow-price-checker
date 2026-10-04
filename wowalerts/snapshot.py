"""Saber si los datos de subastas que hemos leido son los de esta hora.

Blizzard regenera la casa de subastas una vez por hora y para toda la region a
la vez. El cron dispara poco despues, asi que casi siempre leemos el volcado
recien salido. Pero si Blizzard se retrasa, la pasada se encuentra todavia con
los datos de la hora anterior: ya los miramos, no traen nada nuevo, y hasta la
hora siguiente no habria otra oportunidad.

Aqui se decide si merece la pena esperar y volver a mirar.

La cuenta va por ANTIGUEDAD, no contra un minuto fijo del reloj. Antes se
comparaba contra "Blizzard publica hacia el minuto 31", y el 2 de septiembre de
2026 resulto que habia pasado a publicar hacia el 23: cada pasada se creia
tarde, dormia y reescaneaba los 92 reinos dos veces de balde, y el aviso de
retraso gritaba cada hora sin que pasara nada. La antiguedad no depende del
minuto que elija Blizzard, asi que si vuelven a moverlo no hay nada que
reajustar aqui.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# A partir de cuantos minutos el volcado mas nuevo que existe delata un retraso.
# Como se regenera cada hora, cualquier cosa por encima de 60 significa que el
# de esta hora no ha salido todavia.
#
# Va justo por encima de 60 a proposito. Cuanto mas cerca de la publicacion
# dispare el cron, menos envejece el volcado anterior antes de que lo miremos:
# si publican a y 23 y disparamos a y 25, el viejo tiene 62 minutos, y un margen
# de 65 lo daria por bueno y se tragaria la hora entera. Ser generoso aqui no
# cuesta una espera de mas, cuesta una alerta de menos.
MAX_DUMP_AGE_MINUTES = 61


def dump_age(snapshot_at: datetime, now: datetime) -> timedelta:
    """Cuanto hace que Blizzard publico lo que estamos leyendo."""
    return now - snapshot_at


def falta_para_el_siguiente(snapshot_at: datetime, now: datetime) -> float:
    """Minutos que quedan para que Blizzard publique el volcado siguiente.

    Sale de que se regenera cada hora: si el que tenemos delante salio hace 54
    minutos, el proximo asoma en 6. Negativo significa que ya deberia haber
    salido, o sea que van tarde.

    Sirve para no tragarse un volcado casi caduco. Con el cron disparando justo
    antes de la publicacion --que es lo que pasa cuando Blizzard la mueve mas
    tarde-- cada pasada leeria el de la hora anterior, y un chollo de hace 54
    minutos ya se lo ha llevado alguien. Esperar unos minutos lo arregla en el
    acto, en vez de aguantar asi hasta que el disparo se recoloque.
    """
    return 60 - dump_age(snapshot_at, now).total_seconds() / 60


def dump_is_stale(
    snapshot_at: datetime | None,
    now: datetime,
    max_age_minutes: int = MAX_DUMP_AGE_MINUTES,
) -> bool:
    """True si el volcado mas nuevo que existe delata que Blizzard va tarde.

    No basta con que los datos parezcan viejos: a y 58 un volcado de y 23 tiene
    35 minutos y aun asi es el ultimo que existe, de modo que esperar no
    serviria de nada. Solo cuando pasa de la hora sabemos que falta el de esta
    hora, porque se regenera cada hora.

    Sin `snapshot_at` no hay nada que comparar. Eso pasa cuando ningun reino ha
    respondido, y entonces el problema no es el horario: reintentar solo
    gastaria tiempo.
    """
    if snapshot_at is None:
        return False
    return dump_age(snapshot_at, now) > timedelta(minutes=max_age_minutes)
