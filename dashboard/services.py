"""Agrégation des données pour les dashboards (§22-31).

Les vues restent fines : tout calcul vit ici, en s'appuyant sur les services
déjà existants (classement, matchs en retard…) plutôt qu'en le dupliquant.
"""
from __future__ import annotations

from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.enums import (
    ChampionshipStatus,
    MatchStatus,
    OutcomeType,
    ParticipationStatus,
    PhaseKind,
    ResultStatus,
)


def admin_dashboard_context(championship):
    from competition.models import Match
    from competition.services.match import late_matches_queryset
    from participations.models import ChampionshipParticipation

    matches = Match.objects.filter(championship=championship)
    total = matches.count()
    completed = matches.filter(status=MatchStatus.COMPLETED).count()
    # « Programmés » = pas encore joués : un résultat déjà saisi mais pas encore
    # validé est compté à part (sinon il reste indéfiniment dans « Programmés »).
    scheduled = matches.filter(
        status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING],
        result_status__in=[ResultStatus.NONE, ResultStatus.REJECTED],
    ).count()
    postponed = matches.filter(status=MatchStatus.POSTPONED).count()
    cancelled = matches.filter(status=MatchStatus.CANCELLED).count()
    disputed = matches.filter(status=MatchStatus.DISPUTED).count()
    forfeit = matches.filter(status=MatchStatus.FORFEIT).count()
    pending_results = matches.filter(
        result_status__in=[ResultStatus.SUBMITTED, ResultStatus.CONFIRMED]
    ).count()

    validated = matches.filter(result_status=ResultStatus.VALIDATED)
    normal_validated = validated.filter(outcome_type=OutcomeType.NORMAL)
    draws_count = normal_validated.filter(score1=F("score2")).count()
    wins_count = normal_validated.exclude(score1=F("score2")).count()
    forfeit_count = validated.exclude(outcome_type=OutcomeType.NORMAL).count()

    active_participations = ChampionshipParticipation.objects.filter(championship=championship).exclude(
        status__in=[ParticipationStatus.WITHDRAWN, ParticipationStatus.DISQUALIFIED]
    )
    players_count = active_participations.count()

    # Le compteur porte sur TOUS les matchs en retard ; seule la liste
    # affichée est limitée à 20 lignes (avant, le compteur lui-même plafonnait
    # à 20 et « ne bougeait plus » sur un gros championnat).
    late_qs = late_matches_queryset(championship)
    late_matches_total = late_qs.count()
    late_matches = list(
        late_qs.select_related("division", "matchday", "player1__player", "player2__player")
        .order_by("scheduled_date")[:20]
    )
    today = timezone.localdate()
    for match in late_matches:
        match.days_late = (today - match.scheduled_date).days if match.scheduled_date else None

    # Une seule requête agrégée pour toutes les divisions plutôt que 3
    # requêtes par division (§56) : Count(..., distinct=True) sur chaque
    # relation inversée évite l'effet de produit cartésien entre les deux
    # jointures (matchs / participations).
    divisions = list(
        championship.divisions.annotate(
            matches_total=Count("matches", distinct=True),
            matches_completed=Count(
                "matches", filter=Q(matches__status=MatchStatus.COMPLETED), distinct=True
            ),
            active_players=Count(
                "participations",
                filter=~Q(
                    participations__status__in=[
                        ParticipationStatus.WITHDRAWN, ParticipationStatus.DISQUALIFIED,
                    ]
                ),
                distinct=True,
            ),
        )
    )
    division_progress = [
        {
            "name": d.name,
            "completed": d.matches_completed,
            "total": d.matches_total,
            "pct": round(d.matches_completed / d.matches_total * 100, 1) if d.matches_total else 0,
        }
        for d in divisions
    ]
    division_players = [{"name": d.name, "count": d.active_players} for d in divisions]

    snapshots = _compute_snapshots_once(championship, divisions)
    top_players = _top_players(snapshots)

    activity = list(
        matches.filter(entered_at__isnull=False)
        .annotate(day=TruncDate("entered_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    # Une seule requête agrégée pour toutes les journées plutôt qu'une
    # requête par journée (§56).
    from competition.models import Matchday

    matchday_stats = list(
        Matchday.objects.filter(phase__championship=championship, phase__kind=PhaseKind.LEAGUE).annotate(
            total_matches=Count("matches", distinct=True),
            unfinished_matches=Count(
                "matches",
                filter=~Q(
                    matches__status__in=[MatchStatus.COMPLETED, MatchStatus.FORFEIT, MatchStatus.CANCELLED]
                ),
                distinct=True,
            ),
        )
    )
    matchdays_total = len(matchday_stats)
    matchdays_completed = sum(
        1 for md in matchday_stats if md.total_matches > 0 and md.unfinished_matches == 0
    )

    alerts = _build_alerts(championship, divisions, disputed, pending_results, late_matches_total, snapshots)

    return {
        "players_count": players_count,
        "divisions_count": len(divisions),
        "matches_total": total,
        "matches_completed": completed,
        "matches_scheduled": scheduled,
        "matches_postponed": postponed,
        "matches_cancelled": cancelled,
        "matches_disputed": disputed,
        "matches_forfeit": forfeit,
        "pending_results": pending_results,
        "progress_pct": round(completed / total * 100, 1) if total else 0,
        "matchdays_total": matchdays_total,
        "matchdays_completed": matchdays_completed,
        "late_matches": late_matches,
        "late_matches_count": late_matches_total,
        "alerts": alerts,
        "late_threshold_days": championship.settings.late_match_threshold_days,
        # Les parts somment au nombre total de matchs : rien n'est « perdu »
        # entre les catégories (forfaits et résultats en attente inclus).
        "chart_progress": {
            "labels": ["Terminés", "En attente de validation", "Programmés", "Reportés",
                       "Annulés", "Forfaits"],
            "data": [completed, pending_results, scheduled, postponed, cancelled, forfeit],
        },
        "chart_results": {"labels": ["Victoires", "Nuls", "Forfaits"],
                           "data": [wins_count, draws_count, forfeit_count]},
        "chart_division_players": {"labels": [d["name"] for d in division_players],
                                    "data": [d["count"] for d in division_players]},
        "chart_top_players": {"labels": [p["name"] for p in top_players],
                               "data": [p["points"] for p in top_players]},
        "chart_activity": {"labels": [a["day"].strftime("%d/%m") for a in activity],
                            "data": [a["count"] for a in activity]},
        "division_progress": division_progress,
        "top_players": top_players,
    }


def _compute_snapshots_once(championship, divisions):
    """Un seul recalcul de classement par division — partagé entre le
    palmarès et les alertes plutôt que recalculé deux fois (§56)."""
    from competition.models import Phase
    from rankings.services import compute_standings

    snapshots = {}
    for division in divisions:
        phase = Phase.objects.filter(
            championship=championship, division=division, kind=PhaseKind.LEAGUE
        ).first()
        snapshots[division.id] = compute_standings(
            championship=championship, division=division, phase=phase
        ) if phase else None
    return snapshots


def _top_players(snapshots, limit=10):
    rows = []
    for snapshot in snapshots.values():
        if snapshot:
            rows.extend(snapshot.rows.select_related("participation__player"))
    rows.sort(key=lambda r: (-r.points, -r.score_diff))
    return [
        {"name": str(row.participation.player), "points": row.points, "division": row.snapshot.division.name}
        for row in rows[:limit]
    ]


def _build_alerts(championship, divisions, disputed_count, pending_results, late_matches_count, snapshots):
    alerts = []
    if disputed_count:
        alerts.append({
            "level": "danger",
            "message": f"{disputed_count} match(s) en litige à trancher.",
            "link_query": "status=DISPUTED",
            "link_label": "Trancher les litiges",
        })
    if pending_results:
        alerts.append({
            "level": "warning",
            "message": f"{pending_results} résultat(s) en attente de confirmation ou de validation.",
            "link_query": "result_status=PENDING",
            "link_label": "Voir les résultats en attente",
        })
    if late_matches_count:
        alerts.append({
            "level": "warning",
            "message": f"{late_matches_count} match(s) en retard.",
        })
    for division in divisions:
        count = division.active_players
        if division.capacity_min and count < division.capacity_min:
            alerts.append({
                "level": "info",
                "message": f"« {division.name} » : {count} inscrit(s), minimum {division.capacity_min} attendu.",
            })
        if count < 2:
            alerts.append({
                "level": "info",
                "message": f"« {division.name} » : moins de 2 joueurs, calendrier impossible.",
            })
        snapshot = snapshots.get(division.id)
        if snapshot and snapshot.has_unresolved_tie:
            alerts.append({
                "level": "danger",
                "message": f"« {division.name} » : égalité non résolue au classement.",
            })
    return alerts


def _format_match_for(participation, match):
    is_p1 = match.player1_id == participation.id
    my_score = match.score1 if is_p1 else match.score2
    opp_score = match.score2 if is_p1 else match.score1
    opponent = match.player2 if is_p1 else match.player1
    result = None
    if my_score is not None and opp_score is not None:
        result = "V" if my_score > opp_score else ("D" if my_score < opp_score else "N")
    return {"match": match, "opponent": opponent, "my_score": my_score, "opp_score": opp_score, "result": result}


def _opponent_for(participation, match):
    """La participation adverse dans ``match`` vue depuis ``participation``
    (§ affichage de l'identifiant ScrabbleGO de l'adversaire)."""
    if match is None:
        return None
    return match.player2 if match.player1_id == participation.id else match.player1


def player_dashboard_context(user):
    player = getattr(user, "player", None)
    if player is None:
        return {"player": None}

    participation = (
        player.participations.filter(
            championship__status__in=[ChampionshipStatus.IN_PROGRESS, ChampionshipStatus.FINALS]
        )
        .select_related("championship", "division")
        .order_by("-championship__season")
        .first()
    )
    if not participation:
        participation = (
            player.participations.select_related("championship", "division")
            .order_by("-championship__season")
            .first()
        )
    if not participation:
        return {"player": player, "participation": None}

    championship, division = participation.championship, participation.division

    from competition.models import Match, Phase
    from rankings.services import compute_standings

    phase = Phase.objects.filter(
        championship=championship, division=division, kind=PhaseKind.LEAGUE
    ).first()
    row, total_rows = None, 0
    if phase:
        snapshot = compute_standings(championship=championship, division=division, phase=phase)
        if snapshot:
            row = snapshot.rows.filter(participation=participation).first()
            total_rows = snapshot.rows.count()

    base_qs = Match.objects.filter(
        phase__championship=championship, phase__division=division
    ).filter(Q(player1=participation) | Q(player2=participation))

    next_match = (
        base_qs.filter(status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED])
        .select_related("player1__player", "player2__player", "matchday")
        .order_by("scheduled_date", "id")
        .first()
    )
    # Limite quotidienne : une fois atteinte, le prochain adversaire n'est pas
    # dévoilé (ni le match, ni son identifiant ScrabbleGO) avant le lendemain.
    from competition.services.daily_limit import daily_limit_status

    daily_limit = daily_limit_status(participation)
    next_match_hidden = bool(daily_limit and daily_limit["reached"])
    if next_match_hidden:
        next_match = None
    remaining = base_qs.filter(
        status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED]
    ).count()
    recent_matches = [
        _format_match_for(participation, m)
        for m in base_qs.filter(result_status=ResultStatus.VALIDATED)
        .select_related("player1__player", "player2__player")
        .order_by("-validated_at")[:5]
    ]

    from analytics.services import movement_probabilities

    return {
        "player": player,
        "participation": participation,
        "championship": championship,
        "division": division,
        "row": row,
        "total_rows": total_rows,
        "next_match": next_match,
        "next_match_opponent": _opponent_for(participation, next_match),
        "next_match_hidden": next_match_hidden,
        "daily_limit": daily_limit,
        "remaining": remaining,
        "recent_matches": recent_matches,
        "probabilities": movement_probabilities(participation),
    }
