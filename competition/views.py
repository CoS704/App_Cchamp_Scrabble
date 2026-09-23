from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from audit.services import log_action
from championships.mixins import ChampionshipScopedMixin
from core.enums import AuditAction, MatchStatus, ResultStatus

RESULT_STATUS_FILTER_CHOICES = [
    ("PENDING", "En attente (soumis/confirmé)"),
    (ResultStatus.DISPUTED, "Litige"),
    (ResultStatus.VALIDATED, "Validé"),
    (ResultStatus.REJECTED, "Rejeté"),
]
from core.permissions import ChampionshipAdminRequiredMixin, RefereeRequiredMixin, can_referee

from .forms import (
    MatchCancelForm,
    MatchForfeitForm,
    MatchRescheduleForm,
    ResultSubmissionForm,
    ScheduleGenerateForm,
)
from .mixins import MatchParticipantOrStaffMixin, MatchScopedMixin
from .models import Match
from .services.daily_limit import next_opponent_hidden
from .services.match import cancel_match, declare_forfeit, postpone_match, reschedule_match
from .services.result import participation_for_user, reject_result, submit_result
from .services.scheduling import (
    ACTIVE_PARTICIPATION_STATUSES,
    expected_match_count,
    expected_matchday_count,
    generate_schedule,
)


class CalendarView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, ListView):
    template_name = "competition/calendar.html"
    context_object_name = "matches"
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            Match.objects.filter(championship=self.championship)
            .select_related(
                "division", "matchday", "phase", "player1__player", "player2__player"
            )
            .order_by("division__level", "matchday__number", "id")
        )
        division_id = self.request.GET.get("division")
        matchday_id = self.request.GET.get("matchday")
        status = self.request.GET.get("status")
        result_status = self.request.GET.get("result_status")
        if division_id:
            queryset = queryset.filter(division_id=division_id)
        if matchday_id:
            queryset = queryset.filter(matchday_id=matchday_id)
        if status:
            queryset = queryset.filter(status=status)
        if result_status == "PENDING":
            queryset = queryset.filter(
                result_status__in=[ResultStatus.SUBMITTED, ResultStatus.CONFIRMED]
            )
        elif result_status:
            queryset = queryset.filter(result_status=result_status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        legs = self.championship.settings.round_robin_legs
        # Une seule requête agrégée pour toutes les divisions plutôt que 4
        # requêtes par division (§56).
        divisions = list(
            self.championship.divisions.annotate(
                total_count=Count("matches", distinct=True),
                played_count=Count(
                    "matches", filter=Q(matches__status=MatchStatus.COMPLETED), distinct=True
                ),
                n_players=Count(
                    "participations",
                    filter=Q(participations__status__in=ACTIVE_PARTICIPATION_STATUSES),
                    distinct=True,
                ),
            )
        )
        for division in divisions:
            division.has_schedule = division.total_count > 0
            division.expected_matches = expected_match_count(division.n_players, legs)
            division.expected_matchdays = expected_matchday_count(division.n_players, legs)
        context["divisions"] = divisions
        context["status_choices"] = MatchStatus.choices
        context["result_status_choices"] = RESULT_STATUS_FILTER_CHOICES
        context["selected_division"] = self.request.GET.get("division", "")
        context["selected_matchday"] = self.request.GET.get("matchday", "")
        context["selected_status"] = self.request.GET.get("status", "")
        context["selected_result_status"] = self.request.GET.get("result_status", "")
        return context


class ScheduleGenerateView(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin, View):
    template_name = "competition/schedule_generate.html"

    def get_division(self):
        return get_object_or_404(self.championship.divisions, pk=self.kwargs["division_id"])

    def get(self, request, *args, **kwargs):
        division = self.get_division()
        n_players = division.participations.filter(
            status__in=ACTIVE_PARTICIPATION_STATUSES
        ).count()
        legs = self.championship.settings.round_robin_legs
        context = {
            "championship": self.championship,
            "division": division,
            "n_players": n_players,
            "expected_matches": expected_match_count(n_players, legs),
            "expected_matchdays": expected_matchday_count(n_players, legs),
            "has_existing": Match.objects.filter(division=division).exists(),
            "form": ScheduleGenerateForm(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        division = self.get_division()
        form = ScheduleGenerateForm(request.POST)
        if form.is_valid():
            try:
                matches = generate_schedule(
                    championship=self.championship,
                    division=division,
                    start_date=form.cleaned_data["start_date"],
                    interval_days=form.cleaned_data["interval_days"],
                    force=form.cleaned_data["force"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                log_action(
                    actor=request.user,
                    action=AuditAction.SCHEDULE_GENERATED,
                    championship=self.championship,
                    request=request,
                    changes={"division": division.name, "matches_created": len(matches)},
                )
                messages.success(
                    request, f"Calendrier généré pour {division.name} : {len(matches)} match(s)."
                )
                return redirect("competition:list", slug=self.championship.slug)
        n_players = division.participations.filter(
            status__in=ACTIVE_PARTICIPATION_STATUSES
        ).count()
        legs = self.championship.settings.round_robin_legs
        context = {
            "championship": self.championship,
            "division": division,
            "n_players": n_players,
            "expected_matches": expected_match_count(n_players, legs),
            "expected_matchdays": expected_matchday_count(n_players, legs),
            "has_existing": Match.objects.filter(division=division).exists(),
            "form": form,
        }
        return render(request, self.template_name, context)


class MatchActionMixin(ChampionshipScopedMixin, ChampionshipAdminRequiredMixin):
    def get_match(self):
        return get_object_or_404(self.championship.matches, pk=self.kwargs["pk"])


class MatchRescheduleView(MatchActionMixin, View):
    template_name = "competition/match_action_form.html"

    def get(self, request, *args, **kwargs):
        match = self.get_match()
        form = MatchRescheduleForm(
            initial={"scheduled_date": match.scheduled_date, "scheduled_time": match.scheduled_time}
        )
        return render(request, self.template_name, {
            "form": form, "championship": self.championship, "match": match,
            "form_title": "Reprogrammer le match",
        })

    def post(self, request, *args, **kwargs):
        match = self.get_match()
        form = MatchRescheduleForm(request.POST)
        if form.is_valid():
            try:
                reschedule_match(
                    match,
                    new_date=form.cleaned_data["scheduled_date"],
                    new_time=form.cleaned_data["scheduled_time"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                log_action(
                    actor=request.user, action=AuditAction.MATCH_RESCHEDULED, target=match,
                    championship=self.championship, request=request,
                )
                messages.success(request, "Match reprogrammé.")
                return redirect("competition:list", slug=self.championship.slug)
        return render(request, self.template_name, {
            "form": form, "championship": self.championship, "match": match,
            "form_title": "Reprogrammer le match",
        })


class MatchPostponeView(MatchActionMixin, View):
    def post(self, request, *args, **kwargs):
        match = self.get_match()
        try:
            postpone_match(match)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            log_action(
                actor=request.user, action=AuditAction.MATCH_POSTPONED, target=match,
                championship=self.championship, request=request,
            )
            messages.success(request, "Match reporté.")
        return redirect("competition:list", slug=self.championship.slug)


class MatchCancelView(MatchActionMixin, View):
    template_name = "competition/match_action_form.html"

    def get(self, request, *args, **kwargs):
        match = self.get_match()
        return render(request, self.template_name, {
            "form": MatchCancelForm(), "championship": self.championship, "match": match,
            "form_title": "Annuler le match",
        })

    def post(self, request, *args, **kwargs):
        match = self.get_match()
        form = MatchCancelForm(request.POST)
        if form.is_valid():
            try:
                cancel_match(match, reason=form.cleaned_data["reason"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                log_action(
                    actor=request.user, action=AuditAction.MATCH_CANCELLED, target=match,
                    championship=self.championship, request=request,
                    reason=form.cleaned_data["reason"],
                )
                messages.success(request, "Match annulé.")
                return redirect("competition:list", slug=self.championship.slug)
        return render(request, self.template_name, {
            "form": form, "championship": self.championship, "match": match,
            "form_title": "Annuler le match",
        })


class MatchForfeitView(MatchScopedMixin, RefereeRequiredMixin, View):
    """Ouvert aux arbitres (cadrés par division) en plus des administrateurs."""

    template_name = "competition/match_action_form.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {
            "form": MatchForfeitForm(match=self.match), "championship": self.championship,
            "match": self.match, "form_title": "Déclarer un forfait",
        })

    def post(self, request, *args, **kwargs):
        match = self.match
        form = MatchForfeitForm(request.POST, match=match)
        if form.is_valid():
            loser_id = int(form.cleaned_data["loser"])
            loser = match.player1 if loser_id == match.player1_id else match.player2
            try:
                declare_forfeit(
                    match, loser=loser, declared_by=request.user, note=form.cleaned_data["note"]
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                log_action(
                    actor=request.user, action=AuditAction.MATCH_FORFEIT_DECLARED, target=match,
                    championship=self.championship, request=request,
                    changes={"loser": str(loser.player)},
                )
                messages.success(request, "Forfait enregistré.")
                return redirect("competition:list", slug=self.championship.slug)
        return render(request, self.template_name, {
            "form": form, "championship": self.championship, "match": match,
            "form_title": "Déclarer un forfait",
        })


class MatchResultView(MatchParticipantOrStaffMixin, View):
    """Saisie/consultation d'un résultat — joueur du match, arbitre ou admin.

    Ouvert à un participant même sans droit d'administration : c'est son
    propre match. Le détail de l'autorisation (politique de saisie, etc.)
    est tranché par ``competition.services.result.submit_result``.
    """

    template_name = "competition/match_result.html"

    _STATUS_FEEDBACK = {
        ResultStatus.SUBMITTED: (AuditAction.RESULT_SUBMITTED, "info", "Résultat soumis, en attente de confirmation."),
        ResultStatus.CONFIRMED: (AuditAction.RESULT_CONFIRMED, "info", "Résultat confirmé, en attente de validation."),
        ResultStatus.VALIDATED: (AuditAction.RESULT_VALIDATED, "success", "Résultat validé."),
        ResultStatus.DISPUTED: (AuditAction.DISPUTE_OPENED, "warning", "Litige : les scores saisis ne correspondent pas."),
    }

    def _context(self, form):
        return {
            "championship": self.championship,
            "match": self.match,
            "form": form,
            "submissions": self.match.submissions.filter(is_superseded=False)
            .select_related("submitted_by", "submitted_by_participation__player")
            .order_by("submitted_at"),
        }

    def _blocked_by_daily_limit(self, request):
        """Limite de matchs par jour : ouvrir la fiche d'un match pas encore
        joué dévoilerait l'adversaire, ce que la limite atteinte interdit. Ne
        concerne ni le staff ni un match déjà joué/en attente de confirmation
        (le joueur doit pouvoir le confirmer)."""
        if can_referee(request.user, self.championship, self.match.division):
            return False
        if self.match.result_status not in (ResultStatus.NONE, ResultStatus.REJECTED):
            return False
        participation = participation_for_user(request.user, self.match)
        return participation is not None and next_opponent_hidden(participation)

    def _daily_limit_redirect(self, request):
        messages.warning(
            request,
            "Limite de matchs par jour atteinte : votre prochain adversaire sera "
            "dévoilé demain.",
        )
        return redirect("player_dashboard")

    def get(self, request, *args, **kwargs):
        if self._blocked_by_daily_limit(request):
            return self._daily_limit_redirect(request)
        form = ResultSubmissionForm(match=self.match, user=request.user)
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        if self._blocked_by_daily_limit(request):
            return self._daily_limit_redirect(request)
        form = ResultSubmissionForm(request.POST, match=self.match, user=request.user)
        if form.is_valid():
            score1, score2 = form.get_orientation_scores()
            try:
                submit_result(
                    match=self.match,
                    user=request.user,
                    score1=score1,
                    score2=score2,
                    submitting_participation=form.participation,
                )
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            else:
                self.match.refresh_from_db()
                action, level, message = self._STATUS_FEEDBACK.get(
                    self.match.result_status,
                    (AuditAction.RESULT_SUBMITTED, "info", "Résultat enregistré."),
                )
                log_action(
                    actor=request.user, action=action, target=self.match,
                    championship=self.championship, request=request,
                )
                getattr(messages, level)(request, message)
                return redirect("competition:result", slug=self.championship.slug, pk=self.match.pk)
        return render(request, self.template_name, self._context(form))


class MatchRejectResultView(MatchScopedMixin, RefereeRequiredMixin, View):
    template_name = "competition/match_action_form.html"

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {
            "form": MatchCancelForm(), "championship": self.championship, "match": self.match,
            "form_title": "Rejeter le résultat saisi",
        })

    def post(self, request, *args, **kwargs):
        form = MatchCancelForm(request.POST)
        if form.is_valid():
            try:
                reject_result(self.match, user=request.user, reason=form.cleaned_data["reason"])
            except PermissionDenied as exc:
                form.add_error(None, str(exc))
            else:
                log_action(
                    actor=request.user, action=AuditAction.RESULT_REJECTED, target=self.match,
                    championship=self.championship, request=request,
                    reason=form.cleaned_data["reason"],
                )
                messages.success(request, "Résultat rejeté ; le match peut être ressaisi.")
                return redirect("competition:list", slug=self.championship.slug)
        return render(request, self.template_name, {
            "form": form, "championship": self.championship, "match": self.match,
            "form_title": "Rejeter le résultat saisi",
        })
