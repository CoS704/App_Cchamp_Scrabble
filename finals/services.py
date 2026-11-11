"""Génération et progression du tableau final (§36).

Le tableau n'est jamais codé en dur sur un format 1v4/2v3 : la taille et
l'algorithme de tirage (méthode standard, séparant les têtes de série)
s'appliquent à n'importe quelle puissance de 2. Chaque « case » du tableau
est un match ordinaire (``competition.Match``) : la saisie/validation du
résultat réutilise exactement le même circuit que la phase de ligue.
"""
from __future__ import annotations

import random

from django.core.exceptions import ValidationError
from django.db import transaction

from championships.models import Division
from core.enums import CompetitionFormat, MatchStatus, PhaseKind, ResultStatus

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


def _get_or_create_phase(championship, division, kind, order, name=None):
    from competition.models import Phase

    phase, _ = Phase.objects.get_or_create(
        championship=championship,
        division=division,
        kind=kind,
        order=order,
        defaults={"name": name or dict(PhaseKind.choices).get(kind, kind)},
    )
    return phase


def _next_power_of_two(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


def _seeded_round0(seeded: list, size: int) -> list[tuple]:
    """Place les joueurs (classés du meilleur au moins bon) sur la première
    ligne du tableau selon l'ordre de tirage standard ; les places non
    pourvues (``size`` > effectif) deviennent des exempts pour les premières
    têtes de série."""
    order = _standard_seed_order(size)
    return [
        (seeded[seed_number - 1], seed_number) if seed_number <= len(seeded) else (None, seed_number)
        for seed_number in order
    ]


def _standings_phase_for_finals(championship, division):
    from competition.services.phases import standings_phases

    for phase in standings_phases(championship, division):
        if phase.kind in (PhaseKind.LEAGUE, PhaseKind.SWISS):
            return phase
    return None


def _round0_from_standings(championship, division, settings_obj):
    from rankings.services import compute_standings

    phase = _standings_phase_for_finals(championship, division)
    if not phase:
        raise ValidationError("Aucune phase de ligue trouvée pour cette division.")

    snapshot = compute_standings(championship=championship, division=division, phase=phase)
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
    return _seeded_round0([row.participation for row in rows], n), {"seeding": "standard", "qualifiers": n}


def _round0_from_seeds(championship, division, settings_obj):
    """Élimination directe : tous les joueurs actifs, têtes de série d'abord,
    les non classés tirés au sort (graine conservée pour l'audit)."""
    from competition.services.scheduling import _active_participations

    participations = _active_participations(division)
    if len(participations) < 2:
        raise ValidationError("Il faut au moins 2 joueurs actifs pour un tableau à élimination directe.")

    draw_seed = random.SystemRandom().randrange(1, 2**31)
    rng = random.Random(draw_seed)
    seeded = sorted((p for p in participations if p.seed is not None), key=lambda p: (p.seed, p.id))
    unseeded = [p for p in participations if p.seed is None]
    rng.shuffle(unseeded)
    ordered = seeded + unseeded
    size = _next_power_of_two(len(ordered))
    return _seeded_round0(ordered, size), {
        "seeding": "standard", "qualifiers": len(ordered), "draw_seed": draw_seed,
    }


def _group_qualifiers(championship, division, settings_obj):
    """Qualifiés du format coupe du monde : ``(joueur, rang dans le groupe,
    indice du groupe, moyennes)`` pour les premiers de chaque groupe, plus les
    meilleurs du rang suivant s'il y a des repêchés."""
    from competition.models import Match
    from competition.services.phases import standings_phases
    from rankings.services import compute_standings

    phases = [p for p in standings_phases(championship, division) if p.kind == PhaseKind.GROUP]
    if not phases:
        raise ValidationError("Aucun groupe trouvé : générez d'abord le calendrier des groupes.")
    if Match.objects.filter(phase__in=phases).exclude(
        status__in=[MatchStatus.COMPLETED, MatchStatus.FORFEIT, MatchStatus.CANCELLED]
    ).exists():
        raise ValidationError(
            "La phase de groupes n'est pas terminée : tous les matchs doivent avoir un résultat."
        )

    q, wildcards = settings_obj.group_qualifiers, settings_obj.group_wildcards
    qualified, candidates = [], []
    for index, phase in enumerate(phases):
        snapshot = compute_standings(championship=championship, division=division, phase=phase)
        if snapshot.has_unresolved_tie:
            raise ValidationError(
                f"{phase.name} comporte une égalité non résolue : tranchez-la avant de passer à l'élimination directe."
            )
        rows = list(snapshot.rows.select_related("participation").order_by("rank"))
        if len(rows) < q:
            raise ValidationError(f"{phase.name} compte moins de {q} joueurs : réduisez les qualifiés par groupe.")
        for row in rows[:q]:
            qualified.append((row.participation, row.rank, index, row))
        if wildcards and len(rows) > q:
            candidates.append((rows[q], index))

    if wildcards:
        if wildcards > len(candidates):
            raise ValidationError("Trop de repêchés demandés pour le nombre de groupes.")

        def per_match(row):
            played = row.played or 1
            return (-row.points / played, -row.score_diff / played, -row.score_for / played)

        candidates.sort(key=lambda c: (per_match(c[0]), c[1]))
        for row, index in candidates[:wildcards]:
            qualified.append((row.participation, row.rank, index, row))
    if len(qualified) < 2:
        raise ValidationError("Il faut au moins 2 qualifiés pour un tableau à élimination directe.")
    return qualified, len(phases)


def _round0_from_groups(championship, division, settings_obj):
    qualified, groups_count = _group_qualifiers(championship, division, settings_obj)
    q, wildcards = settings_obj.group_qualifiers, settings_obj.group_wildcards
    fmt = {"seeding": "groups", "qualifiers": len(qualified), "groups": groups_count}

    if q == 2 and wildcards == 0 and groups_count % 2 == 0:
        # Classique « coupe du monde » : 1ᵉʳ du groupe A contre 2ᵉ du groupe B, et
        # inversement, dans deux moitiés opposées du tableau — deux joueurs d'un
        # même groupe ne peuvent donc se retrouver qu'en finale.
        winners = {index: part for part, rank, index, _ in qualified if rank == 1}
        seconds = {index: part for part, rank, index, _ in qualified if rank == 2}
        first_half, second_half = [], []
        for k in range(0, groups_count, 2):
            first_half.append((winners[k], seconds[k + 1]))
            second_half.append((winners[k + 1], seconds[k]))
        round0 = [(p, None) for pair in first_half + second_half for p in pair]
        fmt["pairing"] = "cross_groups"
        return round0, fmt

    ranked = sorted(
        qualified,
        key=lambda item: (
            item[1],
            -item[3].points / (item[3].played or 1),
            -item[3].score_diff / (item[3].played or 1),
            -item[3].score_for / (item[3].played or 1),
            item[2],
        ),
    )
    size = _next_power_of_two(len(ranked))
    group_of = {item[0].id: item[2] for item in ranked}
    round0 = _seeded_round0([item[0] for item in ranked], size)
    round0 = _avoid_same_group_first_round(round0, group_of)
    fmt["pairing"] = "seeded"
    return round0, fmt


def _avoid_same_group_first_round(round0, group_of):
    """Échange au besoin des adversaires de premier tour pour éviter qu'un
    joueur ne retrouve un coéquipier de son groupe (au mieux : on s'arrête si
    aucun échange ne résout le conflit). Les exempts ne sont jamais déplacés."""
    pairs = [list(round0[i : i + 2]) for i in range(0, len(round0), 2)]

    def same_group(a, b):
        return a[0] is not None and b[0] is not None and group_of.get(a[0].id) == group_of.get(b[0].id)

    for i, pair in enumerate(pairs):
        if not same_group(pair[0], pair[1]):
            continue
        swapped = False
        for j, other in enumerate(pairs):
            if j == i or other[0][0] is None or other[1][0] is None:
                continue
            for k in (0, 1):
                if not same_group(pair[0], other[k]) and not same_group(pair[1], other[1 - k]):
                    pair[1], other[k] = other[k], pair[1]
                    swapped = True
                    break
            if swapped:
                break
    return [slot for pair in pairs for slot in pair]


@transaction.atomic
def generate_bracket(*, championship, division: Division) -> Bracket:
    """Génère le tableau à élimination directe d'une division selon le format :
    meilleurs de la ligue / du suisse, qualifiés des groupes, ou tous les
    joueurs (élimination directe)."""
    settings_obj = championship.settings
    fmt = settings_obj.competition_format

    if fmt not in (CompetitionFormat.KNOCKOUT, CompetitionFormat.GROUPS_KNOCKOUT) and not settings_obj.finals_enabled:
        raise ValidationError("La phase finale n'est pas activée pour ce championnat.")

    if Bracket.objects.filter(championship=championship, division=division).exists():
        raise ValidationError("Un tableau final existe déjà pour cette division.")

    if fmt == CompetitionFormat.KNOCKOUT:
        round0, bracket_format = _round0_from_seeds(championship, division, settings_obj)
    elif fmt == CompetitionFormat.GROUPS_KNOCKOUT:
        round0, bracket_format = _round0_from_groups(championship, division, settings_obj)
    else:
        round0, bracket_format = _round0_from_standings(championship, division, settings_obj)

    return build_bracket(
        championship=championship, division=division, round0=round0, bracket_format=bracket_format
    )


def build_bracket(*, championship, division, round0: list[tuple], bracket_format: dict) -> Bracket:
    """Construit le tableau à partir de la première ligne (couples adjacents
    = matchs ; ``None`` = exempt, le joueur en face passe directement)."""
    settings_obj = championship.settings
    size = len(round0)
    total_rounds = _rounds_count(size)
    has_byes = any(participation is None for participation, _seed in round0)

    bracket = Bracket.objects.create(
        championship=championship,
        division=division,
        size=size,
        format=bracket_format,
        phase=_get_or_create_phase(
            championship, division, PhaseKind.FINAL if total_rounds == 1 else PhaseKind.SEMI_FINAL, order=1
        ),
    )

    round0_slots = [
        BracketSlot.objects.create(
            bracket=bracket, round_index=0, position=position, seed=seed_number, participation=participation,
        )
        for position, (participation, seed_number) in enumerate(round0)
    ]

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

    # Une exempt à ce niveau supprimerait une demi-finale : pas de petite finale.
    third_place_possible = total_rounds >= 3 or (total_rounds == 2 and not has_byes)
    if settings_obj.finals_third_place and third_place_possible:
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
        a, b = round0_slots[i], round0_slots[i + 1]
        if a.participation_id and b.participation_id:
            _create_match_for_pair(bracket, a, b, total_rounds, is_third_place=False)
        elif a.participation_id or b.participation_id:
            _advance_bye(bracket, a if a.participation_id else b, total_rounds)

    return bracket


def _advance_bye(bracket, slot, total_rounds):
    """Fait passer directement au tour suivant le joueur sans adversaire."""
    next_slot = BracketSlot.objects.filter(source_slot_win=slot).first()
    if next_slot is None:
        return
    next_slot.participation_id = slot.participation_id
    next_slot.save(update_fields=["participation"])
    _try_create_match(next_slot, total_rounds)


def _create_match_for_pair(bracket, slot_a, slot_b, total_rounds, *, is_third_place):
    from competition.models import Match

    if slot_a.participation_id is None or slot_b.participation_id is None:
        return
    phase_kind = _phase_kind_for_round(slot_a.round_index, total_rounds, is_third_place)
    name = "Petite finale" if is_third_place else _ROUND_LABELS.get(total_rounds - slot_a.round_index)
    phase = _get_or_create_phase(
        bracket.championship, bracket.division, phase_kind, order=slot_a.round_index + 1, name=name
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


_ROUND_LABELS = {1: "Finale", 2: "Demi-finales", 3: "Quarts de finale", 4: "Huitièmes de finale"}


def bracket_rounds_context(bracket) -> dict:
    """Regroupe les emplacements d'un tableau par tour, pour l'affichage —
    partagé entre la vue admin et la vue publique (§56, pas de duplication)."""
    total_rounds = _rounds_count(bracket.size)
    slots = list(
        bracket.slots.select_related(
            "participation__player",
            "match__player1__player",
            "match__player2__player",
        ).order_by("round_index", "position")
    )

    groups = []
    for r in range(total_rounds):
        round_slots = [s for s in slots if s.round_index == r and not s.is_third_place]
        games = [(round_slots[i], round_slots[i + 1]) for i in range(0, len(round_slots), 2)]
        label = _ROUND_LABELS.get(total_rounds - r) or f"Tour {r + 1}"
        groups.append({"label": label, "games": games})

    third_place_slots = [s for s in slots if s.is_third_place]
    return {
        "rounds": groups,
        "third_place_game": (
            (third_place_slots[0], third_place_slots[1]) if len(third_place_slots) == 2 else None
        ),
    }


def _try_create_match(slot, total_rounds):
    if slot.match_id or slot.participation_id is None:
        return
    sibling = _sibling_slot(slot)
    if sibling is None or sibling.participation_id is None or sibling.match_id:
        return
    lower, higher = (slot, sibling) if slot.position < sibling.position else (sibling, slot)
    _create_match_for_pair(slot.bracket, lower, higher, total_rounds, is_third_place=slot.is_third_place)
