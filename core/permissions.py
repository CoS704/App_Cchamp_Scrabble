"""Aides de contrôle d'accès — toujours appelées côté serveur.

Les fonctions restent volontairement conservatrices : en cas de doute, elles
refusent. Les mixins de vue ci-dessous s'appuient dessus ; ils ne remplacent
jamais une vérification équivalente côté modèle/service pour les opérations
sensibles (saisie de résultat, verrouillage des règles…).
"""
from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


def is_super_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name="Super Admin").exists()


def is_global_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return is_super_admin(user) or user.groups.filter(name="Admin Championnat").exists()


def can_manage_players(user) -> bool:
    """Registre des joueurs : administrateurs globaux, ou admin d'au moins une
    édition (import/inscription de nouveaux compétiteurs à la volée)."""
    if is_global_admin(user):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return user.staff_roles.filter(role="ADMIN", is_active=True).exists()


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


# --- Mixins de vues (CBV) ---------------------------------------------------
# UserPassesTestMixin : redirige vers LOGIN_URL si non authentifié, sinon lève
# PermissionDenied (403) si le test échoue — jamais un simple masquage UI.


class SuperAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réserve la vue aux super administrateurs."""

    def test_func(self):
        return is_super_admin(self.request.user)


class GlobalAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réserve la vue aux administrateurs globaux (Super Admin / Admin Championnat).

    À utiliser pour les opérations qui ne sont pas cadrées à une édition
    existante (ex. créer un nouveau championnat).
    """

    def test_func(self):
        return is_global_admin(self.request.user)


class PlayerManagerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réserve la vue à qui peut gérer le registre des joueurs."""

    def test_func(self):
        return can_manage_players(self.request.user)


class ChampionshipAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Réserve la vue aux administrateurs (globaux ou de l'édition courante).

    La vue doit exposer l'attribut ``championship`` (par ex. posé dans
    ``dispatch()`` ou ``setup()``) ou surcharger ``get_championship()``.
    """

    def get_championship(self):
        if hasattr(self, "championship"):
            return self.championship
        raise NotImplementedError(
            "Définissez `self.championship` ou surchargez `get_championship()`."
        )

    def test_func(self):
        return can_manage_championship(self.request.user, self.get_championship())


class RefereeRequiredMixin(ChampionshipAdminRequiredMixin):
    """Réserve la vue aux arbitres (ou admins) de l'édition.

    Si la vue expose ``self.division``, restreint aux arbitres cadrés sur
    cette division (ou non cadrés = toutes divisions).
    """

    def test_func(self):
        division = getattr(self, "division", None)
        return can_referee(self.request.user, self.get_championship(), division)
