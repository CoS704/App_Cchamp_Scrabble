"""Inscriptions à une édition — capacité, doublons (§5, §7, §37)."""
from django.core.exceptions import ValidationError

from core.enums import ParticipationStatus

from .models import ChampionshipParticipation


def _participation_matches(participation):
    from django.db.models import Q

    from competition.models import Match

    return Match.objects.filter(Q(player1=participation) | Q(player2=participation))


def _unplayed_q():
    """Match jamais joué : aucun résultat saisi/validé, statut d'attente."""
    from django.db.models import Q

    from core.enums import MatchStatus, ResultStatus

    return Q(result_status__in=[ResultStatus.NONE, ResultStatus.REJECTED]) & Q(
        status__in=[
            MatchStatus.SCHEDULED,
            MatchStatus.UPCOMING,
            MatchStatus.POSTPONED,
            MatchStatus.CANCELLED,
        ]
    )


def has_played_history(participation) -> bool:
    """Vrai si un résultat existe sous cette inscription (ou si une saison
    suivante s'appuie dessus) : on n'efface alors jamais la ligne. Un simple
    calendrier généré, sans aucun match joué, n'est pas un historique."""
    if participation.transition_moves.exists():
        return True
    return _participation_matches(participation).exclude(_unplayed_q()).exists()


def _remove_unplayed_matches(participation) -> int:
    deleted, _ = _participation_matches(participation).filter(_unplayed_q()).delete()
    return deleted


def register_participation(*, championship, player, division, seed=None):
    if division.championship_id != championship.id:
        raise ValidationError("Cette division n'appartient pas à ce championnat.")

    existing = championship.participations.filter(player=player).first()
    if existing and existing.status != ParticipationStatus.WITHDRAWN:
        raise ValidationError("Ce joueur est déjà inscrit à cette édition.")

    if existing and existing.division_id != division.id and has_played_history(existing):
        raise ValidationError(
            "Ce joueur a déjà joué des matchs dans sa division précédente : "
            "il ne peut plus changer de division."
        )

    if not division.is_unlimited and division.capacity_max is not None:
        if division.registered_count >= division.capacity_max:
            raise ValidationError(
                f"La division « {division.name} » est complète "
                f"({division.registered_count}/{division.capacity_max})."
            )

    if existing:
        # Réinscription d'un joueur précédemment retiré (typiquement pour le
        # changer de division) : on réactive la ligne existante, la contrainte
        # « un joueur par championnat » interdisant d'en créer une seconde.
        if existing.division_id != division.id:
            _remove_unplayed_matches(existing)
        existing.division = division
        existing.seed = seed
        existing.status = ParticipationStatus.REGISTERED
        existing.save(update_fields=["division", "seed", "status", "updated_at"])
        return existing

    return ChampionshipParticipation.objects.create(
        championship=championship,
        player=player,
        division=division,
        seed=seed,
        status=ParticipationStatus.REGISTERED,
    )


def withdraw_participation(participation):
    """Retire un joueur d'un championnat.

    Sans résultat joué sous cette inscription (un calendrier généré mais
    encore vierge ne compte pas), il n'y a rien à préserver : on supprime
    la ligne et ses matchs prévus, ce qui libère aussi le joueur (retour dans
    le formulaire d'inscription, suppression possible du joueur). Dès qu'un
    résultat existe, l'historique est conservé : on marque seulement le
    statut « Retiré ».
    """
    if not has_played_history(participation):
        _remove_unplayed_matches(participation)
        participation.delete()
        return None
    participation.status = ParticipationStatus.WITHDRAWN
    participation.save(update_fields=["status", "updated_at"])
    return participation
