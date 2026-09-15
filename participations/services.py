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
    """Retire un joueur d'un championnat.

    Si aucun match n'a été joué sous cette inscription, il n'y a rien à
    préserver : on supprime la ligne plutôt que de la garder pour toujours
    comme une inscription fantôme « Retiré » (ce qui bloquait aussi, sans
    raison, la suppression du joueur lui-même — ``ChampionshipParticipation.
    player`` est protégé tant qu'existe une inscription, même retirée).
    Dès qu'un match existe, l'historique réel est conservé : on se contente
    de marquer le statut, comme avant.
    """
    has_match_history = (
        participation.matches_as_p1.exists() or participation.matches_as_p2.exists()
    )
    if not has_match_history:
        participation.delete()
        return None
    participation.status = ParticipationStatus.WITHDRAWN
    participation.save(update_fields=["status", "updated_at"])
    return participation
