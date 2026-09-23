"""Tests : limite de matchs par jour, compteur de retards, probabilités."""
import datetime

from django.test import TestCase
from django.utils import timezone

from competition.models import Match, Phase
from core.enums import ChampionshipStatus, PhaseKind, ResultStatus
from core.factories import (
    make_championship,
    make_division,
    make_player,
    make_user,
    register,
)


def _league(championship, division):
    return Phase.objects.create(
        championship=championship, division=division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
    )


class DailyMatchLimitTests(TestCase):
    """Réglage « matchs max. par jour » : une fois atteint, le prochain
    adversaire n'est plus dévoilé (dashboard, fiche de match, simulation)."""

    def setUp(self):
        self.championship = make_championship(
            name="Daily Limit Championship", season="dl-1", status=ChampionshipStatus.IN_PROGRESS
        )
        self.division = make_division(self.championship)
        self.phase = _league(self.championship, self.division)
        self.me_user = make_user("dl_me_t")
        self.me = register(
            self.championship, make_player("Me", "Dl", user=self.me_user), self.division
        )
        self.opp1 = register(
            self.championship, make_player("Opp", "Un", scrabblego_id="opp_un_id"), self.division
        )
        self.opp2 = register(
            self.championship, make_player("Opp", "Deux", scrabblego_id="opp_deux_id"), self.division
        )
        # Un match déjà joué aujourd'hui, un autre encore à jouer.
        self.played = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.me, player2=self.opp1, score1=400, score2=300,
            result_status=ResultStatus.VALIDATED, status="COMPLETED", counts_for_standings=True,
            played_at=timezone.now(), pair_key=Match.compute_pair_key(self.me.id, self.opp1.id),
        )
        self.todo = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.me, player2=self.opp2,
            pair_key=Match.compute_pair_key(self.me.id, self.opp2.id),
        )
        self.result_url = (
            f"/gestion/championnats/{self.championship.slug}/calendrier/{self.todo.pk}/resultat/"
        )
        self.client.force_login(self.me_user)

    def _set_limit(self, value):
        settings_obj = self.championship.settings
        settings_obj.max_matches_per_day = value
        settings_obj.save()

    def test_no_limit_shows_next_opponent(self):
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "opp_deux_id")

    def test_limit_not_yet_reached_shows_next_opponent(self):
        self._set_limit(2)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "opp_deux_id")
        self.assertContains(resp, "1 / 2")

    def test_limit_reached_hides_next_opponent_on_dashboard(self):
        self._set_limit(1)
        resp = self.client.get("/mon-espace/")
        self.assertNotContains(resp, "opp_deux_id")
        self.assertNotContains(resp, "Opp Deux")
        self.assertContains(resp, "dévoilé demain")

    def test_limit_reached_blocks_the_unplayed_match_page(self):
        self._set_limit(1)
        resp = self.client.get(self.result_url)
        self.assertRedirects(resp, "/mon-espace/", fetch_redirect_response=False)

    def test_limit_reached_still_allows_confirming_a_pending_match(self):
        self._set_limit(1)
        self.todo.result_status = ResultStatus.SUBMITTED
        self.todo.save()
        resp = self.client.get(self.result_url)
        self.assertEqual(resp.status_code, 200)

    def test_limit_reached_hides_remaining_opponents_on_simulation_page(self):
        self._set_limit(1)
        resp = self.client.get("/mon-espace/simulation/")
        self.assertNotContains(resp, "Opp Deux")

    def test_yesterdays_match_does_not_count(self):
        self._set_limit(1)
        self.played.played_at = timezone.now() - datetime.timedelta(days=2)
        self.played.save()
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "opp_deux_id")

    def test_staff_are_not_restricted(self):
        self._set_limit(1)
        admin = make_user("dl_admin_t", group="Super Admin")
        self.client.force_login(admin)
        resp = self.client.get(self.result_url)
        self.assertEqual(resp.status_code, 200)

    def test_settings_form_exposes_the_optional_field(self):
        from championships.forms import ChampionshipSettingsForm

        fields = ChampionshipSettingsForm().fields
        self.assertIn("max_matches_per_day", fields)
        self.assertFalse(fields["max_matches_per_day"].required)


class AdminDashboardLateCountTests(TestCase):
    def test_late_counter_is_not_capped_at_twenty(self):
        """Le compteur plafonnait à 20 (taille de la liste affichée) : sur un
        gros championnat il « ne bougeait plus »."""
        from dashboard.services import admin_dashboard_context

        championship = make_championship(
            name="Late Cap Championship", season="lc-1", status=ChampionshipStatus.IN_PROGRESS
        )
        division = make_division(championship)
        phase = _league(championship, division)
        players = [register(championship, make_player(f"P{i}", "Lc"), division) for i in range(9)]
        old = datetime.date.today() - datetime.timedelta(days=30)
        total = 0
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                Match.objects.create(
                    championship=championship, division=division, phase=phase,
                    player1=players[i], player2=players[j], scheduled_date=old,
                    pair_key=Match.compute_pair_key(players[i].id, players[j].id),
                )
                total += 1
        self.assertGreater(total, 20)

        context = admin_dashboard_context(championship)

        self.assertEqual(context["late_matches_count"], total)
        self.assertEqual(len(context["late_matches"]), 20)


class ProbabilityRefreshTests(TestCase):
    def test_probabilities_react_to_new_results_and_are_stable_otherwise(self):
        """Les bornes meilleur/pire cas ne bougeaient pas tant qu'il restait
        beaucoup de matchs ; la simulation réagit à chaque résultat, et donne
        les mêmes chiffres deux fois de suite sans nouveau résultat."""
        from analytics.services import movement_probabilities

        championship = make_championship(
            name="Prob Championship", season="pb-1", status=ChampionshipStatus.IN_PROGRESS
        )
        settings_obj = championship.settings
        settings_obj.finals_enabled = True
        settings_obj.finals_qualifiers_count = 2
        settings_obj.save()
        division = make_division(championship)
        phase = _league(championship, division)
        players = [register(championship, make_player(f"P{i}", "Pb"), division) for i in range(6)]
        matches = {}
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                matches[(i, j)] = Match.objects.create(
                    championship=championship, division=division, phase=phase,
                    player1=players[i], player2=players[j],
                    pair_key=Match.compute_pair_key(players[i].id, players[j].id),
                )

        target = players[0]
        before = movement_probabilities(target)
        self.assertEqual(before, movement_probabilities(target))

        for j in (1, 2, 3):
            match = matches[(0, j)]
            match.score1, match.score2 = 450, 300
            match.result_status = ResultStatus.VALIDATED
            match.status = "COMPLETED"
            match.counts_for_standings = True
            match.save()
        after = movement_probabilities(target)

        self.assertGreater(after["finals_pct"], before["finals_pct"])
        self.assertEqual(after["remaining_matches"], before["remaining_matches"] - 3)


class LateThresholdTests(TestCase):
    """Un match prévu hier et non joué doit compter « en retard » par défaut
    (avant : tolérance implicite de 3 jours, compteur à 0 alors que des matchs
    étaient manifestement en retard)."""

    def _championship_with_match(self, scheduled_date):
        championship = make_championship(
            name=f"Late Threshold {scheduled_date}", season=f"lt-{scheduled_date}",
            status=ChampionshipStatus.IN_PROGRESS,
        )
        division = make_division(championship)
        phase = _league(championship, division)
        p1 = register(championship, make_player("A", "Lt"), division)
        p2 = register(championship, make_player("B", "Lt"), division)
        Match.objects.create(
            championship=championship, division=division, phase=phase, player1=p1, player2=p2,
            scheduled_date=scheduled_date, pair_key=Match.compute_pair_key(p1.id, p2.id),
        )
        return championship

    def test_default_is_zero_days_of_grace(self):
        from dashboard.services import admin_dashboard_context

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        championship = self._championship_with_match(yesterday)
        self.assertEqual(championship.settings.late_match_threshold_days, 0)
        self.assertEqual(admin_dashboard_context(championship)["late_matches_count"], 1)

    def test_todays_match_is_not_late(self):
        from dashboard.services import admin_dashboard_context

        championship = self._championship_with_match(datetime.date.today())
        self.assertEqual(admin_dashboard_context(championship)["late_matches_count"], 0)

    def test_explicit_grace_period_is_still_honoured(self):
        from dashboard.services import admin_dashboard_context

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        championship = self._championship_with_match(yesterday)
        championship.settings.late_match_threshold_days = 3
        championship.settings.save()
        self.assertEqual(admin_dashboard_context(championship)["late_matches_count"], 0)


class ProgressChartTests(TestCase):
    def test_progress_chart_slices_add_up_to_total_matches(self):
        """Résultats en attente et forfaits ne doivent pas disparaître du
        graphique de progression (les parts somment au total des matchs)."""
        from dashboard.services import admin_dashboard_context

        championship = make_championship(
            name="Chart Sum Championship", season="cs-1", status=ChampionshipStatus.IN_PROGRESS
        )
        division = make_division(championship)
        phase = _league(championship, division)
        ps = [register(championship, make_player(f"P{i}", "Cs"), division) for i in range(4)]
        states = [
            dict(status="COMPLETED", result_status=ResultStatus.VALIDATED, score1=400, score2=300),
            dict(status="SCHEDULED", result_status=ResultStatus.SUBMITTED),
            dict(status="SCHEDULED"),
            dict(status="FORFEIT", result_status=ResultStatus.VALIDATED, score1=0, score2=0),
        ]
        pairs = [(0, 1), (0, 2), (0, 3), (1, 2)]
        for (i, j), extra in zip(pairs, states):
            Match.objects.create(
                championship=championship, division=division, phase=phase,
                player1=ps[i], player2=ps[j],
                pair_key=Match.compute_pair_key(ps[i].id, ps[j].id), **extra,
            )

        chart = admin_dashboard_context(championship)["chart_progress"]

        self.assertEqual(sum(chart["data"]), 4)
        self.assertEqual(dict(zip(chart["labels"], chart["data"]))["En attente de validation"], 1)
        self.assertEqual(dict(zip(chart["labels"], chart["data"]))["Programmés"], 1)
