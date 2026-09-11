"""Génération et progression du tableau final (§36).

Le tableau n'est jamais codé en dur sur un format 1v4/2v3 : la taille et
l'algorithme de tirage (méthode standard, séparant les têtes de série)
s'appliquent à n'importe quelle puissance de 2. Chaque « case » du tableau
est un match ordinaire (``competition.Match``) : la saisie/validation du
résultat réutilise exactement le même circuit que la phase de ligue.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from championships.models import Division
from core.enums import PhaseKind, ResultStatus

from .models import Bracket, BracketSlot


def _standard_seed_order(n: int) -> list[int]:
    """Ordre de tirage à élimination directe qui sépare les têtes de série
    jusqu'à la finale. Ex. n=4 -> [1, 4, 2, 3] (demi-finales 1v4, 2v3)."""
    if n == 1:
        return [1]
    previous = _standard_seed_order(n // 2)
    order = []
    for seed in previous:
        order.append(seed)
        order.append(n + 1 - seed)
    return order


def _rounds_count(size: int) -> int:
    return size.bit_length() - 1


def _phase_kind_for_round(round_index: int, total_rounds: int, is_third_place: bool) -> str:
    if is_third_place:
        return PhaseKind.THIRD_PLACE
    if round_index == total_rounds - 1:
        return PhaseKind.FINAL
    if round_index == total_rounds - 2:
        return PhaseKind.SEMI_FINAL
    return PhaseKind.PLAYOFF


def _get_or_create_phase(championship, division, kind, order):
    from competition.models import Phase

    phase, _ = Phase.objects.get_or_create(
        championship=championship,
        division=division,
        kind=kind,
        order=order,
        defaults={"name": dict(PhaseKind.choices).get(kind, kind)},
    )
    return phase


@transaction.atomic
def generate_bracket(*, championship, division: Division) -> Bracket:
    settings_obj = championship.settings
    if not settings_obj.finals_enabled:
        raise ValidationError("La phase finale n'est pas activée pour ce championnat.")

    if Bracket.objects.filter(championship=championship, division=division).exists():
        raise ValidationError("Un tableau final existe déjà pour cette division.")

    from competition.models import Phase
    from rankings.services import compute_standings

    league_phase = Phase.objects.filter(
        championship=championship, division=division, kind=PhaseKind.LEAGUE
    ).first()
    if not league_phase:
        raise ValidationError("Aucune phase de ligue trouvée pour cette division.")

    snapshot = compute_standings(championship=championship, division=division, phase=league_phase)
    if not snapshot:
        raise ValidationError("Classement indisponible : aucun joueur dans cette division.")

    n = settings_obj.finals_qualifiers_count
    if n < 2 or (n & (n - 1)) != 0:
        raise ValidationError("Le nombre de qualifiés doit être une puissance de 2 (2, 4, 8…).")

    rows = list(snapshot.rows.select_related("participation").order_by("rank")[:n])
    if len(rows) < n:
        raise ValidationError(
            f"Seuls {len(rows)} joueur(s) classé(s) : {n} qualifiés requis pour la phase finale."
        )
    if snapshot.has_unresolved_tie:
        raise ValidationError(
            "Le classement de ligue comporte une égalité non résolue : "
            "tranchez-la avant de générer la phase finale."
        )

    seeds = [row.participation for row in rows]
    total_rounds = _rounds_count(n)
    seed_positions = _standard_seed_order(n)

    bracket = Bracket.objects.create(
        championship=championship,
        division=division,
        size=n,
        format={"seeding": "standard", "qualifiers": n},
        phase=_get_or_create_phase(
            championship, division, PhaseKind.FINAL if total_rounds == 1 else PhaseKind.SEMI_FINAL, order=1
        ),
    )

    round0_slots = []
    for position, seed_number in enumerate(seed_positions):
        slot = BracketSlot.objects.create(
            bracket=bracket,
            round_index=0,
            position=position,
            seed=seed_number,
            participation=seeds[seed_number - 1],
        )
        round0_slots.append(slot)

    slots_by_round = {0: round0_slots}
    for r in range(1, total_rounds):
        previous = slots_by_round[r - 1]
        current = []
        for i in range(len(previous) // 2):
            # convention : source_slot_win référence le 1er slot du jeu ;
            # les deux slots d'un jeu partagent le même ``match``.
            slot = BracketSlot.objects.create(
                bracket=bracket, round_index=r, position=i, source_slot_win=previous[2 * i],
            )
            current.append(slot)
        slots_by_round[r] = current

    if settings_obj.finals_third_place and total_rounds >= 2:
        semis = slots_by_round[total_rounds - 2]
        for i, slot_index in enumerate((0, 2)):
            BracketSlot.objects.create(
                bracket=bracket,
                round_index=total_rounds - 1,
                position=i,
                is_third_place=True,
                source_slot_lose=semis[slot_index],
            )

    for i in range(0, len(round0_slots), 2):
        _create_match_for_pair(bracket, round0_slots[i], round0_slots[i + 1], total_rounds, is_third_place=False)

    return bracket


def _create_match_for_pair(bracket, slot_a, slot_b, total_rounds, *, is_third_place):
    from competition.models import Match

    if slot_a.participation_id is None or slot_b.participation_id is None:
        return
    phase_kind = _phase_kind_for_round(slot_a.round_index, total_rounds, is_third_place)
    phase = _get_or_create_phase(
        bracket.championship, bracket.division, phase_kind, order=slot_a.round_index + 1
    )
    match = Match.objects.create(
        championship=bracket.championship,
        division=bracket.division,
        phase=phase,
        player1=slot_a.participation,
        player2=slot_b.participation,
        pair_key=Match.compute_pair_key(slot_a.participation_id, slot_b.participation_id),
    )
    BracketSlot.objects.filter(pk__in=[slot_a.pk, slot_b.pk]).update(match=match)


def _sibling_slot(slot):
    sibling_position = slot.position + 1 if slot.position % 2 == 0 else slot.position - 1
    return BracketSlot.objects.filter(
        bracket_id=slot.bracket_id,
        round_index=slot.round_index,
        position=sibling_position,
        is_third_place=slot.is_third_place,
    ).first()


def advance_bracket(match) -> None:
    """Propage vainqueur/perdant d'un match de tableau vers les tours suivants
    dès qu'il est validé. Appelé automatiquement après chaque validation de
    résultat (voir ``competition.services.result``/``match``)."""
    if match.result_status != ResultStatus.VALIDATED or match.winner_id is None:
        return

    source_slots = list(match.bracket_slots.all())
    if not source_slots:
        return

    bracket = source_slots[0].bracket
    total_rounds = _rounds_count(bracket.size)
    winner = match.winner
    loser = match.player2 if match.winner_id == match.player1_id else match.player1

    for next_slot in BracketSlot.objects.filter(source_slot_win__in=source_slots):
        next_slot.participation = winner
        next_slot.save(update_fields=["participation"])
        _try_create_match(next_slot, total_rounds)

    for next_slot in BracketSlot.objects.filter(source_slot_lose__in=source_slots):
        next_slot.participation = loser
        next_slot.save(update_fields=["participation"])
        _try_create_match(next_slot, total_rounds)


def _try_create_match(slot, total_rounds):
    if slot.match_id or slot.participation_id is None:
        return
    sibling = _sibling_slot(slot)
    if sibling is None or sibling.participation_id is None or sibling.match_id:
        return
    lower, higher = (slot, sibling) if slot.position < sibling.position else (sibling, slot)
    _create_match_for_pair(slot.bracket, lower, higher, total_rounds, is_third_place=slot.is_third_place)
