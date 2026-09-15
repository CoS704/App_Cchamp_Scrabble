from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from audit.services import log_action
from core.enums import AuditAction
from core.permissions import PlayerManagerRequiredMixin

from .forms import PlayerForm, PlayerImportForm, PlayerLoginForm
from .models import Player
from .services import (
    create_player_login,
    import_players_from_csv,
    is_deliverable_email,
    reset_player_login_password,
    send_login_credentials_email,
    suggest_email,
    suggest_username,
)


class PlayerListView(PlayerManagerRequiredMixin, ListView):
    template_name = "players/list.html"
    context_object_name = "players"
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            Player.objects.select_related("user")
            .annotate(participations_count=Count("participations", distinct=True))
            .order_by("last_name", "first_name")
        )
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


class PlayerLoginCreateView(PlayerManagerRequiredMixin, View):
    """Création du compte de connexion d'un joueur, avec mot de passe
    temporaire généré — à communiquer au joueur immédiatement, il ne sera
    plus jamais affiché ensuite (§ jamais de secret conservé en clair)."""

    template_name = "players/login_create.html"

    def get_player(self):
        return get_object_or_404(Player, slug=self.kwargs["slug"])

    def get(self, request, *args, **kwargs):
        player = self.get_player()
        if player.user_id:
            messages.info(request, "Ce joueur a déjà un compte.")
            return redirect("players:list")
        username = suggest_username(player)
        form = PlayerLoginForm(initial={"username": username, "email": suggest_email(username)})
        return render(request, self.template_name, {"form": form, "player": player})

    def post(self, request, *args, **kwargs):
        player = self.get_player()
        if player.user_id:
            messages.info(request, "Ce joueur a déjà un compte.")
            return redirect("players:list")
        form = PlayerLoginForm(request.POST)
        if form.is_valid():
            try:
                user, password = create_player_login(
                    player,
                    username=form.cleaned_data["username"],
                    email=form.cleaned_data["email"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            else:
                log_action(
                    actor=request.user,
                    action=AuditAction.PLAYER_LOGIN_CREATED,
                    target=player,
                    request=request,
                )
                email_sent = send_login_credentials_email(
                    player, username=user.username, password=password, created=True, request=request
                )
                return render(
                    request,
                    "players/login_credentials.html",
                    {
                        "player": player,
                        "username": user.username,
                        "password": password,
                        "created": True,
                        "email_sent": email_sent,
                        "email_deliverable": is_deliverable_email(user.email),
                    },
                )
        return render(request, self.template_name, {"form": form, "player": player})


class PlayerLoginResetView(PlayerManagerRequiredMixin, View):
    """Réinitialise le mot de passe d'un joueur déjà pourvu d'un compte."""

    def post(self, request, *args, **kwargs):
        player = get_object_or_404(Player, slug=kwargs["slug"])
        try:
            password = reset_player_login_password(player)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            return redirect("players:list")
        log_action(
            actor=request.user,
            action=AuditAction.PLAYER_LOGIN_RESET,
            target=player,
            request=request,
        )
        email_sent = send_login_credentials_email(
            player, username=player.user.username, password=password, created=False, request=request
        )
        return render(
            request,
            "players/login_credentials.html",
            {
                "player": player,
                "username": player.user.username,
                "password": password,
                "created": False,
                "email_sent": email_sent,
                "email_deliverable": is_deliverable_email(player.user.email),
            },
        )


class PlayerDeleteView(PlayerManagerRequiredMixin, View):
    """Suppression d'un joueur — refusée dès qu'il est ou a été inscrit à un
    championnat, pour ne jamais faire disparaître un historique de matchs
    réel (retirer un joueur d'une édition précise reste possible depuis
    l'écran Inscriptions)."""

    def post(self, request, *args, **kwargs):
        player = get_object_or_404(Player, slug=kwargs["slug"])
        if player.participations.exists():
            messages.error(
                request,
                f"Impossible de supprimer « {player} » : il/elle a déjà été inscrit(e) à "
                "un championnat. Retirez-le/la de chaque édition d'abord, ou désactivez "
                "son profil plutôt que de le supprimer.",
            )
            return redirect("players:list")

        name = str(player)
        user = player.user
        log_action(
            actor=request.user,
            action=AuditAction.PLAYER_DELETED,
            target=player,
            request=request,
            changes={"deleted_player": name},
        )
        player.delete()
        if user:
            user.delete()
        messages.success(request, f"Joueur « {name} » supprimé.")
        return redirect("players:list")


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
