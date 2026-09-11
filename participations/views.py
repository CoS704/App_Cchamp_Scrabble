from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from audit.services import log_action
from championships.mixins import ChampionshipScopedMixin
from core.enums import AuditAction
from core.permissions import ChampionshipAdminRequiredMixin

from .forms import ParticipationForm
from .services import register_participation, withdraw_participation


class ParticipationListView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, ListView):
    template_name = "participations/list.html"
    context_object_name = "participations"

    def get_queryset(self):
        return (
            self.championship.participations.select_related("player", "division")
            .order_by("division__level", "seed", "player__last_name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["divisions"] = self.championship.divisions.all()
        return context


class ParticipationCreateView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    template_name = "participations/form.html"

    def get(self, request, *args, **kwargs):
        form = ParticipationForm(championship=self.championship)
        return render(request, self.template_name, {"form": form, "championship": self.championship})

    def post(self, request, *args, **kwargs):
        form = ParticipationForm(request.POST, championship=self.championship)
        if form.is_valid():
            try:
                participation = register_participation(
                    championship=self.championship,
                    player=form.cleaned_data["player"],
                    division=form.cleaned_data["division"],
                    seed=form.cleaned_data["seed"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                log_action(
                    actor=request.user,
                    action=AuditAction.PLAYER_REGISTERED,
                    target=participation,
                    championship=self.championship,
                    request=request,
                )
                messages.success(
                    request, f"{participation.player} inscrit en {participation.division}."
                )
                return redirect("participations:list", slug=self.championship.slug)
        return render(request, self.template_name, {"form": form, "championship": self.championship})


class ParticipationWithdrawView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        participation = get_object_or_404(self.championship.participations, pk=kwargs["pk"])
        withdraw_participation(participation)
        log_action(
            actor=request.user,
            action=AuditAction.PLAYER_WITHDRAWN,
            target=participation,
            championship=self.championship,
            request=request,
        )
        messages.success(request, f"{participation.player} retiré du championnat.")
        return redirect("participations:list", slug=self.championship.slug)
