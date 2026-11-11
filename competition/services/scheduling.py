"""Génération automatique du calendrier — méthode du cercle (§12).

Pour N joueurs (aller simple) : N·(N-1)/2 matchs, N-1 journées si N est pair,
N journées (un exempt par journée) si N est impair. Le format aller-retour
(``round_robin_legs = 2``) rejoue les mêmes journées avec les orientations
joueur1/joueur2 inversées.
"""
from __future__ import annotations

import random
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.enums import CompetitionFormat, ParticipationStatus, PhaseKind, ResultStatus

from .phases import STANDINGS_KINDS

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


def _active_participations(division):
    return list(
        division.participations.filter(status__in=ACTIVE_PARTICIPATION_STATUSES).order_by("seed", "id")
    )


def _create_round_robin(
    *, championship, division, phase, participations, legs, start_date, interval_days, per_day
) -> list[Match]:
    """Crée journées et matchs d'un tous-contre-tous pour une phase donnée
    (ligue entière, ou un groupe du format coupe du monde)."""
    ids = [p.id for p in participations]
    rounds = generate_round_robin_rounds(ids)

    # Deux passes en masse (journées puis matchs) plutôt qu'un `create()` par
    # journée : pour un grand tableau (ex. 50 joueurs → 49 journées), c'est
    # 2 requêtes au lieu de 50 (§56).
    scheduled_dates: dict[int, object] = {}
    matchdays_to_create = []
    matchday_number = 0
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


def generate_schedule(
    *,
    championship,
    division,
    start_date=None,
    interval_days: int = 7,
    force: bool = False,
) -> list[Match]:
    """Génère (ou régénère) le calendrier d'une division selon le format de
    la compétition (championnat, groupes, suisse).

    Lève ``ValidationError`` si : moins de 2 joueurs, calendrier déjà présent
    sans ``force``, ou des résultats sont déjà validés (on ne détruit jamais
    des matchs validés).
    """
    if division.championship_id != championship.id:
        raise ValidationError("Cette division n'appartient pas à ce championnat.")

    fmt = championship.settings.competition_format
    if fmt == CompetitionFormat.GROUPS_KNOCKOUT:
        return generate_group_stage(
            championship=championship, division=division, start_date=start_date,
            interval_days=interval_days, force=force,
        )
    if fmt == CompetitionFormat.SWISS:
        from .swiss import generate_swiss_round

        return generate_swiss_round(
            championship=championship, division=division, start_date=start_date,
            interval_days=interval_days, force=force,
        )
    if fmt == CompetitionFormat.KNOCKOUT:
        raise ValidationError(
            "Ce format n'a pas de calendrier : générez directement le tableau "
            "d'élimination directe depuis « Phases finales »."
        )

    participations = _active_participations(division)
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

    return _create_round_robin(
        championship=championship, division=division, phase=phase, participations=participations,
        legs=championship.settings.round_robin_legs, start_date=start_date,
        interval_days=interval_days, per_day=championship.settings.max_matches_per_day or 1,
    )


def draw_groups(participations, groups_count: int, rng: random.Random) -> list[list]:
    """Tirage au sort en pots : les joueurs sont classés par tête de série
    (les non classés à la fin, au hasard), découpés en pots de ``groups_count``
    joueurs, et chaque pot est réparti au hasard — un joueur par groupe et par
    pot. Les groupes diffèrent d'au plus un joueur."""
    shuffled = list(participations)
    rng.shuffle(shuffled)
    # tri stable : le mélange préalable départage les ex æquo de tête de série
    shuffled.sort(key=lambda p: p.seed if p.seed is not None else 10**6)

    groups: list[list] = [[] for _ in range(groups_count)]
    for pot_start in range(0, len(shuffled), groups_count):
        pot = shuffled[pot_start : pot_start + groups_count]
        slots = list(range(groups_count))
        rng.shuffle(slots)
        for participation, slot in zip(pot, slots):
            groups[slot].append(participation)
    return groups


def group_sizes(n_players: int, groups_count: int) -> list[int]:
    """Effectifs des groupes pour ``n_players`` répartis en ``groups_count`` groupes."""
    base, extra = divmod(n_players, groups_count)
    return [base + 1 if i < extra else base for i in range(groups_count)]


def format_plan(settings_obj, n_players: int) -> dict:
    """Ce que produira la génération pour ``n_players`` joueurs, selon le
    format : nombre de matchs, de journées/rondes et un résumé lisible."""
    legs = settings_obj.round_robin_legs
    fmt = settings_obj.competition_format
    if fmt == CompetitionFormat.GROUPS_KNOCKOUT:
        sizes = group_sizes(n_players, settings_obj.groups_count)
        matches = sum(expected_match_count(size, legs) for size in sizes)
        days = max((expected_matchday_count(size, legs) for size in sizes), default=0)
        summary = (
            f"{settings_obj.groups_count} groupes de {min(sizes)}"
            + (f" à {max(sizes)}" if min(sizes) != max(sizes) else "")
            + f" joueurs, puis {settings_obj.group_qualifiers} qualifié(s) par groupe"
            + (f" + {settings_obj.group_wildcards} repêché(s)" if settings_obj.group_wildcards else "")
            + " en élimination directe"
        )
        return {"matches": matches, "matchdays": days, "summary": summary}
    if fmt == CompetitionFormat.SWISS:
        from .swiss import swiss_rounds_total

        rounds = swiss_rounds_total(settings_obj, n_players) if n_players >= 2 else 0
        return {
            "matches": rounds * (n_players // 2), "matchdays": rounds,
            "summary": f"{rounds} rondes appariées au fur et à mesure selon le classement",
        }
    if fmt == CompetitionFormat.KNOCKOUT:
        size = 1
        while size < n_players:
            size *= 2
        return {
            "matches": max(n_players - 1, 0), "matchdays": max(size.bit_length() - 1, 0),
            "summary": f"tableau de {size} places ({size - n_players} exempt(s))" if n_players >= 2 else "",
        }
    return {
        "matches": expected_match_count(n_players, legs),
        "matchdays": expected_matchday_count(n_players, legs),
        "summary": "",
    }


def group_letter(index: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letters[index] if index < len(letters) else str(index + 1)


@transaction.atomic
def generate_group_stage(
    *, championship, division, start_date=None, interval_days: int = 7, force: bool = False,
    draw_seed: int | None = None,
) -> list[Match]:
    """Format coupe du monde, étape 1 : tire les groupes de la division et
    génère le tous-contre-tous de chaque groupe."""
    settings_obj = championship.settings
    groups_count = settings_obj.groups_count
    participations = _active_participations(division)
    if len(participations) < groups_count * 2:
        raise ValidationError(
            f"{groups_count} groupes demandent au moins {groups_count * 2} joueurs actifs "
            f"({len(participations)} inscrit(s) dans cette division)."
        )

    existing_phases = Phase.objects.filter(
        championship=championship, division=division, kind=PhaseKind.GROUP
    )
    if existing_phases.exists():
        if not force:
            raise ValidationError(
                "Les groupes existent déjà pour cette division. "
                "Cochez le remplacement pour les tirer à nouveau."
            )
        if Match.objects.filter(
            phase__in=existing_phases, result_status=ResultStatus.VALIDATED
        ).exists():
            raise ValidationError(
                "Impossible de refaire le tirage : des résultats sont déjà validés dans les groupes."
            )
        if division.brackets.exists():
            raise ValidationError("Impossible de refaire le tirage : le tableau final est déjà généré.")
        existing_phases.delete()  # cascade : journées et matchs

    if draw_seed is None:
        draw_seed = random.SystemRandom().randrange(1, 2**31)
    groups = draw_groups(participations, groups_count, random.Random(draw_seed))

    legs = settings_obj.round_robin_legs
    per_day = settings_obj.max_matches_per_day or 1
    matches: list[Match] = []
    for index, members in enumerate(groups):
        phase = Phase.objects.create(
            championship=championship, division=division, kind=PhaseKind.GROUP, order=index + 1,
            name=f"Groupe {group_letter(index)}", config={"draw_seed": draw_seed},
        )
        phase.participants.set(members)
        matches.extend(
            _create_round_robin(
                championship=championship, division=division, phase=phase,
                participations=sorted(members, key=lambda p: (p.seed is None, p.seed or 0, p.id)),
                legs=legs, start_date=start_date, interval_days=interval_days, per_day=per_day,
            )
        )
    return matches


def redate_league_calendar(championship, *, settings_obj=None, today=None) -> int:
    """Recale les dates des calendriers de ligue existants sur le nombre de
    matchs par jour du réglage (N journées par date), sans rien supprimer.

    Sert quand la limite quotidienne est définie/modifiée APRÈS la génération
    du calendrier : on ne peut pas régénérer (des résultats sont déjà
    validés), et les dates ne reflétaient pas le rythme réel des joueurs.

    Une journée n'est **jamais** déplacée une fois TOUS ses matchs décidés
    (terminés ou forfait) : changer le rythme ne doit jamais faire passer un
    match déjà disputé pour « en retard » a posteriori, ni réécrire son
    historique. Une journée seulement partiellement jouée (certains joueurs
    ont déjà leur résultat, d'autres non) reste déplaçable dans son
    ensemble — sinon les retardataires se retrouvent figés à une date passée
    dès qu'un seul adversaire a joué le premier, sans qu'ils y soient pour
    rien. Seules les journées encore entièrement à jouer sont recalées,
    à partir d'aujourd'hui (ou de la suite immédiate des journées déjà
    disputées si elle est plus tardive) — jamais dans le passé, même si un
    rythme plus soutenu comprimerait la fin de saison avant la date du jour.
    Un match reprogrammé à la main (date différente de celle de sa journée)
    n'est pas touché.

    Retourne le nombre de journées dont la date a changé.
    """
    from core.enums import MatchStatus

    per_day = (settings_obj or championship.settings).max_matches_per_day or 1
    today = today or timezone.localdate()
    changed = 0
    phases = Phase.objects.filter(championship=championship, kind__in=STANDINGS_KINDS)
    for phase in phases:
        matchdays = list(Matchday.objects.filter(phase=phase).order_by("number"))
        dated = [md for md in matchdays if md.scheduled_date]
        if not dated:
            continue
        # Une journée n'est « verrouillée » (jamais déplacée) que si TOUS ses
        # matchs sont décidés — pas dès qu'un seul l'est. Un seul match validé
        # sur 7 ne clôt pas la journée : les 6 autres, encore à jouer, doivent
        # rester déplaçables (sinon ils se retrouvent figés à une date passée
        # dès qu'un adversaire quelconque a joué en premier, et paraissent en
        # retard sans raison).
        counts = (
            Matchday.objects.filter(id__in=[md.id for md in dated])
            .annotate(
                total=Count("matches"),
                decided=Count(
                    "matches",
                    filter=Q(matches__status__in=[MatchStatus.COMPLETED, MatchStatus.FORFEIT]),
                ),
            )
        )
        fully_decided_ids = {c.id for c in counts if c.total and c.total == c.decided}
        locked = [md for md in dated if md.id in fully_decided_ids]
        pending = [md for md in dated if md.id not in fully_decided_ids]
        if not pending:
            continue

        # Le pas se déduit UNIQUEMENT d'au moins deux journées verrouillées
        # (jamais modifiées par cette fonction) — jamais de l'ensemble des
        # dates, y compris celles des journées encore à recaler : le pas
        # changeait alors d'un appel à l'autre au fur et à mesure que ces
        # dates bougeaient, ce qui les faisait rebouger indéfiniment (cassant
        # l'idempotence). Sans au moins deux points de repère fiables, 1 jour
        # est la seule valeur qui ne dépende jamais de ce qu'on est en train
        # de déplacer.
        distinct_dates = sorted({md.scheduled_date for md in dated})
        locked_dates = sorted({md.scheduled_date for md in locked})
        step = (locked_dates[1] - locked_dates[0]).days if len(locked_dates) > 1 else 1
        step = step or 1

        last_locked_date = max((md.scheduled_date for md in locked), default=None)
        start = (
            max(today, last_locked_date + timedelta(days=step))
            if last_locked_date
            else max(today, distinct_dates[0])
        )

        for index, md in enumerate(pending):
            new_date = start + timedelta(days=step * (index // per_day))
            if md.scheduled_date == new_date:
                continue
            Match.objects.filter(matchday=md, scheduled_date=md.scheduled_date).update(
                scheduled_date=new_date
            )
            md.scheduled_date = new_date
            md.save(update_fields=["scheduled_date", "updated_at"])
            changed += 1
    return changed
