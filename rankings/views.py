from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from championships.mixins import ChampionshipScopedMixin
from championships.models import Championship
from core.enums import ChampionshipStatus
from core.permissions import ChampionshipAdminRequiredMixin

from .services import all_divisions_standings


class StandingsView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, TemplateView):
    """Classement admin — recalculé à l'affichage (garantie de fraîcheur ;
    l'optimisation par cache pur vient à l'étape performance, §56)."""

    template_name = "rankings/standings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["divisions_standings"] = all_divisions_standings(self.championship)
        return context


class PublicChampionshipListView(TemplateView):
    """Liste publique des championnats (§32) — accessible sans connexion."""

    template_name = "rankings/public_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["championships"] = (
            Championship.objects.exclude(status=ChampionshipStatus.DRAFT)
            .select_related("series")
            .order_by("-season", "name")
        )
        return context


class PublicStandingsView(TemplateView):
    """Classement public d'un championnat — accessible sans connexion (§32)."""

    template_name = "rankings/public_standings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        championship = get_object_or_404(
            Championship.objects.exclude(status=ChampionshipStatus.DRAFT).select_related("settings"),
            slug=self.kwargs["slug"],
        )
        context["championship"] = championship
        context["divisions_standings"] = all_divisions_standings(championship)
        return context
