"""Génération de la saison suivante à partir du classement final (§10)."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from championships import services as championship_services
from championships.models import Championship, Division
from core.enums import (
    ChampionshipStatus,
    EntryOrigin,
    MovementType,
    MoveType,
    PhaseKind,
    PromotionOutcome,
    TransitionStatus,
)
from participations.models import ChampionshipParticipation

from .models import SeasonTransition, SeasonTransitionMove

_SETTINGS_COPY_FIELDS = [
    "points_win", "points_draw", "points_loss",
    "points_forfeit_win", "points_forfeit_loss",
    "forfeit_score_for", "forfeit_score_against",
    "primary_tiebreak", "round_robin_legs",
    "result_entry_policy", "result_confirmation_required", "double_entry_auto_confirm",
    "late_match_threshold_days",
    "finals_enabled", "finals_qualifiers_count", "finals_format", "finals_third_place",
    "carry_over_between_editions",
]


def _final_standing_rows(championship, division):
    from competition.models import Phase
    from rankings.services import compute_standings

    phase = Phase.objects.filter(
        championship=championship, division=division, kind=PhaseKind.LEAGUE
    ).first()
    if not phase:
        return []
    snapshot = compute_standings(championship=championship, division=division, phase=phase)
    if not snapshot:
        return []
    return list(snapshot.rows.select_related("participation__player").order_by("rank"))


def propose_transition(*, championship, created_by) -> SeasonTransition:
    from championships.services import rule_rank_indices

    if championship.status not in (
        ChampionshipStatus.IN_PROGRESS,
        ChampionshipStatus.FINALS,
        ChampionshipStatus.COMPLETED,
    ):
        raise ValidationError(
            "Le championnat doit être en cours (ou terminé) pour proposer la saison suivante."
        )
    if SeasonTransition.objects.filter(
        from_championship=championship,
        status__in=[TransitionStatus.PROPOSED, TransitionStatus.ADJUSTED, TransitionStatus.CONFIRMED],
    ).exists():
        raise ValidationError("Une transition est déjà en cours ou confirmée pour cette édition.")

    transition = SeasonTransition.objects.create(from_championship=championship, created_by=created_by)

    for division in championship.divisions.all():
        rows = _final_standing_rows(championship, division)
        n = len(rows)
        ordered_ids = [row.participation_id for row in rows]

        target_division_by_pid: dict[int, Division | None] = {}
        move_type_by_pid: dict[int, str] = {}
        rules = championship.movement_rules.filter(source_division=division, is_active=True).order_by(
            "priority"
        )
        for rule in rules:
            move_type = MoveType.PROMOTED if rule.movement_type == MovementType.PROMOTION else MoveType.RELEGATED
            for idx in rule_rank_indices(rule, n):
                if 1 <= idx <= n:
                    pid = ordered_ids[idx - 1]
                    target_division_by_pid.setdefault(pid, rule.target_division)
                    move_type_by_pid.setdefault(pid, move_type)

        for row in rows:
            pid = row.participation_id
            target_division = target_division_by_pid.get(pid, division)
            move_type = move_type_by_pid.get(pid, MoveType.KEPT)
            to_key = target_division.carryover_key if target_division else ""
            SeasonTransitionMove.objects.create(
                transition=transition,
                source_participation=row.participation,
                player=row.participation.player,
                from_carryover_key=division.carryover_key,
                to_carryover_key=to_key,
                move_type=move_type,
            )

    return transition


@transaction.atomic
def confirm_transition(*, transition: SeasonTransition, confirmed_by, new_name: str, new_season: str) -> Championship:
    if transition.status == TransitionStatus.CONFIRMED:
        raise ValidationError("Cette transition a déjà été confirmée.")
    if transition.status == TransitionStatus.CANCELLED:
        raise ValidationError("Cette transition a été annulée.")

    source = transition.from_championship

    new_championship = Championship.objects.create(
        series=source.series,
        name=new_name,
        season=new_season,
        previous_edition=source,
        created_by=confirmed_by,
    )
    settings_obj = championship_services.initialize_championship(new_championship)
    source_settings = source.settings
    for field in _SETTINGS_COPY_FIELDS:
        setattr(settings_obj, field, getattr(source_settings, field))
    settings_obj.save()
    championship_services.regenerate_tiebreak_chain(new_championship, settings_obj.primary_tiebreak)

    new_divisions: dict[str, Division] = {}
    for division in source.divisions.all():
        new_divisions[division.carryover_key] = Division.objects.create(
            championship=new_championship,
            name=division.name,
            level=division.level,
            carryover_key=division.carryover_key,
            capacity_min=division.capacity_min,
            capacity_max=division.capacity_max,
            is_unlimited=division.is_unlimited,
            color=division.color,
            description=division.description,
        )

    outcome_by_move_type = {
        MoveType.PROMOTED: (EntryOrigin.PROMOTED_FROM, PromotionOutcome.PROMOTED),
        MoveType.RELEGATED: (EntryOrigin.RELEGATED_FROM, PromotionOutcome.RELEGATED),
        MoveType.KEPT: (EntryOrigin.KEPT, PromotionOutcome.STAYED),
        MoveType.MANUAL_OVERRIDE: (EntryOrigin.MANUAL, PromotionOutcome.STAYED),
    }

    for move in transition.moves.select_related("player", "source_participation").all():
        target_division = new_divisions.get(move.to_carryover_key)
        entry_origin, promotion_outcome = outcome_by_move_type.get(
            move.move_type, (EntryOrigin.KEPT, PromotionOutcome.STAYED)
        )

        move.source_participation.promotion_outcome = promotion_outcome
        move.source_participation.resulting_division_carryover_key = move.to_carryover_key
        move.source_participation.save(
            update_fields=["promotion_outcome", "resulting_division_carryover_key"]
        )

        if target_division is None:
            continue  # sortie de structure : pas de réinscription automatique

        ChampionshipParticipation.objects.create(
            championship=new_championship,
            player=move.player,
            division=target_division,
            entry_origin=entry_origin,
            source_participation=move.source_participation,
        )

    transition.to_championship = new_championship
    transition.status = TransitionStatus.CONFIRMED
    transition.confirmed_by = confirmed_by
    transition.save(update_fields=["to_championship", "status", "confirmed_by", "updated_at"])

    if source.status not in (ChampionshipStatus.COMPLETED, ChampionshipStatus.ARCHIVED):
        source.status = ChampionshipStatus.COMPLETED
        source.save(update_fields=["status", "updated_at"])

    return new_championship
