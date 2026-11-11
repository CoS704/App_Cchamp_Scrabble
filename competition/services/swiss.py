"""Système suisse : une ronde à la fois, appariée selon le classement courant.

Chaque ronde n'est générée qu'une fois la précédente entièrement jouée : on
apparie les joueurs voisins au classement (donc de force proche), sans jamais
rejouer deux fois la même paire, et le joueur en trop (effectif impair) reçoit
un exempt, jamais deux fois tant qu'un autre joueur n'en a pas eu.
"""
from __future__ import annotations

import math
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.enums import MatchStatus, OutcomeType, PhaseKind, ResultStatus

from ..models import Match, Matchday, Phase

_DECIDED = (MatchStatus.COMPLETED, MatchStatus.FORFEIT, MatchStatus.CANCELLED)
_SEARCH_BUDGET = 50_000


def swiss_rounds_total(settings_obj, n_players: int) -> int:
    """Nombre de rondes : celui du réglage, sinon ⌈log₂ n⌉ (au moins 3) ; jamais
    plus que le nombre d'adversaires distincts possibles."""
    automatic = max(3, math.ceil(math.log2(max(n_players, 2))))
    return max(1, min(settings_obj.swiss_rounds or automatic, n_players - 1))


def _pair(order: list[int], played: set[frozenset], byes: set[int], first_round: bool):
    """Appariement sans revanche par recherche avec retour arrière.

    Retourne ``(paires, exempt)`` ou ``None`` si aucun appariement sans
    revanche n'existe. En première ronde, le haut du classement affronte le
    bas (1ᵉʳ contre le (n/2+1)ᵉ…) ; ensuite, chacun affronte le plus proche
    voisin disponible.
    """
    budget = [_SEARCH_BUDGET]

    def solve(players: list[int], half_split: bool):
        if not players:
            return []
        budget[0] -= 1
        if budget[0] < 0:
            return None
        first, rest = players[0], players[1:]
        if half_split and len(players) >= 2:
            target = len(players) // 2 - 1
            preferred = rest[target:] + rest[:target]
        else:
            preferred = rest
        for other in preferred:
            if frozenset((first, other)) in played:
                continue
            remaining = [p for p in rest if p != other]
            tail = solve(remaining, half_split)
            if tail is not None:
                return [(first, other)] + tail
        return None

    if len(order) % 2 == 0:
        pairs = solve(order, first_round)
        return (pairs, None) if pairs is not None else None

    # Effectif impair : l'exempt est le moins bien classé qui n'en a pas encore eu.
    candidates = [p for p in reversed(order) if p not in byes] + [p for p in reversed(order) if p in byes]
    for bye in candidates:
        pairs = solve([p for p in order if p != bye], first_round)
        if pairs is not None:
            return pairs, bye
    return None


def _bye_scores(settings_obj) -> tuple[int, int]:
    """Score technique d'un exempt : celui du forfait, avec au moins un point
    d'avance pour que l'exempt compte bien comme une victoire."""
    against = settings_obj.forfeit_score_against
    return max(settings_obj.forfeit_score_for, against + 1), against


def _swiss_phase(championship, division) -> Phase:
    phase, _ = Phase.objects.get_or_create(
        championship=championship, division=division, kind=PhaseKind.SWISS, order=1,
        defaults={"name": f"Système suisse — {division.name}"},
    )
    return phase


def _active_ids(division) -> list[int]:
    from .scheduling import _active_participations

    return [p.id for p in _active_participations(division)]


def _create_round(*, championship, division, phase, round_number, order, played, byes,
                  matchday_date, first_round) -> list[Match]:
    result = _pair(order, played, byes, first_round)
    if result is None:
        raise ValidationError(
            "Aucun appariement sans revanche n'est possible : toutes les rondes "
            "utiles ont déjà été jouées pour ces joueurs."
        )
    pairs, bye = result

    matchday = Matchday.objects.create(phase=phase, number=round_number, name=f"Ronde {round_number}",
                                       scheduled_date=matchday_date)
    matches = [
        Match(
            championship=championship, division=division, phase=phase, matchday=matchday,
            player1_id=a, player2_id=b, scheduled_date=matchday_date,
            pair_key=Match.compute_pair_key(a, b), source=Match.GENERATED,
        )
        for a, b in pairs
    ]
    if bye is not None:
        score_for, score_against = _bye_scores(championship.settings)
        now = timezone.now()
        matches.append(
            Match(
                championship=championship, division=division, phase=phase, matchday=matchday,
                player1_id=bye, player2=None, scheduled_date=matchday_date,
                pair_key=Match.compute_pair_key(bye, None), source=Match.GENERATED,
                status=MatchStatus.COMPLETED, result_status=ResultStatus.VALIDATED,
                outcome_type=OutcomeType.BYE, score1=score_for, score2=score_against,
                winner_id=bye, counts_for_standings=True, validated_at=now,
            )
        )
    return Match.objects.bulk_create(matches)


def _history(phase) -> tuple[set[frozenset], set[int]]:
    played, byes = set(), set()
    for p1, p2 in Match.objects.filter(phase=phase).values_list("player1_id", "player2_id"):
        if p2 is None:
            byes.add(p1)
        else:
            played.add(frozenset((p1, p2)))
    return played, byes


@transaction.atomic
def generate_swiss_round(*, championship, division, start_date=None, interval_days=7, force=False):
    """Ronde 1 (ou nouvelle ronde 1 avec ``force``) du système suisse."""
    ids = _active_ids(division)
    if len(ids) < 3:
        raise ValidationError("Le système suisse demande au moins 3 joueurs actifs.")

    phase = _swiss_phase(championship, division)
    existing = Match.objects.filter(phase=phase)
    if existing.exists():
        if not force:
            raise ValidationError(
                "Le système suisse est déjà lancé pour cette division. "
                "Cochez le remplacement pour le relancer."
            )
        if existing.filter(result_status=ResultStatus.VALIDATED).exclude(outcome_type=OutcomeType.BYE).exists():
            raise ValidationError(
                "Impossible de relancer : des résultats sont déjà validés dans cette phase."
            )
        existing.delete()
        Matchday.objects.filter(phase=phase).delete()

    phase.config = {"interval_days": interval_days}
    phase.save(update_fields=["config", "updated_at"])
    return _create_round(
        championship=championship, division=division, phase=phase, round_number=1,
        order=ids, played=set(), byes=set(), matchday_date=start_date, first_round=True,
    )


@transaction.atomic
def generate_next_swiss_round(*, championship, division):
    """Ronde suivante, appariée d'après le classement courant."""
    from rankings.services import compute_standings

    phase = Phase.objects.filter(championship=championship, division=division, kind=PhaseKind.SWISS).first()
    last = Matchday.objects.filter(phase=phase).order_by("-number").first() if phase else None
    if not last:
        raise ValidationError("Lancez d'abord la première ronde du système suisse.")

    ids = _active_ids(division)
    total = swiss_rounds_total(championship.settings, len(ids))
    if last.number >= total:
        raise ValidationError(f"Les {total} rondes prévues sont déjà générées.")
    if Match.objects.filter(matchday=last).exclude(status__in=_DECIDED).exists():
        raise ValidationError(
            f"La ronde {last.number} n'est pas terminée : tous ses matchs doivent avoir un résultat."
        )

    snapshot = compute_standings(championship=championship, division=division, phase=phase)
    ranked = [pid for pid in snapshot.rows.order_by("rank").values_list("participation_id", flat=True)
              if pid in set(ids)]
    played, byes = _history(phase)

    interval = (phase.config or {}).get("interval_days", 7)
    next_date = None
    if last.scheduled_date:
        next_date = max(last.scheduled_date + timedelta(days=interval), timezone.localdate())

    return _create_round(
        championship=championship, division=division, phase=phase, round_number=last.number + 1,
        order=ranked, played=played, byes=byes, matchday_date=next_date, first_round=False,
    )


def swiss_status(championship, division) -> dict:
    """État d'avancement du suisse pour l'écran d'administration."""
    phase = Phase.objects.filter(championship=championship, division=division, kind=PhaseKind.SWISS).first()
    n_players = len(_active_ids(division))
    total = swiss_rounds_total(championship.settings, n_players) if n_players >= 2 else 0
    last = Matchday.objects.filter(phase=phase).order_by("-number").first() if phase else None
    current = last.number if last else 0
    round_done = bool(last) and not Match.objects.filter(matchday=last).exclude(status__in=_DECIDED).exists()
    return {
        "started": bool(last), "current_round": current, "total_rounds": total,
        "round_done": round_done, "can_generate_next": bool(last) and round_done and current < total,
        "finished": bool(last) and round_done and current >= total,
    }
