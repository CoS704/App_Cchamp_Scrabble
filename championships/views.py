from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError, RestrictedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from audit.services import log_action
from core.enums import AuditAction, ChampionshipStatus
from core.permissions import ChampionshipAdminRequiredMixin, GlobalAdminRequiredMixin, is_global_admin

from . import services
from .forms import (
    ChampionshipForm,
    ChampionshipSettingsForm,
    DivisionForm,
    PromotionRelegationRuleForm,
)
from .mixins import ChampionshipScopedMixin, TitledFormMixin
from .models import Championship, ChampionshipSettings


class ChampionshipListView(GlobalAdminRequiredMixin, ListView):
    template_name = "championships/list.html"
    context_object_name = "championships"

    def get_queryset(self):
        return Championship.objects.select_related("series").order_by("-season", "name")


class ChampionshipCreateView(GlobalAdminRequiredMixin, CreateView):
    model = Championship
    form_class = ChampionshipForm
    template_name = "championships/generic_form.html"
    extra_context = {"form_title": "Nouveau championnat"}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        services.initialize_championship(self.object)
        log_action(
            actor=self.request.user,
            action=AuditAction.CHAMPIONSHIP_CREATED,
            target=self.object,
            championship=self.object,
            request=self.request,
        )
        messages.success(
            self.request,
            "Championnat créé en « Brouillon ». Configurez ses divisions et ses règles, "
            "puis passez-le « En cours » (bouton « Changer le statut ») pour qu'il "
            "apparaisse dans les classements publics et « Mon espace ».",
        )
        return response

    def get_success_url(self):
        return reverse("championships:detail", kwargs={"slug": self.object.slug})


class ChampionshipDetailView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, DetailView):
    template_name = "championships/detail.html"
    context_object_name = "championship"

    def get_object(self, queryset=None):
        return self.championship

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["divisions"] = self.championship.divisions.all()
        context["movement_rules"] = self.championship.movement_rules.select_related(
            "source_division", "target_division"
        )
        context["tiebreaks"] = self.championship.tiebreaks.filter(is_active=True)
        context["is_global_admin"] = is_global_admin(self.request.user)
        return context


class ChampionshipSettingsUpdateView(
    ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, UpdateView
):
    form_class = ChampionshipSettingsForm
    template_name = "championships/generic_form.html"

    def get_object(self, queryset=None):
        obj, _ = ChampionshipSettings.objects.get_or_create(championship=self.championship)
        return obj

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        self._old_primary = self.object.primary_tiebreak
        if self.championship.rules_locked:
            form.fields["override_reason"] = forms.CharField(
                label="Motif de la modification exceptionnelle",
                widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            )
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = "Configuration du championnat"
        return context

    def form_valid(self, form):
        reason = form.cleaned_data.pop("override_reason", "")
        new_primary = form.cleaned_data["primary_tiebreak"]
        limit_changed = "max_matches_per_day" in form.changed_data
        response = super().form_valid(form)
        if limit_changed:
            from competition.services.scheduling import redate_league_calendar

            moved = redate_league_calendar(self.championship)
            if moved:
                messages.info(
                    self.request,
                    f"Dates du calendrier recalées sur le nombre de matchs par jour "
                    f"({moved} journée(s) déplacée(s)) ; aucun match supprimé.",
                )
        if new_primary != self._old_primary:
            services.regenerate_tiebreak_chain(self.championship, new_primary)
            messages.info(
                self.request,
                "La chaîne de départage a été réinitialisée sur le nouveau critère principal.",
            )
        log_action(
            actor=self.request.user,
            action=AuditAction.SETTINGS_UPDATED,
            target=self.object,
            championship=self.championship,
            reason=reason,
            request=self.request,
            changes={"primary_tiebreak": new_primary},
        )
        messages.success(self.request, "Configuration mise à jour.")
        return response

    def get_success_url(self):
        return reverse("championships:detail", kwargs={"slug": self.championship.slug})


class ChampionshipStatusView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    """Fait évoluer le statut de l'édition (Brouillon → En cours → Terminé…)."""

    template_name = "championships/status_form.html"

    def _context(self):
        return {
            "championship": self.championship,
            "choices": [
                (value, label)
                for value, label in ChampionshipStatus.choices
                if value != self.championship.status
            ],
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context())

    def post(self, request, *args, **kwargs):
        old_status = self.championship.status
        new_status = request.POST.get("status", "")
        try:
            services.change_status(self.championship, new_status)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("championships:status", slug=self.championship.slug)
        log_action(
            actor=request.user,
            action=AuditAction.CHAMPIONSHIP_STATUS_CHANGED,
            target=self.championship,
            championship=self.championship,
            request=request,
            changes={"from": old_status, "to": new_status},
        )
        messages.success(
            request, f"Statut modifié : {self.championship.get_status_display()}."
        )
        return redirect("championships:detail", slug=self.championship.slug)


class ChampionshipDeleteView(ChampionshipScopedMixin, GlobalAdminRequiredMixin, View):
    """Suppression définitive d'une édition — réservée aux administrateurs
    globaux (comme la création) et seulement tant qu'elle est en brouillon :
    au-delà, elle porte des inscriptions/matchs/résultats réels qu'on ne
    supprime jamais en un clic (cf. DivisionDeleteView, même principe)."""

    def get(self, request, *args, **kwargs):
        can_delete = self.championship.status == ChampionshipStatus.DRAFT
        return render(
            request,
            "championships/delete_confirm.html",
            {"championship": self.championship, "can_delete": can_delete},
        )

    def post(self, request, *args, **kwargs):
        if self.championship.status != ChampionshipStatus.DRAFT:
            messages.error(
                request,
                "Seul un championnat encore en brouillon peut être supprimé. "
                "Une édition déjà lancée doit être conservée pour son historique.",
            )
            return redirect("championships:detail", slug=self.championship.slug)
        if request.POST.get("confirm_name", "").strip() != self.championship.name:
            messages.error(request, "Le nom saisi ne correspond pas : suppression annulée.")
            return redirect("championships:delete", slug=self.championship.slug)

        name = self.championship.name
        season = self.championship.season
        try:
            self.championship.delete()
        except (ProtectedError, RestrictedError):
            # Filet de sécurité : une relation protégée qu'on n'a pas prévue
            # a bloqué la suppression — jamais un 500 brut pour l'admin.
            messages.error(
                request,
                "Suppression impossible : des données liées à ce championnat "
                "en bloquent la suppression.",
            )
            return redirect("championships:detail", slug=self.championship.slug)
        log_action(
            actor=request.user,
            action=AuditAction.CHAMPIONSHIP_DELETED,
            request=request,
            changes={"deleted_championship": name, "season": season},
        )
        messages.success(request, f"Championnat « {name} » ({season}) supprimé.")
        return redirect("championships:list")


class LockRulesView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return render(
            request, "championships/lock_confirm.html", {"championship": self.championship}
        )

    def post(self, request, *args, **kwargs):
        services.lock_rules(self.championship)
        log_action(
            actor=request.user,
            action=AuditAction.RULES_LOCKED,
            championship=self.championship,
            request=request,
        )
        messages.success(request, "Les règles de cette édition sont désormais verrouillées.")
        return redirect("championships:detail", slug=self.championship.slug)


class DivisionCreateView(
    ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, TitledFormMixin, CreateView
):
    form_class = DivisionForm
    template_name = "championships/generic_form.html"
    form_title = "Nouvelle division"

    def form_valid(self, form):
        form.instance.championship = self.championship
        response = super().form_valid(form)
        log_action(
            actor=self.request.user,
            action=AuditAction.DIVISION_CREATED,
            target=self.object,
            championship=self.championship,
            request=self.request,
        )
        messages.success(self.request, f"Division « {self.object.name} » créée.")
        return response

    def get_success_url(self):
        return reverse("championships:detail", kwargs={"slug": self.championship.slug})


class DivisionUpdateView(
    ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, TitledFormMixin, UpdateView
):
    form_class = DivisionForm
    template_name = "championships/generic_form.html"
    form_title = "Modifier la division"

    def get_queryset(self):
        return self.championship.divisions.all()

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            actor=self.request.user,
            action=AuditAction.DIVISION_UPDATED,
            target=self.object,
            championship=self.championship,
            request=self.request,
        )
        messages.success(self.request, "Division mise à jour.")
        return response

    def get_success_url(self):
        return reverse("championships:detail", kwargs={"slug": self.championship.slug})


class DivisionDeleteView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        division = get_object_or_404(self.championship.divisions, pk=kwargs["pk"])
        if division.participations.exists() or division.matches.exists():
            messages.error(
                request,
                "Impossible de supprimer une division déjà utilisée par des "
                "inscriptions ou des matchs.",
            )
        elif self.championship.status != ChampionshipStatus.DRAFT:
            messages.error(
                request, "Les divisions ne peuvent être supprimées qu'en brouillon."
            )
        else:
            name = division.name
            division.delete()
            log_action(
                actor=request.user,
                action=AuditAction.DIVISION_DELETED,
                championship=self.championship,
                request=request,
                changes={"deleted_division": name},
            )
            messages.success(request, f"Division « {name} » supprimée.")
        return redirect("championships:detail", slug=self.championship.slug)


class MovementRuleCreateView(
    ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, TitledFormMixin, CreateView
):
    form_class = PromotionRelegationRuleForm
    template_name = "championships/generic_form.html"
    form_title = "Nouvelle règle de promotion / relégation"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["championship"] = self.championship
        return kwargs

    def form_valid(self, form):
        form.instance.championship = self.championship
        response = super().form_valid(form)
        log_action(
            actor=self.request.user,
            action=AuditAction.MOVEMENT_RULE_CREATED,
            target=self.object,
            championship=self.championship,
            request=self.request,
        )
        messages.success(self.request, "Règle ajoutée.")
        return response

    def get_success_url(self):
        return reverse("championships:detail", kwargs={"slug": self.championship.slug})


class MovementRuleDeleteView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        rule = get_object_or_404(self.championship.movement_rules, pk=kwargs["pk"])
        rule.delete()
        log_action(
            actor=request.user,
            action=AuditAction.MOVEMENT_RULE_DELETED,
            championship=self.championship,
            request=request,
        )
        messages.success(request, "Règle supprimée.")
        return redirect("championships:detail", slug=self.championship.slug)
