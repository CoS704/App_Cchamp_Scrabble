"""Aides de contrôle d'accès — toujours appelées côté serveur.

Étoffé à l'étape 7 (authentification & permissions). Les fonctions restent
volontairement conservatrices : en cas de doute, elles refusent.
"""
from __future__ import annotations


def is_super_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name="Super Admin").exists()


def is_global_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return is_super_admin(user) or user.groups.filter(name="Admin Championnat").exists()


def can_manage_championship(user, championship) -> bool:
    """Vrai si l'utilisateur peut administrer cette édition."""
    if is_global_admin(user):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return championship.staff.filter(
        user=user, role="ADMIN", is_active=True
    ).exists()


def can_referee(user, championship, division=None) -> bool:
    if can_manage_championship(user, championship):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    qs = championship.staff.filter(user=user, role="REFEREE", is_active=True)
    if not qs.exists():
        return False
    if division is None:
        return True
    for staff in qs.prefetch_related("divisions"):
        scoped = staff.divisions.all()
        if not scoped or division in scoped:
            return True
    return False


def can_enter_result(user, match) -> bool:
    """Autorisation de saisie d'un résultat, selon la politique de l'édition.

    La logique complète (vainqueur déclaré uniquement, etc.) est implémentée
    dans ``competition.services.result`` à l'étape 12 ; ce prédicat couvre le
    contrôle d'accès de base.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    championship = match.championship
    if can_referee(user, championship, match.division):
        return True
    player_user_ids = set()
    for part in (match.player1, match.player2):
        if part and part.player.user_id:
            player_user_ids.add(part.player.user_id)
    return user.id in player_user_ids
