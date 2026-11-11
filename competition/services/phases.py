"""Aides communes aux formats de compétition (ligue, groupes, suisse, élimination).

Un « classement » est calculé par phase de type ligue, groupe ou suisse ;
les phases d'élimination directe n'en ont pas (le tableau fait foi).
"""
from __future__ import annotations

from core.enums import CompetitionFormat, PhaseKind

STANDINGS_KINDS = (PhaseKind.LEAGUE, PhaseKind.GROUP, PhaseKind.SWISS)

KNOCKOUT_FORMATS = (CompetitionFormat.GROUPS_KNOCKOUT, CompetitionFormat.KNOCKOUT)


def has_knockout_stage(settings_obj) -> bool:
    """Vrai si la compétition se conclut par un tableau à élimination directe."""
    return settings_obj.competition_format in KNOCKOUT_FORMATS or settings_obj.finals_enabled


def standings_phases(championship, division) -> list:
    from ..models import Phase

    return list(
        Phase.objects.filter(
            championship=championship, division=division, kind__in=STANDINGS_KINDS
        ).order_by("order", "id")
    )


def phase_participations(phase, division):
    """Joueurs concernés par un classement : les membres du groupe si la phase
    en définit, sinon tous les joueurs de la division."""
    if phase.pk and phase.participants.exists():
        return phase.participants.all()
    return division.participations.all()


def standings_phase_for(participation):
    """Phase de classement où figure ce joueur (son groupe, ou la phase unique)."""
    phases = standings_phases(participation.championship, participation.division)
    for phase in phases:
        if phase.kind == PhaseKind.GROUP:
            if phase.participants.filter(pk=participation.pk).exists():
                return phase
        else:
            return phase
    return None
