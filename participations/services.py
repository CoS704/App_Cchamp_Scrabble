"""Inscriptions à une édition — capacité, doublons (§5, §7, §37)."""
from django.core.exceptions import ValidationError

from core.enums import ParticipationStatus

from .models import ChampionshipParticipation


def register_participation(*, championship, player, division, seed=None):
    if division.championship_id != championship.id:
        raise ValidationError("Cette division n'appartient pas à ce championnat.")

    if championship.participations.filter(player=player).exists():
        raise ValidationError("Ce joueur est déjà inscrit à cette édition.")

    if not division.is_unlimited and division.capacity_max is not None:
        if division.registered_count >= division.capacity_max:
            raise ValidationError(
                f"La division « {division.name} » est complète "
                f"({division.registered_count}/{division.capacity_max})."
            )

    return ChampionshipParticipation.objects.create(
        championship=championship,
        player=player,
        division=division,
        seed=seed,
        status=ParticipationStatus.REGISTERED,
    )


def withdraw_participation(participation):
    participation.status = ParticipationStatus.WITHDRAWN
    participation.save(update_fields=["status", "updated_at"])
    return participation
