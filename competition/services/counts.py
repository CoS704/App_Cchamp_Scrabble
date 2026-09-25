"""Compteurs de matchs d'une inscription (aide à la validation, §24)."""
from __future__ import annotations

from django.db.models import Count, Q

from core.enums import OutcomeType, ResultStatus

from .daily_limit import matches_played_today


def participation_match_counts(participation, *, exclude_match=None) -> dict:
    """Combien de matchs ``participation`` a déjà joués / doit encore jouer.

    ``exclude_match`` écarte le match en cours de validation, pour que « déjà
    joués » se lise comme « avant celui-ci ».
    """
    from ..models import Match

    qs = Match.objects.filter(Q(player1=participation) | Q(player2=participation))
    if exclude_match is not None:
        qs = qs.exclude(pk=exclude_match.pk)
    counts = qs.aggregate(
        total=Count("id"),
        played=Count(
            "id",
            filter=Q(result_status=ResultStatus.VALIDATED, outcome_type=OutcomeType.NORMAL),
        ),
        forfeits=Count(
            "id",
            filter=Q(result_status=ResultStatus.VALIDATED) & ~Q(outcome_type=OutcomeType.NORMAL),
        ),
        awaiting=Count(
            "id", filter=Q(result_status__in=[ResultStatus.SUBMITTED, ResultStatus.CONFIRMED])
        ),
    )
    counts["remaining"] = (
        counts["total"] - counts["played"] - counts["forfeits"] - counts["awaiting"]
    )
    counts["played_today"] = matches_played_today(participation)
    return counts
