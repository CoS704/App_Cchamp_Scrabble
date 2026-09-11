"""Moteur de classement (§17-21) : calcul depuis les matchs validés, chaîne de
départage configurable, égalités persistantes jamais inventées, zones de
promotion/relégation.

Le classement n'est jamais la source de vérité : il est recalculé à partir
des matchs ``VALIDATED`` à chaque appel. Les ``StandingSnapshot``/``StandingRow``
sont un cache + un historique, jamais l'inverse (voir docs/01-modelisation-bdd.md §5).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core.enums import MovementType, MovementZone, PhaseKind, ResultStatus, TiebreakCriterion

from .models import StandingRow, StandingSnapshot


def _empty_stats() -> dict:
    return {
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "points": 0,
        "score_for": 0,
        "score_against": 0,
        "score_diff": 0,
        "win_rate": Decimal("0"),
        "form": [],
    }


def _result_letter(own: int, other: int) -> str:
    if own > other:
        return "V"
    if own < other:
        return "D"
    return "N"


def _aggregate(participation_ids, matches, settings_obj):
    """Agrège les statistiques par participation + la table des confrontations
    directes (``h2h``), depuis les seuls matchs comptant pour le classement."""
    stats = {pid: _empty_stats() for pid in participation_ids}
    h2h = defaultdict(list)

    for match in matches:
        p1, p2 = match.player1_id, match.player2_id
        if p1 not in stats or (p2 is not None and p2 not in stats):
            continue  # joueur retiré entre-temps : hors périmètre du classement

        s1, s2 = match.score1, match.score2
        stats[p1]["played"] += 1
        stats[p1]["score_for"] += s1
        stats[p1]["score_against"] += s2
        stats[p1]["form"].append(_result_letter(s1, s2))

        if p2 is not None:
            stats[p2]["played"] += 1
            stats[p2]["score_for"] += s2
            stats[p2]["score_against"] += s1
            stats[p2]["form"].append(_result_letter(s2, s1))
            h2h[frozenset((p1, p2))].append(match)

        if s1 > s2:
            stats[p1]["wins"] += 1
            stats[p1]["points"] += settings_obj.points_win
            if p2 is not None:
                stats[p2]["losses"] += 1
                stats[p2]["points"] += settings_obj.points_loss
        elif s2 > s1:
            if p2 is not None:
                stats[p2]["wins"] += 1
                stats[p2]["points"] += settings_obj.points_win
            stats[p1]["losses"] += 1
            stats[p1]["points"] += settings_obj.points_loss
        else:
            stats[p1]["draws"] += 1
            stats[p1]["points"] += settings_obj.points_draw
            if p2 is not None:
                stats[p2]["draws"] += 1
                stats[p2]["points"] += settings_obj.points_draw

    for s in stats.values():
        s["score_diff"] = s["score_for"] - s["score_against"]
        s["win_rate"] = (
            (Decimal(s["wins"]) / s["played"] * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if s["played"]
            else Decimal("0.00")
        )

    return stats, h2h


def _cluster_by(order, key_func):
    """Découpe une liste déjà groupée en sous-listes consécutives partageant
    la même valeur de ``key_func`` (regroupement stable)."""
    if not order:
        return []
    clusters = [[order[0]]]
    for pid in order[1:]:
        if key_func(pid) == key_func(clusters[-1][-1]):
            clusters[-1].append(pid)
        else:
            clusters.append([pid])
    return clusters


def _head_to_head_key(stats, h2h, cluster, settings_obj):
    """Mini-championnat entre les seuls membres du cluster : ne compare que
    les confrontations directes internes au groupe encore à départager."""
    cluster_set = set(cluster)
    mini_points = {pid: 0 for pid in cluster}
    mini_diff = {pid: 0 for pid in cluster}
    for pair, matches in h2h.items():
        a, b = tuple(pair)
        if a not in cluster_set or b not in cluster_set:
            continue
        for match in matches:
            s1, s2, p1, p2 = match.score1, match.score2, match.player1_id, match.player2_id
            mini_diff[p1] += s1 - s2
            mini_diff[p2] += s2 - s1
            if s1 > s2:
                mini_points[p1] += settings_obj.points_win
                mini_points[p2] += settings_obj.points_loss
            elif s2 > s1:
                mini_points[p2] += settings_obj.points_win
                mini_points[p1] += settings_obj.points_loss
            else:
                mini_points[p1] += settings_obj.points_draw
                mini_points[p2] += settings_obj.points_draw
    return lambda pid: (-mini_points[pid], -mini_diff[pid])


def _criterion_key(criterion, stats, h2h, cluster, participations_by_id, settings_obj, championship_id):
    if criterion == TiebreakCriterion.SCORE_DIFF:
        return lambda pid: -stats[pid]["score_diff"]
    if criterion == TiebreakCriterion.WINS:
        return lambda pid: -stats[pid]["wins"]
    if criterion == TiebreakCriterion.SCORE_FOR:
        return lambda pid: -stats[pid]["score_for"]
    if criterion == TiebreakCriterion.SCORE_AGAINST_ASC:
        return lambda pid: stats[pid]["score_against"]
    if criterion == TiebreakCriterion.HEAD_TO_HEAD:
        return _head_to_head_key(stats, h2h, cluster, settings_obj)
    if criterion == TiebreakCriterion.SEED:
        return lambda pid: participations_by_id[pid].seed or 10**6
    if criterion == TiebreakCriterion.FORM:
        return lambda pid: -sum(1 for r in stats[pid]["form"][-5:] if r == "V")
    if criterion == TiebreakCriterion.DRAW_LOTS:
        # Tirage déterministe et stable d'un recalcul à l'autre (pas un vrai
        # tirage au sort physique — à raffiner si besoin d'un tirage tracé).
        return lambda pid: hash((championship_id, pid))
    raise ValueError(f"Critère de départage non géré : {criterion}")


def _rank_participations(participations, stats, h2h, tiebreak_chain, tie_overrides, settings_obj, championship_id):
    participations_by_id = {p.id: p for p in participations}
    ids = list(participations_by_id.keys())

    order = sorted(ids, key=lambda pid: (-stats[pid]["points"], pid))
    clusters = _cluster_by(order, key_func=lambda pid: stats[pid]["points"])

    for tiebreak in tiebreak_chain:
        if tiebreak.criterion == TiebreakCriterion.MANUAL:
            continue  # traité après la boucle : dernier recours
        next_clusters = []
        for cluster in clusters:
            if len(cluster) == 1:
                next_clusters.append(cluster)
                continue
            key_func = _criterion_key(
                tiebreak.criterion, stats, h2h, cluster, participations_by_id, settings_obj, championship_id
            )
            sub_sorted = sorted(cluster, key=key_func)
            next_clusters.extend(_cluster_by(sub_sorted, key_func=key_func))
        clusters = next_clusters

    ordered: list[int] = []
    tie_group_of: dict[int, int] = {}
    unresolved: set[int] = set()
    tie_group_counter = 0

    for cluster in clusters:
        if len(cluster) > 1:
            tie_group_counter += 1
            override = tie_overrides.get(frozenset(cluster))
            if override:
                cluster = [pid for pid in override if pid in cluster]
            else:
                unresolved.update(cluster)
                cluster = sorted(
                    cluster,
                    key=lambda pid: (
                        participations_by_id[pid].seed or 10**6,
                        participations_by_id[pid].player.last_name,
                        participations_by_id[pid].player.first_name,
                    ),
                )
            for pid in cluster:
                tie_group_of[pid] = tie_group_counter
        ordered.extend(cluster)

    return ordered, tie_group_of, unresolved


def _movement_zones(championship, division, ordered, finals_qualifiers_count):
    from championships.services import rule_rank_indices

    n = len(ordered)
    zones = {}
    rules = championship.movement_rules.filter(source_division=division, is_active=True).order_by(
        "priority"
    )
    for rule in rules:
        zone = MovementZone.PROMOTION if rule.movement_type == MovementType.PROMOTION else MovementZone.RELEGATION
        for idx in rule_rank_indices(rule, n):
            if 1 <= idx <= n:
                zones.setdefault(ordered[idx - 1], zone)

    if finals_qualifiers_count:
        for idx in range(1, min(finals_qualifiers_count, n) + 1):
            zones.setdefault(ordered[idx - 1], MovementZone.FINALS)

    return zones


def _load_tie_overrides(championship, division, phase):
    from competition.models import TieResolution

    overrides = {}
    for resolution in TieResolution.objects.filter(
        championship=championship, division=division, phase=phase
    ).prefetch_related("participations"):
        ids = frozenset(p.id for p in resolution.participations.all())
        overrides[ids] = resolution.ordered_result
    return overrides


def all_divisions_standings(championship):
    """Classement de chaque division d'un championnat — recalculé à l'appel.

    Partagé entre le dashboard admin, la page classement admin et la page
    classement publique pour ne pas dupliquer cette logique (§32, §56).
    """
    from competition.models import Phase

    result = []
    for division in championship.divisions.all():
        phase = Phase.objects.filter(
            championship=championship, division=division, kind=PhaseKind.LEAGUE
        ).first()
        snapshot = None
        rows = None
        if phase:
            snapshot = compute_standings(championship=championship, division=division, phase=phase)
            if snapshot:
                rows = snapshot.rows.select_related("participation__player").order_by("rank")
        result.append({"division": division, "snapshot": snapshot, "rows": rows})
    return result


def _previous_ranks(division, phase):
    last = (
        StandingSnapshot.objects.filter(division=division, phase=phase, is_current=False)
        .order_by("-computed_at")
        .first()
    )
    if not last:
        return {}
    return {row.participation_id: row.rank for row in last.rows.all()}


@transaction.atomic
def compute_standings(*, championship, division, phase):
    """(Re)calcule et persiste le classement courant d'une division/phase.

    Retourne le ``StandingSnapshot`` courant (jamais ``None`` si la division
    a au moins un joueur, même sans aucun match joué).
    """
    from competition.models import Match

    participations = list(
        division.participations.exclude(status__in=["WITHDRAWN", "DISQUALIFIED"]).select_related(
            "player"
        )
    )
    if not participations:
        return None

    matches = list(
        Match.objects.filter(
            phase=phase, counts_for_standings=True, result_status=ResultStatus.VALIDATED
        ).only("player1_id", "player2_id", "score1", "score2")
    )

    settings_obj = championship.settings
    stats, h2h = _aggregate({p.id for p in participations}, matches, settings_obj)

    tiebreak_chain = list(championship.tiebreaks.filter(is_active=True).order_by("position"))
    tie_overrides = _load_tie_overrides(championship, division, phase)

    ordered, tie_group_of, unresolved = _rank_participations(
        participations, stats, h2h, tiebreak_chain, tie_overrides, settings_obj, championship.id
    )

    movement_map = _movement_zones(
        championship, division, ordered, settings_obj.finals_qualifiers_count if settings_obj.finals_enabled else 0
    )
    previous_ranks = _previous_ranks(division, phase)

    StandingSnapshot.objects.filter(division=division, phase=phase, is_current=True).update(
        is_current=False
    )
    snapshot = StandingSnapshot.objects.create(
        championship=championship,
        division=division,
        phase=phase,
        is_current=True,
        tiebreak_primary_used=settings_obj.primary_tiebreak,
        has_unresolved_tie=bool(unresolved),
    )

    rows = []
    for rank, pid in enumerate(ordered, start=1):
        s = stats[pid]
        rows.append(
            StandingRow(
                snapshot=snapshot,
                participation_id=pid,
                rank=rank,
                played=s["played"],
                wins=s["wins"],
                draws=s["draws"],
                losses=s["losses"],
                points=s["points"],
                score_for=s["score_for"],
                score_against=s["score_against"],
                score_diff=s["score_diff"],
                win_rate=s["win_rate"],
                form=s["form"][-5:],
                tie_group=tie_group_of.get(pid),
                movement_zone=movement_map.get(pid, MovementZone.SAFE),
                rank_change=(previous_ranks[pid] - rank) if pid in previous_ranks else 0,
            )
        )
    StandingRow.objects.bulk_create(rows)

    return snapshot
