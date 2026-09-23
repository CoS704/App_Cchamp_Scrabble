from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from championships.mixins import ChampionshipScopedMixin
from core.enums import ChampionshipStatus, MatchStatus, PhaseKind
from core.permissions import ChampionshipAdminRequiredMixin, is_global_admin

from .services import admin_dashboard_context, player_dashboard_context


@method_decorator(never_cache, name="dispatch")
class AdminDashboardView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, TemplateView):
    template_name = "dashboard/admin.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(admin_dashboard_context(self.championship))
        return context


@method_decorator(never_cache, name="dispatch")
class PlayerDashboardView(LoginRequiredMixin, TemplateView):
    """« Mon espace » : vue joueur, ou repli utile pour un compte
    admin/arbitre sans profil joueur associé (§26 adapté à un compte staff)."""

    template_name = "dashboard/player.html"

    def get_context_data(self, **kwargs):
        from championships.models import Championship

        context = super().get_context_data(**kwargs)
        context.update(player_dashboard_context(self.request.user))

        if not context.get("player"):
            user = self.request.user
            if is_global_admin(user):
                context["managed_championships"] = Championship.objects.order_by("-season", "name")[:10]
            else:
                staff_championship_ids = user.staff_roles.filter(is_active=True).values_list(
                    "championship_id", flat=True
                )
                context["managed_championships"] = Championship.objects.filter(
                    id__in=staff_championship_ids
                ).order_by("-season", "name")
        return context


class SimulationView(LoginRequiredMixin, TemplateView):
    """Simulation « et si… » (§29) : ne modifie jamais de résultat réel."""

    template_name = "dashboard/simulation.html"

    def get_participation(self):
        player = getattr(self.request.user, "player", None)
        if not player:
            return None
        return (
            player.participations.filter(
                championship__status__in=[ChampionshipStatus.IN_PROGRESS, ChampionshipStatus.FINALS]
            )
            .select_related("championship", "division")
            .order_by("-championship__season")
            .first()
        )

    def get_context_data(self, **kwargs):
        from analytics.services import movement_probabilities
        from competition.models import Match, Phase

        context = super().get_context_data(**kwargs)
        participation = self.get_participation()
        context["participation"] = participation
        if not participation:
            return context

        phase = Phase.objects.filter(
            championship=participation.championship,
            division=participation.division,
            kind=PhaseKind.LEAGUE,
        ).first()
        context["phase"] = phase
        context["probabilities"] = movement_probabilities(participation)

        from competition.services.daily_limit import daily_limit_status

        daily = daily_limit_status(participation)
        context["daily_limit"] = daily
        if daily and daily["reached"]:
            # La liste des matchs restants nomme les futurs adversaires : elle
            # est masquée tant que la limite quotidienne est atteinte.
            context["remaining_matches"] = []
            return context
        if phase:
            context["remaining_matches"] = list(
                Match.objects.filter(
                    phase=phase,
                    status__in=[MatchStatus.SCHEDULED, MatchStatus.UPCOMING, MatchStatus.POSTPONED],
                )
                .filter(Q(player1=participation) | Q(player2=participation))
                .select_related("player1__player", "player2__player")
            )
        return context

    def post(self, request, *args, **kwargs):
        from analytics.services import simulate_outcomes

        context = self.get_context_data(**kwargs)
        participation = context.get("participation")
        if participation and context.get("phase"):
            outcomes = {}
            for match in context.get("remaining_matches", []):
                value = request.POST.get(f"outcome_{match.id}")
                if value in {"WIN", "DRAW", "LOSS"}:
                    outcomes[match.id] = value
            context["simulation_result"] = simulate_outcomes(
                participation=participation, outcomes=outcomes
            )
        return self.render_to_response(context)
