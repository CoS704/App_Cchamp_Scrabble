"""Génération automatique du calendrier — méthode du cercle (§12).

Pour N joueurs (aller simple) : N·(N-1)/2 matchs, N-1 journées si N est pair,
N journées (un exempt par journée) si N est impair. Le format aller-retour
(``round_robin_legs = 2``) rejoue les mêmes journées avec les orientations
joueur1/joueur2 inversées.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError

from core.enums import ParticipationStatus, PhaseKind, ResultStatus

from ..models import Match, Matchday, Phase

ACTIVE_PARTICIPATION_STATUSES = [
    ParticipationStatus.REGISTERED,
    ParticipationStatus.CONFIRMED,
    ParticipationStatus.ACTIVE,
]


def expected_match_count(n_players: int, legs: int = 1) -> int:
    if n_players < 2:
        return 0
    return n_players * (n_players - 1) // 2 * legs


def expected_matchday_count(n_players: int, legs: int = 1) -> int:
    if n_players < 2:
        return 0
    rounds = n_players - 1 if n_players % 2 == 0 else n_players
    return rounds * legs


def generate_round_robin_rounds(participation_ids: list[int]) -> list[list[tuple[int, int]]]:
    """Méthode du cercle : un élément fixe, les autres tournent d'un cran à
    chaque journée. Un id impair de joueurs est complété par un exempt
    (``None``), retiré des paires produites."""
    ids: list[int | None] = list(participation_ids)
    if len(ids) % 2 == 1:
        ids.append(None)

    n = len(ids)
    fixed, rotating = ids[0], ids[1:]
    rounds: list[list[tuple[int, int]]] = []

    for _ in range(n - 1):
        current = [fixed] + rotating
        pairs = []
        for i in range(n // 2):
            a, b = current[i], current[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b))
        rounds.append(pairs)
        rotating = [rotating[-1]] + rotating[:-1]

    return rounds


def generate_schedule(
    *,
    championship,
    division,
    start_date=None,
    interval_days: int = 7,
    force: bool = False,
) -> list[Match]:
    """Génère (ou régénère) le calendrier de phase de ligue d'une division.

    Lève ``ValidationError`` si : moins de 2 joueurs, calendrier déjà présent
    sans ``force``, ou des résultats sont déjà validés (on ne détruit jamais
    des matchs validés).
    """
    if division.championship_id != championship.id:
        raise ValidationError("Cette division n'appartient pas à ce championnat.")

    participations = list(
        division.participations.filter(status__in=ACTIVE_PARTICIPATION_STATUSES)
        .order_by("seed", "id")
    )
    if len(participations) < 2:
        raise ValidationError(
            "Il faut au moins 2 joueurs actifs inscrits pour générer un calendrier."
        )

    phase, _ = Phase.objects.get_or_create(
        championship=championship,
        division=division,
        kind=PhaseKind.LEAGUE,
        order=1,
        defaults={"name": f"Phase de ligue — {division.name}"},
    )

    existing = Match.objects.filter(phase=phase)
    if existing.exists():
        if not force:
            raise ValidationError(
                "Un calendrier existe déjà pour cette division. "
                "Cochez le remplacement pour le régénérer."
            )
        if existing.filter(result_status=ResultStatus.VALIDATED).exists():
            raise ValidationError(
                "Impossible de régénérer : des résultats sont déjà validés dans cette phase."
            )
        existing.delete()
        Matchday.objects.filter(phase=phase).delete()

    legs = championship.settings.round_robin_legs
    ids = [p.id for p in participations]
    rounds = generate_round_robin_rounds(ids)

    # Deux passes en masse (journées puis matchs) plutôt qu'un `create()` par
    # journée : pour un grand tableau (ex. 50 joueurs → 49 journées), c'est
    # 2 requêtes au lieu de 50 (§56).
    scheduled_dates: dict[int, object] = {}
    matchdays_to_create = []
    matchday_number = 0
    per_day = championship.settings.max_matches_per_day or 1
    for leg in range(1, legs + 1):
        for _round_pairs in rounds:
            matchday_number += 1
            # Avec une limite de N matchs/jour, N journées tombent le même jour.
            scheduled_date = (
                start_date + timedelta(days=interval_days * ((matchday_number - 1) // per_day))
                if start_date
                else None
            )
            scheduled_dates[matchday_number] = scheduled_date
            matchdays_to_create.append(
                Matchday(phase=phase, number=matchday_number, scheduled_date=scheduled_date)
            )
    created_matchdays = Matchday.objects.bulk_create(matchdays_to_create)
    matchday_by_number = {md.number: md for md in created_matchdays}

    matches_to_create: list[Match] = []
    matchday_number = 0
    for leg in range(1, legs + 1):
        for round_pairs in rounds:
            matchday_number += 1
            matchday = matchday_by_number[matchday_number]
            scheduled_date = scheduled_dates[matchday_number]
            for a_id, b_id in round_pairs:
                p1_id, p2_id = (a_id, b_id) if leg == 1 else (b_id, a_id)
                matches_to_create.append(
                    Match(
                        championship=championship,
                        division=division,
                        phase=phase,
                        matchday=matchday,
                        player1_id=p1_id,
                        player2_id=p2_id,
                        leg=leg,
                        scheduled_date=scheduled_date,
                        pair_key=Match.compute_pair_key(p1_id, p2_id),
                        source=Match.GENERATED,
                    )
                )

    return Match.objects.bulk_create(matches_to_create)


def redate_league_calendar(championship) -> int:
    """Recale les dates des calendriers de ligue existants sur le nombre de
    matchs par jour du réglage (N journées par date), sans rien supprimer.

    Sert quand la limite quotidienne est définie/modifiée APRÈS la génération
    du calendrier : on ne peut pas régénérer (des résultats sont déjà
    validés), et les dates ne reflétaient pas le rythme réel des joueurs.
    Point de départ = date de la première journée ; pas = écart entre les deux
    premières dates distinctes (1 jour à défaut). Un match reprogrammé à la
    main (date différente de celle de sa journée) n'est pas touché.

    Retourne le nombre de journées dont la date a changé.
    """
    per_day = championship.settings.max_matches_per_day or 1
    changed = 0
    phases = Phase.objects.filter(championship=championship, kind=PhaseKind.LEAGUE)
    for phase in phases:
        matchdays = list(Matchday.objects.filter(phase=phase).order_by("number"))
        dated = [md.scheduled_date for md in matchdays if md.scheduled_date]
        if not dated:
            continue
        distinct = sorted(set(dated))
        start = distinct[0]
        step = (distinct[1] - distinct[0]).days if len(distinct) > 1 else 1
        for md in matchdays:
            new_date = start + timedelta(days=step * ((md.number - 1) // per_day))
            if md.scheduled_date == new_date:
                continue
            Match.objects.filter(matchday=md, scheduled_date=md.scheduled_date).update(
                scheduled_date=new_date
            )
            md.scheduled_date = new_date
            md.save(update_fields=["scheduled_date", "updated_at"])
            changed += 1
    return changed
