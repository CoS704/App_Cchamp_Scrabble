from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.services import log_action
from championships.mixins import ChampionshipScopedMixin
from core.enums import AuditAction, MoveType, TransitionStatus
from core.permissions import ChampionshipAdminRequiredMixin

from .forms import ConfirmTransitionForm, MoveEditForm
from .models import SeasonTransition, SeasonTransitionMove
from .services import confirm_transition, propose_transition


class TransitionDetailView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    template_name = "transitions/detail.html"

    def get(self, request, *args, **kwargs):
        transition = (
            SeasonTransition.objects.filter(from_championship=self.championship)
            .exclude(status=TransitionStatus.CANCELLED)
            .order_by("-created_at")
            .first()
        )
        moves = None
        if transition:
            moves = transition.moves.select_related("player").order_by(
                "from_carryover_key", "player__last_name"
            )
        return render(request, self.template_name, {
            "championship": self.championship,
            "transition": transition,
            "moves": moves,
            "confirm_form": (
                ConfirmTransitionForm()
                if transition and transition.status != TransitionStatus.CONFIRMED
                else None
            ),
        })


class ProposeTransitionView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            transition = propose_transition(championship=self.championship, created_by=request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            log_action(
                actor=request.user, action=AuditAction.TRANSITION_PROPOSED, target=transition,
                championship=self.championship, request=request,
                changes={"moves": transition.moves.count()},
            )
            messages.success(
                request, f"Proposition générée : {transition.moves.count()} mouvement(s) à vérifier."
            )
        return redirect("transitions:detail", slug=self.championship.slug)


class MoveEditView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        move = get_object_or_404(
            SeasonTransitionMove, pk=kwargs["move_id"], transition__from_championship=self.championship
        )
        form = MoveEditForm(request.POST, championship=self.championship)
        if form.is_valid():
            move.to_carryover_key = form.cleaned_data["to_carryover_key"]
            move.is_manual_override = True
            move.move_type = MoveType.MANUAL_OVERRIDE
            move.save(update_fields=["to_carryover_key", "is_manual_override", "move_type", "updated_at"])
            SeasonTransition.objects.filter(pk=move.transition_id).update(status=TransitionStatus.ADJUSTED)
            log_action(
                actor=request.user, action=AuditAction.TRANSITION_MOVE_ADJUSTED, target=move,
                championship=self.championship, request=request,
                changes={"player": str(move.player), "to_carryover_key": move.to_carryover_key},
            )
            messages.success(request, f"Mouvement de {move.player} ajusté.")
        return redirect("transitions:detail", slug=self.championship.slug)


class ConfirmTransitionView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        transition = get_object_or_404(
            SeasonTransition,
            from_championship=self.championship,
            status__in=[TransitionStatus.PROPOSED, TransitionStatus.ADJUSTED],
        )
        form = ConfirmTransitionForm(request.POST)
        if form.is_valid():
            try:
                new_championship = confirm_transition(
                    transition=transition,
                    confirmed_by=request.user,
                    new_name=form.cleaned_data["name"],
                    new_season=form.cleaned_data["season"],
                )
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
            else:
                log_action(
                    actor=request.user, action=AuditAction.TRANSITION_CONFIRMED, target=transition,
                    championship=self.championship, request=request,
                    changes={"new_championship": new_championship.slug},
                )
                messages.success(request, f"Nouvelle édition créée : {new_championship.name}.")
                return redirect("championships:detail", slug=new_championship.slug)
        else:
            messages.error(request, "Merci de renseigner un nom et une saison valides.")
        return redirect("transitions:detail", slug=self.championship.slug)


class CancelTransitionView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        transition = get_object_or_404(
            SeasonTransition,
            from_championship=self.championship,
            status__in=[TransitionStatus.PROPOSED, TransitionStatus.ADJUSTED],
        )
        transition.status = TransitionStatus.CANCELLED
        transition.save(update_fields=["status", "updated_at"])
        messages.success(request, "Proposition annulée.")
        return redirect("transitions:detail", slug=self.championship.slug)
