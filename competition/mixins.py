from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404

from championships.models import Championship
from core.permissions import can_enter_result


class MatchScopedMixin:
    """Comme ``championships.mixins.ChampionshipScopedMixin``, mais résout
    aussi le match et sa division avant le contrôle de permission — pour
    qu'un arbitre cadré sur une division précise soit correctement filtré."""

    def dispatch(self, request, *args, **kwargs):
        self.championship = get_object_or_404(
            Championship.objects.select_related("series", "settings"),
            slug=kwargs["slug"],
        )
        self.match = get_object_or_404(
            self.championship.matches.select_related(
                "division", "matchday", "phase", "player1__player", "player2__player"
            ),
            pk=kwargs["pk"],
        )
        self.division = self.match.division
        return super().dispatch(request, *args, **kwargs)

    def get_championship(self):
        return self.championship

    def get_match(self):
        return self.match

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["championship"] = self.championship
        return context


class MatchParticipantOrStaffMixin(MatchScopedMixin, LoginRequiredMixin, UserPassesTestMixin):
    """Joueur du match, arbitre (cadré division) ou administrateur — jamais
    un tiers, même connecté."""

    def test_func(self):
        return can_enter_result(self.request.user, self.match)
