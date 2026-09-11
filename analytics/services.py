"""Estimations montée/maintien/relégation et simulation « et si » (§28-29).

Méthode volontairement simple et explicable — pas de modèle statistique
opaque. Pour chaque joueur encore en course, on calcule le **meilleur** et le
**pire** rang final mathématiquement atteignables compte tenu des matchs
restants (lui gagnant tout pendant que les autres perdent tout, et
inversement), puis on interpole linéairement la proportion de cet intervalle
qui recoupe chaque zone de mouvement. Architecture ouverte à un modèle plus
fin par la suite (il suffit de remplacer ``movement_probabilities``).

Ce module ne persiste jamais rien : les résultats réels ne sont pas modifiés.
"""
from __future__ import annotations

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
    span = worst_rank - best_rank + 1

    def zone_overlap_pct(zone_ranks: set[int]) -> float:
        if not zone_ranks:
            return 0.0
        if best_rank == worst_rank:
            return 100.0 if best_rank in zone_ranks else 0.0
        overlap_lo = max(best_rank, min(zone_ranks))
        overlap_hi = min(worst_rank, max(zone_ranks))
        overlap = max(0, overlap_hi - overlap_lo + 1)
        return round(overlap / span * 100, 1)

    from championships.services import rule_rank_indices

    promotion_pct = 0.0
    relegation_pct = 0.0
    for rule in championship.movement_rules.filter(source_division=division, is_active=True):
        pct = zone_overlap_pct(rule_rank_indices(rule, n))
        if rule.movement_type == MovementType.PROMOTION:
            promotion_pct = max(promotion_pct, pct)
        else:
            relegation_pct = max(relegation_pct, pct)

    finals_pct = 0.0
    if settings_obj.finals_enabled:
        finals_pct = zone_overlap_pct(set(range(1, min(settings_obj.finals_qualifiers_count, n) + 1)))

    safe_pct = max(0.0, round(100 - promotion_pct - relegation_pct, 1))

    return {
        "best_rank": best_rank,
        "worst_rank": worst_rank,
        "total": n,
        "remaining_matches": remaining_counts.get(pid, 0),
        "promotion_pct": promotion_pct,
        "relegation_pct": relegation_pct,
        "finals_pct": finals_pct,
        "safe_pct": safe_pct,
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
