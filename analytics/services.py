"""Estimations montée/maintien/relégation et simulation « et si » (§28-29).

Méthode statistique simple et explicable (pas d'apprentissage automatique) :
les matchs restants de la division sont **simulés** un grand nombre de fois, la
probabilité qu'un joueur gagne un match étant tirée de sa forme actuelle
(taux de victoires lissé, formule « log5 » face à l'adversaire). La part des
classements finaux simulés qui tombent dans chaque zone de mouvement donne les
pourcentages affichés.

Pourquoi pas de simples bornes « meilleur / pire cas » (version initiale) :
tant qu'il reste beaucoup de matchs, ces bornes couvrent tout le tableau et les
pourcentages ne bougent pas d'un résultat à l'autre. La simulation, elle,
réagit à chaque résultat validé. Elle est **déterministe** (graine dérivée de
l'état du classement) : deux actualisations sans nouveau résultat affichent
exactement les mêmes chiffres. Le meilleur et le pire rang mathématiquement
atteignables restent calculés et exposés.

Ce module ne persiste jamais rien : les résultats réels ne sont pas modifiés.
"""
from __future__ import annotations

import hashlib
import random

from django.db.models import Q

from core.enums import MatchStatus, MovementType, PhaseKind, ResultStatus

_VIRTUAL_SCORES = {"WIN": (400, 300), "DRAW": (350, 350), "LOSS": (300, 400)}


class _VirtualMatch:
    """Objet minimal imitant ``Match`` pour l'agrégation du moteur de
    classement, sans toucher à la base de données."""

    __slots__ = ("player1_id", "player2_id", "score1", "score2")

    def __init__(self, player1_id, player2_id, score1, score2):
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.score1 = score1
        self.score2 = score2


def _league_phase(championship, division):
    from competition.models import Phase

    return Phase.objects.filter(
        championship=championship, division=division, kind=PhaseKind.LEAGUE
    ).first()


def _current_stats(championship, division, phase):
    from competition.models import Match
    from rankings.services import _aggregate

    participations = list(
        division.participations.exclude(status__in=["WITHDRAWN", "DISQUALIFIED"]).select_related("player")
    )
    real_matches = list(
        Match.objects.filter(phase=phase, counts_for_standings=True, result_status=ResultStatus.VALIDATED)
    )
    stats, h2h = _aggregate({p.id for p in participations}, real_matches, championship.settings)
    return participations, stats, h2h


def _remaining_matches_qs(phase, participation):
    from competition.models import Match

    return Match.objects.filter(
        phase=phase, status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED]
    ).filter(Q(player1=participation) | Q(player2=participation))


def _remaining_counts_for_phase(phase, participation_ids) -> dict[int, int]:
    """Nombre de matchs restants par participation, en une seule requête
    (plutôt qu'une requête par joueur — §56)."""
    from competition.models import Match

    counts = {pid: 0 for pid in participation_ids}
    pending = Match.objects.filter(
        phase=phase, status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED]
    ).values_list("player1_id", "player2_id")
    for player1_id, player2_id in pending:
        if player1_id in counts:
            counts[player1_id] += 1
        if player2_id in counts:
            counts[player2_id] += 1
    return counts


def _remaining_fixtures(phase, participation_ids) -> list[tuple[int, int]]:
    """Matchs restants entre joueurs encore en course (byes exclus)."""
    from competition.models import Match

    ids = set(participation_ids)
    pairs = Match.objects.filter(
        phase=phase,
        status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED],
        player2__isnull=False,
    ).values_list("player1_id", "player2_id")
    return [(p1, p2) for p1, p2 in pairs if p1 in ids and p2 in ids]


def _win_probability(rate_a: float, rate_b: float) -> float:
    """Formule « log5 » : chance que A batte B d'après leurs taux de victoires."""
    num = rate_a * (1 - rate_b)
    den = num + rate_b * (1 - rate_a)
    return num / den if den else 0.5


def _simulate_final_rank_distribution(target_id, stats, fixtures, settings_obj) -> dict[int, float]:
    """Distribution ``{rang final: probabilité}`` du joueur ``target_id``.

    Départage des égalités dans la simulation : points, puis différence de score
    actuelle, puis tirage au sort — une approximation assumée (le classement
    officiel applique la chaîne de départage complète de l'édition)."""
    ids = sorted(stats)
    rates = {
        pid: (stats[pid]["wins"] + 0.5 * stats[pid]["draws"] + 1) / (stats[pid]["played"] + 2)
        for pid in ids
    }
    base_points = {pid: stats[pid]["points"] for pid in ids}
    score_diff = {pid: stats[pid]["score_diff"] for pid in ids}
    win_pts, loss_pts = settings_obj.points_win, settings_obj.points_loss

    if not fixtures:
        ahead = sum(
            1
            for other in ids
            if other != target_id
            and (base_points[other], score_diff[other]) > (base_points[target_id], score_diff[target_id])
        )
        return {ahead + 1: 1.0}

    win_prob = [_win_probability(rates[p1], rates[p2]) for p1, p2 in fixtures]
    # Budget constant d'opérations : peu de matchs -> beaucoup de simulations.
    n_sims = max(300, min(3000, 300_000 // len(fixtures)))
    seed_source = repr((target_id, sorted(base_points.items()), sorted(score_diff.items()), fixtures))
    rng = random.Random(int(hashlib.md5(seed_source.encode()).hexdigest()[:12], 16))

    counts: dict[int, int] = {}
    for _ in range(n_sims):
        points = dict(base_points)
        for (p1, p2), p in zip(fixtures, win_prob):
            if rng.random() < p:
                points[p1] += win_pts
                points[p2] += loss_pts
            else:
                points[p2] += win_pts
                points[p1] += loss_pts
        mine = (points[target_id], score_diff[target_id])
        ahead = 0
        for other in ids:
            if other == target_id:
                continue
            theirs = (points[other], score_diff[other])
            if theirs > mine or (theirs == mine and rng.random() < 0.5):
                ahead += 1
        counts[ahead + 1] = counts.get(ahead + 1, 0) + 1
    return {rank: c / n_sims for rank, c in counts.items()}


def movement_probabilities(participation) -> dict | None:
    championship, division = participation.championship, participation.division
    phase = _league_phase(championship, division)
    if not phase:
        return None

    participations, stats, _h2h = _current_stats(championship, division, phase)
    if participation.id not in stats:
        return None

    settings_obj = championship.settings
    remaining_counts = _remaining_counts_for_phase(phase, stats.keys())

    best_points = {
        pid: stats[pid]["points"] + remaining_counts[pid] * settings_obj.points_win for pid in stats
    }
    worst_points = {
        pid: stats[pid]["points"] + remaining_counts[pid] * settings_obj.points_loss for pid in stats
    }

    def rank_of(scenario_points, target_pid):
        ordered = sorted(stats.keys(), key=lambda pid: (-scenario_points[pid], pid))
        return ordered.index(target_pid) + 1

    pid = participation.id
    best_case = {other: (best_points[other] if other == pid else worst_points[other]) for other in stats}
    worst_case = {other: (worst_points[other] if other == pid else best_points[other]) for other in stats}
    best_rank = rank_of(best_case, pid)
    worst_rank = rank_of(worst_case, pid)

    n = len(participations)

    from championships.services import rule_rank_indices

    promotion_ranks: set[int] = set()
    relegation_ranks: set[int] = set()
    for rule in championship.movement_rules.filter(source_division=division, is_active=True):
        ranks = rule_rank_indices(rule, n)
        if rule.movement_type == MovementType.PROMOTION:
            promotion_ranks |= ranks
        else:
            relegation_ranks |= ranks
    finals_ranks = (
        set(range(1, min(settings_obj.finals_qualifiers_count, n) + 1))
        if settings_obj.finals_enabled
        else set()
    )

    fixtures = _remaining_fixtures(phase, stats.keys())
    rank_probs = _simulate_final_rank_distribution(pid, stats, fixtures, settings_obj)

    def zone_pct(zone_ranks: set[int]) -> float:
        return round(sum(rank_probs.get(r, 0.0) for r in zone_ranks) * 100, 1)

    promotion_pct = zone_pct(promotion_ranks)
    relegation_pct = zone_pct(relegation_ranks)
    finals_pct = zone_pct(finals_ranks)
    safe_pct = max(0.0, round(100 - promotion_pct - relegation_pct, 1))
    expected_rank = round(sum(rank * prob for rank, prob in rank_probs.items()), 1)

    return {
        "best_rank": best_rank,
        "worst_rank": worst_rank,
        "total": n,
        "remaining_matches": remaining_counts.get(pid, 0),
        "promotion_pct": promotion_pct,
        "relegation_pct": relegation_pct,
        "finals_pct": finals_pct,
        "safe_pct": safe_pct,
        "expected_rank": expected_rank,
    }


def simulate_outcomes(*, participation, outcomes: dict[int, str]) -> dict:
    """``outcomes`` : ``{match_id: "WIN"|"DRAW"|"LOSS"}`` du point de vue de
    ``participation``, pour ses seuls matchs restants. Ne persiste rien."""
    championship, division = participation.championship, participation.division
    phase = _league_phase(championship, division)
    if not phase:
        return {"error": "Aucune phase de ligue pour cette division."}

    participations, _stats, _h2h = _current_stats(championship, division, phase)

    virtual_matches = []
    for match in _remaining_matches_qs(phase, participation):
        outcome = outcomes.get(match.id)
        if not outcome:
            continue
        is_p1 = match.player1_id == participation.id
        my_score, opp_score = _VIRTUAL_SCORES[outcome]
        score1, score2 = (my_score, opp_score) if is_p1 else (opp_score, my_score)
        virtual_matches.append(_VirtualMatch(match.player1_id, match.player2_id, score1, score2))

    # Recalcule tout d'un bloc (réel + virtuel) pour rester cohérent avec le
    # moteur de classement (agrégation + h2h + départage).
    from competition.models import Match
    from rankings.services import _aggregate, _movement_zones, _rank_participations

    real_matches = list(
        Match.objects.filter(phase=phase, counts_for_standings=True, result_status=ResultStatus.VALIDATED)
    )
    all_matches = real_matches + virtual_matches
    stats, h2h = _aggregate({p.id for p in participations}, all_matches, championship.settings)

    tiebreak_chain = list(championship.tiebreaks.filter(is_active=True).order_by("position"))
    ordered, tie_group_of, unresolved = _rank_participations(
        participations, stats, h2h, tiebreak_chain, {}, championship.settings, championship.id
    )
    movement_map = _movement_zones(
        championship, division, ordered,
        championship.settings.finals_qualifiers_count if championship.settings.finals_enabled else 0,
    )

    rank = ordered.index(participation.id) + 1
    return {
        "rank": rank,
        "total": len(ordered),
        "points": stats[participation.id]["points"],
        "movement_zone": movement_map.get(participation.id, "SAFE"),
        "simulated_count": len(virtual_matches),
    }
