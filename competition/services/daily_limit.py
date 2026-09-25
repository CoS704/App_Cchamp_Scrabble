"""Limite de matchs par jour et par joueur (réglage d'édition).

Quand un joueur a joué tous les matchs de sa journée calendaire, son prochain
adversaire ne lui est pas dévoilé avant le lendemain.

Le « jour » est le **jour calendaire prévu** du match (``scheduled_date``), pas
le moment où il est joué : un match en retard (prévu un jour passé) n'est pas
un match du jour, ne consomme donc pas le quota d'aujourd'hui, et reste
toujours accessible. Avec une limite de N matchs/jour, le calendrier regroupe
N journées sur une même date (voir ``scheduling.redate_league_calendar``).

Repli : une édition dont le calendrier n'a aucune date (matchs non datés) n'a
pas de « jour calendaire » ; on compte alors, comme avant, les matchs joués
aujourd'hui d'après l'horodatage du résultat.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from core.enums import OutcomeType, ResultStatus

# Un résultat saisi (même en attente de confirmation ou contesté) compte comme
# match joué : sinon on pourrait contourner la limite en ne confirmant pas.
_PLAYED_RESULT_STATUSES = [
    ResultStatus.SUBMITTED,
    ResultStatus.CONFIRMED,
    ResultStatus.VALIDATED,
    ResultStatus.DISPUTED,
]


def _participation_matches(participation):
    from ..models import Match

    return Match.objects.filter(Q(player1=participation) | Q(player2=participation))


def _played_q():
    return Q(result_status__in=_PLAYED_RESULT_STATUSES, outcome_type=OutcomeType.NORMAL)


def uses_calendar_days(participation) -> bool:
    """Vrai si le calendrier du joueur porte des dates (jours calendaires)."""
    return _participation_matches(participation).filter(scheduled_date__isnull=False).exists()


def todays_scheduled_matches_qs(participation, *, today=None):
    """Matchs prévus aujourd'hui (jour local), joués ou non."""
    today = today or timezone.localdate()
    return _participation_matches(participation).filter(scheduled_date=today)


def late_unplayed_matches_qs(participation, *, today=None):
    """Matchs non joués dont la date prévue est passée (en retard)."""
    from core.enums import MatchStatus

    today = today or timezone.localdate()
    return _participation_matches(participation).filter(
        scheduled_date__lt=today,
        status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED],
        result_status__in=[ResultStatus.NONE, ResultStatus.REJECTED],
    )


def matches_played_today_qs(participation, *, today=None):
    """Matchs du jour déjà joués (quota consommé).

    Avec un calendrier daté : les matchs **prévus aujourd'hui** dont un
    résultat est saisi. Sans dates (repli) : les matchs dont le résultat a été
    validé/saisi aujourd'hui. Forfaits et matchs non joués exclus.
    """
    today = today or timezone.localdate()
    if uses_calendar_days(participation):
        return todays_scheduled_matches_qs(participation, today=today).filter(_played_q())
    return (
        _participation_matches(participation)
        .filter(_played_q())
        .filter(
            Q(played_at__date=today)
            | Q(submissions__submitted_at__date=today, submissions__is_superseded=False)
        )
        .distinct()
    )


def matches_played_today(participation, *, today=None) -> int:
    return matches_played_today_qs(participation, today=today).count()


def daily_limit_status(participation, *, today=None) -> dict | None:
    """``None`` si l'édition n'a pas de limite, sinon l'état du jour."""
    limit = participation.championship.settings.max_matches_per_day
    if not limit:
        return None
    played = matches_played_today(participation, today=today)
    return {"limit": limit, "played_today": played, "reached": played >= limit}


def next_opponent_hidden(participation, *, today=None) -> bool:
    status = daily_limit_status(participation, today=today)
    return bool(status and status["reached"])


def match_is_late(match, *, today=None) -> bool:
    """Match non joué dont la date prévue est déjà passée."""
    today = today or timezone.localdate()
    return match.scheduled_date is not None and match.scheduled_date < today
