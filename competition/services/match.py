"""Cycle de vie d'un match : report, reprogrammation, annulation, forfait (§54).

La saisie/validation « normale » d'un résultat (double soumission, litige)
est traitée par ``competition.services.result`` — étape 12. Le forfait est un
cas particulier : l'admin/arbitre fixe directement le résultat officiel, il
n'y a rien à réconcilier.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.enums import MatchStatus, OutcomeType, ResultStatus

# Statuts depuis lesquels un match peut encore être reprogrammé / reporté.
_EDITABLE_STATUSES = {MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED}


def reschedule_match(match, *, new_date, new_time=None):
    if match.result_status == ResultStatus.VALIDATED:
        raise ValidationError("Ce match a déjà un résultat validé.")
    match.scheduled_date = new_date
    match.scheduled_time = new_time
    match.status = MatchStatus.SCHEDULED
    match.reschedule_count += 1
    match.save(
        update_fields=[
            "scheduled_date", "scheduled_time", "status", "reschedule_count", "updated_at",
        ]
    )
    return match


def postpone_match(match, *, reason: str = ""):
    if match.status not in _EDITABLE_STATUSES:
        raise ValidationError("Seul un match programmé peut être reporté.")
    match.postponed_from = match.scheduled_date
    match.status = MatchStatus.POSTPONED
    if reason:
        match.notes = reason
    match.save(update_fields=["postponed_from", "status", "notes", "updated_at"])
    return match


def cancel_match(match, *, reason: str = ""):
    if match.result_status == ResultStatus.VALIDATED:
        raise ValidationError("Impossible d'annuler un match déjà validé.")
    match.status = MatchStatus.CANCELLED
    match.outcome_type = OutcomeType.NOT_PLAYED
    match.counts_for_standings = False
    if reason:
        match.notes = reason
    match.save(
        update_fields=["status", "outcome_type", "counts_for_standings", "notes", "updated_at"]
    )
    return match


def declare_forfeit(match, *, loser, declared_by, note: str = ""):
    """Forfait d'un seul joueur : l'autre est déclaré vainqueur avec le score
    technique configuré (``ChampionshipSettings.forfeit_score_*``)."""
    if match.result_status == ResultStatus.VALIDATED:
        raise ValidationError("Ce match a déjà un résultat validé.")
    if loser.id == match.player1_id:
        winner, outcome = match.player2, OutcomeType.FORFEIT_P1
    elif match.player2_id and loser.id == match.player2_id:
        winner, outcome = match.player1, OutcomeType.FORFEIT_P2
    else:
        raise ValidationError("Ce joueur ne fait pas partie de ce match.")
    if winner is None:
        raise ValidationError("Match sans second joueur (exempt) : forfait non applicable.")

    settings_obj = match.championship.settings
    match.outcome_type = outcome
    match.winner = winner
    if winner.id == match.player1_id:
        match.score1 = settings_obj.forfeit_score_for
        match.score2 = settings_obj.forfeit_score_against
    else:
        match.score1 = settings_obj.forfeit_score_against
        match.score2 = settings_obj.forfeit_score_for
    match.status = MatchStatus.FORFEIT
    match.result_status = ResultStatus.VALIDATED
    match.counts_for_standings = True
    match.entered_by = declared_by
    match.entered_at = timezone.now()
    match.validated_by = declared_by
    match.validated_at = timezone.now()
    if note:
        match.notes = note
    match.save()

    from .result import _recompute_standings  # import local : évite un cycle

    _recompute_standings(match)
    return match


def late_matches_queryset(championship):
    """Matchs programmés dont la date prévue dépasse le seuil configuré (§24)."""
    from ..models import Match  # import local : évite un cycle au chargement des apps

    threshold_days = championship.settings.late_match_threshold_days
    cutoff = timezone.localdate() - timedelta(days=threshold_days)
    return Match.objects.filter(
        championship=championship,
        status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING],
        scheduled_date__lt=cutoff,
    )
