"""Limite de matchs par jour et par joueur (réglage d'édition).

Quand un joueur a atteint le nombre de matchs autorisé pour la journée, son
prochain adversaire ne lui est pas dévoilé avant le lendemain.
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


def matches_played_today(participation, *, today=None) -> int:
    """Nombre de matchs joués aujourd'hui (jour local) par ``participation``.

    Un match est « joué aujourd'hui » si son résultat a été validé aujourd'hui
    (``played_at``) ou si une saisie de résultat a été faite aujourd'hui. Les
    forfaits et matchs non joués ne comptent pas.
    """
    from ..models import Match

    today = today or timezone.localdate()
    return (
        Match.objects.filter(Q(player1=participation) | Q(player2=participation))
        .filter(result_status__in=_PLAYED_RESULT_STATUSES, outcome_type=OutcomeType.NORMAL)
        .filter(
            Q(played_at__date=today)
            | Q(submissions__submitted_at__date=today, submissions__is_superseded=False)
        )
        .distinct()
        .count()
    )


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
