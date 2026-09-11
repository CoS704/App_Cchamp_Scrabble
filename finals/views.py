from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, ListView

from audit.services import log_action
from championships.mixins import ChampionshipScopedMixin
from core.enums import AuditAction
from core.permissions import ChampionshipAdminRequiredMixin

from .models import Bracket
from .services import _rounds_count, generate_bracket


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
        bracket = self.object
        total_rounds = _rounds_count(bracket.size)
        slots = list(
            bracket.slots.select_related(
                "participation__player",
                "match__player1__player",
                "match__player2__player",
            ).order_by("round_index", "position")
        )

        groups = []
        for r in range(total_rounds):
            round_slots = [s for s in slots if s.round_index == r and not s.is_third_place]
            games = [(round_slots[i], round_slots[i + 1]) for i in range(0, len(round_slots), 2)]
            if r == total_rounds - 1:
                label = "Finale"
            elif r == total_rounds - 2:
                label = "Demi-finales"
            else:
                label = f"Tour {r + 1}"
            groups.append({"label": label, "games": games})

        third_place_slots = [s for s in slots if s.is_third_place]
        context["rounds"] = groups
        context["third_place_game"] = (
            (third_place_slots[0], third_place_slots[1]) if len(third_place_slots) == 2 else None
        )
        return context
