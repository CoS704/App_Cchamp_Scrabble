"""Soumission et validation des résultats — cœur anti-double-saisie (§13-15).

Le ``Match`` ne porte jamais qu'UN résultat officiel. Les ``ResultSubmission``
sont les déclarations brutes des uns et des autres ; ce module les réconcilie
sans jamais créer deux résultats concurrents, et sans jamais laisser un
résultat litigieux impacter le classement.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core.enums import MatchStatus, OutcomeType, ResultEntryPolicy, ResultStatus, SubmissionSource
from core.permissions import can_manage_championship, can_referee

from ..models import ResultSubmission


def participation_for_user(user, match):
    """La participation de ``user`` dans ce match, ou ``None`` s'il n'y joue pas."""
    for participation in (match.player1, match.player2):
        if participation and participation.player.user_id == user.id:
            return participation
    return None


def _authorize(match, user, submitting_participation, score1, score2, *, has_pending_opponent_submission):
    """Détermine la source à journaliser, ou lève ``PermissionDenied``.

    Sous ``WINNER_ONLY``, seul le vainqueur (auto-déclaré) peut *initier* la
    saisie d'un match. Une fois une saisie en attente de l'adversaire, l'autre
    joueur peut toujours la *confirmer* (ou la contester) — sans quoi le
    mécanisme de double saisie (§14) serait bloqué : personne ne pourrait
    jamais confirmer un résultat où il apparaît comme perdant.
    """
    championship = match.championship

    if can_manage_championship(user, championship):
        return SubmissionSource.ADMIN
    if can_referee(user, championship, match.division):
        return SubmissionSource.REFEREE

    if submitting_participation is None or submitting_participation.id not in (
        match.player1_id,
        match.player2_id,
    ):
        raise PermissionDenied("Vous ne faites pas partie de ce match.")

    policy = championship.settings.result_entry_policy
    if policy == ResultEntryPolicy.ADMIN_ONLY:
        raise PermissionDenied("Seul un administrateur peut saisir ce résultat.")

    if policy == ResultEntryPolicy.WINNER_ONLY and not has_pending_opponent_submission:
        is_player1 = submitting_participation.id == match.player1_id
        own_score = score1 if is_player1 else score2
        other_score = score2 if is_player1 else score1
        if own_score < other_score:
            raise PermissionDenied(
                "Seul le vainqueur du match est autorisé à saisir le résultat."
            )

    return SubmissionSource.PLAYER


def _record_submission(match, user, participation, score1, score2, winner, source, outcome_type, note):
    # Une nouvelle saisie du même auteur remplace la précédente (jamais deux
    # saisies actives pour la même personne sur le même match).
    ResultSubmission.objects.filter(match=match, submitted_by=user, is_superseded=False).update(
        is_superseded=True
    )
    return ResultSubmission.objects.create(
        match=match,
        submitted_by=user,
        submitted_by_participation=participation,
        score1=score1,
        score2=score2,
        claimed_winner=winner,
        outcome_type=outcome_type,
        source=source,
        note=note,
    )


def _apply_validated(match, score1, score2, winner, outcome_type, user):
    match.score1 = score1
    match.score2 = score2
    match.winner = winner
    match.outcome_type = outcome_type
    match.result_status = ResultStatus.VALIDATED
    match.status = MatchStatus.COMPLETED
    match.counts_for_standings = True
    match.played_at = match.played_at or timezone.now()
    match.entered_by = match.entered_by or user
    match.entered_at = match.entered_at or timezone.now()
    match.validated_by = user
    match.validated_at = timezone.now()
    match.save()
    _recompute_standings(match)

    from notifications.services import notify_result_event  # import local : évite un cycle

    notify_result_event(match, event="validated")


def _recompute_standings(match):
    from rankings.services import compute_standings  # import local : évite un cycle

    compute_standings(championship=match.championship, division=match.division, phase=match.phase)

    if match.bracket_slots.exists():
        from finals.services import advance_bracket

        advance_bracket(match)


def submit_result(
    *,
    match,
    user,
    score1: int,
    score2: int,
    submitting_participation=None,
    outcome_type=OutcomeType.NORMAL,
    note: str = "",
):
    """Point d'entrée unique de saisie — joueur, arbitre ou admin.

    Réconciliation (§14) :
    - saisie d'un admin/arbitre → validée immédiatement (rien à réconcilier,
      et permet la correction d'un résultat déjà validé) ;
    - une seule saisie active côté joueurs → ``SUBMITTED`` (ou validée
      directement si l'édition ne requiert pas de confirmation) ;
    - deux saisies identiques → confirmée, validée automatiquement si
      ``double_entry_auto_confirm`` ;
    - deux saisies différentes → ``DISPUTED``, le classement n'est pas touché.
    """
    if score1 < 0 or score2 < 0:
        raise ValidationError("Les scores ne peuvent pas être négatifs.")

    others = list(
        match.submissions.filter(is_superseded=False)
        .exclude(submitted_by_participation=submitting_participation)
        .exclude(source__in=[SubmissionSource.ADMIN, SubmissionSource.REFEREE])
    )

    source = _authorize(
        match, user, submitting_participation, score1, score2,
        has_pending_opponent_submission=bool(others),
    )

    if match.result_status == ResultStatus.VALIDATED and source not in (
        SubmissionSource.ADMIN,
        SubmissionSource.REFEREE,
    ):
        raise ValidationError(
            "Ce résultat est déjà validé ; seul un administrateur ou un arbitre peut le corriger."
        )

    winner = None
    if score1 > score2:
        winner = match.player1
    elif score2 > score1:
        winner = match.player2

    submission = _record_submission(
        match, user, submitting_participation, score1, score2, winner, source, outcome_type, note
    )

    if source in (SubmissionSource.ADMIN, SubmissionSource.REFEREE):
        _apply_validated(match, score1, score2, winner, outcome_type, user)
        return submission

    settings_obj = match.championship.settings

    if not settings_obj.result_confirmation_required:
        _apply_validated(match, score1, score2, winner, outcome_type, user)
        return submission

    from notifications.services import notify_result_event  # import local : évite un cycle

    if not others:
        match.result_status = ResultStatus.SUBMITTED
        match.save(update_fields=["result_status", "updated_at"])
        notify_result_event(
            match, event="submitted",
            exclude_participation_id=submitting_participation.id if submitting_participation else None,
        )
        return submission

    other = others[0]
    if (
        other.score1 == score1
        and other.score2 == score2
        and other.outcome_type == outcome_type
    ):
        if settings_obj.double_entry_auto_confirm:
            _apply_validated(match, score1, score2, winner, outcome_type, user)
        else:
            match.result_status = ResultStatus.CONFIRMED
            match.save(update_fields=["result_status", "updated_at"])
            notify_result_event(match, event="confirmed")
    else:
        match.result_status = ResultStatus.DISPUTED
        match.status = MatchStatus.DISPUTED
        match.counts_for_standings = False
        match.save(update_fields=["result_status", "status", "counts_for_standings", "updated_at"])
        notify_result_event(match, event="disputed")

    return submission


def reject_result(match, *, user, reason: str = ""):
    """Rejette toute saisie en cours et rouvre le match à une nouvelle saisie."""
    if not (
        can_manage_championship(user, match.championship)
        or can_referee(user, match.championship, match.division)
    ):
        raise PermissionDenied("Seul un administrateur ou un arbitre peut rejeter ce résultat.")

    was_counting = match.counts_for_standings

    ResultSubmission.objects.filter(match=match, is_superseded=False).update(is_superseded=True)
    match.result_status = ResultStatus.REJECTED
    match.status = MatchStatus.SCHEDULED
    match.score1 = None
    match.score2 = None
    match.winner = None
    match.counts_for_standings = False
    if reason:
        match.notes = reason
    match.save()

    if was_counting:
        _recompute_standings(match)

    return match
