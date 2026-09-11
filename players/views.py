from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from audit.services import log_action
from core.enums import AuditAction
from core.permissions import PlayerManagerRequiredMixin

from .forms import PlayerForm, PlayerImportForm
from .models import Player
from .services import import_players_from_csv


class PlayerListView(PlayerManagerRequiredMixin, ListView):
    template_name = "players/list.html"
    context_object_name = "players"
    paginate_by = 50

    def get_queryset(self):
        queryset = Player.objects.order_by("last_name", "first_name")
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(display_name__icontains=query)
            )
        return queryset


class PlayerCreateView(PlayerManagerRequiredMixin, CreateView):
    model = Player
    form_class = PlayerForm
    template_name = "players/form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        log_action(
            actor=self.request.user,
            action=AuditAction.PLAYER_CREATED,
            target=self.object,
            request=self.request,
        )
        messages.success(self.request, f"Joueur « {self.object} » créé.")
        return response

    def get_success_url(self):
        return self.request.POST.get("next") or reverse("players:list")


class PlayerUpdateView(PlayerManagerRequiredMixin, UpdateView):
    model = Player
    form_class = PlayerForm
    template_name = "players/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(
            actor=self.request.user,
            action=AuditAction.PLAYER_UPDATED,
            target=self.object,
            request=self.request,
        )
        messages.success(self.request, "Joueur mis à jour.")
        return response

    def get_success_url(self):
        return reverse("players:list")


class PlayerImportView(PlayerManagerRequiredMixin, View):
    template_name = "players/import.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {"form": PlayerImportForm()})

    def post(self, request, *args, **kwargs):
        form = PlayerImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        report = import_players_from_csv(form.cleaned_data["csv_file"], created_by=request.user)
        log_action(
            actor=request.user,
            action=AuditAction.PLAYER_IMPORTED,
            request=request,
            changes={"created": len(report.created), "skipped": len(report.skipped)},
        )
        return render(request, "players/import_result.html", {"report": report})
