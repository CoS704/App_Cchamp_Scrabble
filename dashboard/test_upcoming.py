"""Tests : prochains matchs configurables et compteurs à la validation."""
import datetime

from django.test import TestCase
from django.utils import timezone

from competition.models import Match, Phase
from core.enums import ChampionshipStatus, PhaseKind, ResultStatus
from core.factories import make_championship, make_division, make_player, make_user, register


class UpcomingMatchesTests(TestCase):
    def setUp(self):
        self.championship = make_championship(
            name="Upcoming Championship", season="up-1", status=ChampionshipStatus.IN_PROGRESS
        )
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division,
            kind=PhaseKind.LEAGUE, order=1, name="Ligue",
        )
        self.me_user = make_user("up_me_t")
        self.me = register(
            self.championship, make_player("Me", "Up", user=self.me_user), self.division
        )
        self.opponents = [
            register(self.championship, make_player(f"Adv{i}", "Up", scrabblego_id=f"adv_id_{i}"), self.division)
            for i in range(1, 5)
        ]
        base = datetime.date.today() + datetime.timedelta(days=1)
        self.matches = []
        for i, opp in enumerate(self.opponents):
            self.matches.append(
                Match.objects.create(
                    championship=self.championship, division=self.division, phase=self.phase,
                    player1=self.me, player2=opp,
                    scheduled_date=base + datetime.timedelta(days=i),
                    pair_key=Match.compute_pair_key(self.me.id, opp.id),
                )
            )
        self.client.force_login(self.me_user)

    def _set(self, **values):
        settings_obj = self.championship.settings
        for key, value in values.items():
            setattr(settings_obj, key, value)
        settings_obj.save()

    def test_default_shows_two_next_matches_in_date_order(self):
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_1")
        self.assertContains(resp, "adv_id_2")
        self.assertNotContains(resp, "adv_id_3")
        self.assertContains(resp, "+ 2 autres matchs à venir")

    def test_setting_controls_how_many_are_shown(self):
        self._set(upcoming_matches_shown=3)
        resp = self.client.get("/mon-espace/")
        for i in (1, 2, 3):
            self.assertContains(resp, f"adv_id_{i}")
        self.assertNotContains(resp, "adv_id_4")

    def test_one_shows_only_the_next_match(self):
        self._set(upcoming_matches_shown=1)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_1")
        self.assertNotContains(resp, "adv_id_2")

    # ---- limite quotidienne = matchs PRÉVUS le jour calendaire -----------
    def _schedule_today(self, count):
        today = datetime.date.today()
        for match in self.matches[:count]:
            match.scheduled_date = today
            match.save()

    def _play(self, match, when_scheduled=None):
        match.score1, match.score2 = 410, 350
        match.result_status, match.status = ResultStatus.VALIDATED, "COMPLETED"
        match.counts_for_standings = True
        match.played_at = timezone.now()
        if when_scheduled:
            match.scheduled_date = when_scheduled
        match.save()

    def test_daily_limit_reveals_the_days_scheduled_matches_only(self):
        self._set(upcoming_matches_shown=1, max_matches_per_day=3)
        self._schedule_today(3)
        resp = self.client.get("/mon-espace/")
        for i in (1, 2, 3):
            self.assertContains(resp, f"adv_id_{i}")
        self.assertNotContains(resp, "adv_id_4")  # prévu demain : jamais dévoilé
        self.assertContains(resp, "Vos matchs du jour")

    def test_day_quota_follows_the_setting_dynamically(self):
        self._schedule_today(4)
        self._set(max_matches_per_day=2)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_2")
        self.assertNotContains(resp, "adv_id_3")
        self._set(max_matches_per_day=4)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_4")

    def test_played_matches_of_the_day_are_listed_with_the_remaining_ones(self):
        self._schedule_today(3)
        self._play(self.matches[0])
        self._set(max_matches_per_day=3)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_1")
        self.assertContains(resp, "410 - 350")
        self.assertContains(resp, "adv_id_2")
        self.assertContains(resp, "adv_id_3")
        self.assertNotContains(resp, "adv_id_4")

    def test_all_days_matches_played_hides_tomorrows_opponent(self):
        self._schedule_today(2)
        self._play(self.matches[0])
        self._play(self.matches[1])
        self._set(max_matches_per_day=2)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "dévoilé demain")
        self.assertNotContains(resp, "adv_id_3")

    def test_late_matches_played_today_do_not_use_the_days_quota(self):
        """Régression : des matchs en retard joués aujourd'hui comptaient dans
        le quota (2/2) et masquaient les vrais matchs du jour."""
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        # 2 matchs prévus hier, joués aujourd'hui (rattrapage)
        for match in self.matches[:2]:
            match.scheduled_date = yesterday
            match.save()
            self._play(match)
        # les 2 vrais matchs du jour
        for match in self.matches[2:4]:
            match.scheduled_date = datetime.date.today()
            match.save()
        self._set(max_matches_per_day=2)

        resp = self.client.get("/mon-espace/")

        self.assertNotContains(resp, "dévoilé demain")
        self.assertContains(resp, "0 / 2")
        self.assertContains(resp, "adv_id_3")
        self.assertContains(resp, "adv_id_4")

    def test_late_matches_are_listed_separately_and_never_hidden(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        self.matches[0].scheduled_date = yesterday  # en retard, non joué
        self.matches[0].save()
        for match in self.matches[1:3]:
            match.scheduled_date = datetime.date.today()
            match.save()
            self._play(match)
        self._set(max_matches_per_day=2)  # quota du jour atteint

        resp = self.client.get("/mon-espace/")

        self.assertContains(resp, "dévoilé demain")
        self.assertContains(resp, "Matchs en retard")
        self.assertContains(resp, "adv_id_1")

    def test_late_match_page_stays_open_when_the_days_quota_is_reached(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        late = self.matches[0]
        late.scheduled_date = yesterday
        late.save()
        for match in self.matches[1:3]:
            match.scheduled_date = datetime.date.today()
            match.save()
            self._play(match)
        self._set(max_matches_per_day=2)
        url = f"/gestion/championnats/{self.championship.slug}/calendrier/{late.pk}/resultat/"
        self.assertEqual(self.client.get(url).status_code, 200)

        future = self.matches[3]
        future_url = f"/gestion/championnats/{self.championship.slug}/calendrier/{future.pk}/resultat/"
        self.assertRedirects(self.client.get(future_url), "/mon-espace/", fetch_redirect_response=False)

    def test_result_awaiting_confirmation_is_listed_separately(self):
        pending = self.matches[0]
        pending.result_status = ResultStatus.SUBMITTED
        pending.save()
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "Résultat à confirmer")
        # le match en attente n'occupe plus une place dans « prochains matchs »
        self.assertContains(resp, "adv_id_2")
        self.assertContains(resp, "adv_id_3")

    def test_settings_form_exposes_the_field(self):
        from championships.forms import ChampionshipSettingsForm

        self.assertIn("upcoming_matches_shown", ChampionshipSettingsForm().fields)


class MatchCountsOnValidationTests(TestCase):
    def setUp(self):
        self.championship = make_championship(
            name="Counts Championship", season="mc-1", status=ChampionshipStatus.IN_PROGRESS
        )
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division,
            kind=PhaseKind.LEAGUE, order=1, name="Ligue",
        )
        self.user_a = make_user("mc_a_t")
        self.a = register(self.championship, make_player("A", "Mc", user=self.user_a), self.division)
        self.b = register(self.championship, make_player("B", "Mc"), self.division)
        self.c = register(self.championship, make_player("C", "Mc"), self.division)
        self.d = register(self.championship, make_player("D", "Mc"), self.division)

        def played(p1, p2, today=False):
            return Match.objects.create(
                championship=self.championship, division=self.division, phase=self.phase,
                player1=p1, player2=p2, score1=400, score2=300,
                result_status=ResultStatus.VALIDATED, status="COMPLETED",
                counts_for_standings=True,
                played_at=timezone.now() if today else timezone.now() - datetime.timedelta(days=3),
                pair_key=Match.compute_pair_key(p1.id, p2.id),
            )

        played(self.a, self.c)                 # A : 1 joué (ancien)
        played(self.a, self.d, today=True)     # A : 2 joués, 1 aujourd'hui
        self.current = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.a, player2=self.b, pair_key=Match.compute_pair_key(self.a.id, self.b.id),
        )
        self.url = f"/gestion/championnats/{self.championship.slug}/calendrier/{self.current.pk}/resultat/"

    def test_counts_service(self):
        from competition.services.counts import participation_match_counts

        counts = participation_match_counts(self.a, exclude_match=self.current)
        self.assertEqual(counts["played"], 2)
        self.assertEqual(counts["played_today"], 1)
        self.assertEqual(counts["remaining"], 0)
        # sans exclure le match courant, il compte parmi les restants
        self.assertEqual(participation_match_counts(self.a)["remaining"], 1)
        self.assertEqual(participation_match_counts(self.b, exclude_match=self.current)["played"], 0)

    def test_admin_sees_both_players_counts_on_the_result_page(self):
        admin = make_user("mc_admin_t", group="Super Admin")
        self.client.force_login(admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Matchs déjà joués")
        counts = {item["player"].last_name + item["player"].first_name: item["counts"]["played"]
                  for item in resp.context["player_counts"]}
        self.assertEqual(counts, {"McA": 2, "McB": 0})

    def test_daily_limit_is_shown_next_to_todays_count(self):
        settings_obj = self.championship.settings
        settings_obj.max_matches_per_day = 3
        settings_obj.save()
        admin = make_user("mc_admin2_t", group="Super Admin")
        self.client.force_login(admin)
        resp = self.client.get(self.url)
        self.assertContains(resp, "/ 3")

    def test_players_do_not_see_the_counts(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Matchs déjà joués")
        self.assertEqual(resp.context["player_counts"], [])


class CalendarDatesFollowTheDailyLimitTests(TestCase):
    """Avec N matchs/jour, N journées partagent la même date (sinon les dates
    ne reflètent pas le rythme réel et « le jour » ne veut rien dire)."""

    def _division_with_players(self, n_players=6, per_day=None):
        championship = make_championship(
            name=f"Redate {per_day}", season=f"rd-{per_day}", status=ChampionshipStatus.IN_PROGRESS
        )
        if per_day:
            championship.settings.max_matches_per_day = per_day
            championship.settings.save()
        division = make_division(championship)
        for i in range(n_players):
            register(championship, make_player(f"P{i}", "Rd"), division)
        return championship, division

    def test_generation_groups_matchdays_by_date(self):
        from competition.services.scheduling import generate_schedule

        championship, division = self._division_with_players(per_day=2)
        start = datetime.date(2026, 10, 1)
        generate_schedule(championship=championship, division=division, start_date=start, interval_days=1)
        dates = list(
            Match.objects.filter(division=division).order_by("matchday__number")
            .values_list("matchday__number", "scheduled_date").distinct()
        )
        by_number = dict(dates)
        self.assertEqual(by_number[1], start)
        self.assertEqual(by_number[2], start)
        self.assertEqual(by_number[3], start + datetime.timedelta(days=1))
        self.assertEqual(by_number[5], start + datetime.timedelta(days=2))

    def test_redate_moves_an_existing_one_per_day_calendar_without_deleting_matches(self):
        from competition.services.scheduling import generate_schedule, redate_league_calendar

        championship, division = self._division_with_players(per_day=None)
        start = datetime.date(2026, 10, 1)
        generate_schedule(championship=championship, division=division, start_date=start, interval_days=1)
        total_before = Match.objects.filter(division=division).count()
        championship.settings.max_matches_per_day = 2
        championship.settings.save()

        moved = redate_league_calendar(championship)

        self.assertGreater(moved, 0)
        self.assertEqual(Match.objects.filter(division=division).count(), total_before)
        by_number = dict(
            Match.objects.filter(division=division)
            .values_list("matchday__number", "scheduled_date").distinct()
        )
        self.assertEqual(by_number[1], start)
        self.assertEqual(by_number[2], start)
        self.assertEqual(by_number[4], start + datetime.timedelta(days=1))
        # idempotent
        self.assertEqual(redate_league_calendar(championship), 0)

    def test_redate_keeps_manually_rescheduled_matches(self):
        from competition.services.scheduling import generate_schedule, redate_league_calendar

        championship, division = self._division_with_players(per_day=None)
        generate_schedule(
            championship=championship, division=division,
            start_date=datetime.date(2026, 10, 1), interval_days=1,
        )
        manual = Match.objects.filter(division=division, matchday__number=4).first()
        manual.scheduled_date = datetime.date(2026, 12, 25)
        manual.save()
        championship.settings.max_matches_per_day = 2
        championship.settings.save()

        redate_league_calendar(championship)

        manual.refresh_from_db()
        self.assertEqual(manual.scheduled_date, datetime.date(2026, 12, 25))
