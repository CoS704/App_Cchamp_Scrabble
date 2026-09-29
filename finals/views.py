from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from audit.services import log_action
from championships.mixins import ChampionshipScopedMixin
from championships.models import Championship
from core.enums import AuditAction, ChampionshipStatus
from core.permissions import ChampionshipAdminRequiredMixin

from .models import Bracket
from .services import bracket_rounds_context, generate_bracket


class BracketListView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, ListView):
    template_name = "finals/list.html"
    context_object_name = "brackets"

    def get_queryset(self):
        return Bracket.objects.filter(championship=self.championship).select_related("division")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        existing_ids = {b.division_id for b in context["brackets"]}
        context["divisions_without_bracket"] = self.championship.divisions.exclude(id__in=existing_ids)
        context["finals_enabled"] = self.championship.settings.finals_enabled
        return context


class BracketGenerateView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        division = get_object_or_404(self.championship.divisions, pk=kwargs["division_id"])
        try:
            bracket = generate_bracket(championship=self.championship, division=division)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            log_action(
                actor=request.user, action=AuditAction.BRACKET_GENERATED, target=bracket,
                championship=self.championship, request=request,
                changes={"division": division.name, "size": bracket.size},
            )
            messages.success(request, f"Tableau final généré pour {division.name}.")
        return redirect("finals:list", slug=self.championship.slug)


class BracketDetailView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, DetailView):
    model = Bracket
    template_name = "finals/detail.html"
    context_object_name = "bracket"

    def get_queryset(self):
        return Bracket.objects.filter(championship=self.championship)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(bracket_rounds_context(self.object))
        return context


class PublicBracketListView(TemplateView):
    """Liste publique des tableaux finaux d'un championnat — accessible sans
    connexion (§32), même pattern que ``rankings.PublicStandingsView``."""

    template_name = "finals/public_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        championship = get_object_or_404(
            Championship.objects.exclude(status=ChampionshipStatus.DRAFT),
            slug=self.kwargs["slug"],
        )
        context["championship"] = championship
        context["brackets"] = Bracket.objects.filter(championship=championship).select_related("division")
        return context


class PublicBracketDetailView(DetailView):
    """Tableau final public d'une division — lecture seule, sans action
    d'administration (pas de bouton « Résultat »)."""

    model = Bracket
    template_name = "finals/public_detail.html"
    context_object_name = "bracket"

    def get_queryset(self):
        return Bracket.objects.filter(
            championship__slug=self.kwargs["slug"]
        ).exclude(championship__status=ChampionshipStatus.DRAFT).select_related("championship", "division")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["championship"] = self.object.championship
        context.update(bracket_rounds_context(self.object))
        return context
