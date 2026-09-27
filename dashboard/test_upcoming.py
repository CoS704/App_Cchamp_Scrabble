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


    def test_redate_never_moves_already_played_matchdays(self):
        """Régression : augmenter le rythme comprimait toute la saison depuis
        la date de départ d'origine, ce qui pouvait faire passer des journées
        déjà jouées pour « replanifiées », ou faire tomber les journées
        restantes dans le passé (donc « en retard » alors qu'elles ne
        l'étaient pas)."""
        from competition.services.scheduling import generate_schedule, redate_league_calendar
        from core.enums import MatchStatus, ResultStatus

        championship, division = self._division_with_players(n_players=8, per_day=2)
        start = datetime.date.today() - datetime.timedelta(days=6)
        generate_schedule(championship=championship, division=division, start_date=start, interval_days=1)

        # Journées 1 et 2 (jour 1) réellement jouées.
        played = Match.objects.filter(division=division, matchday__number__in=[1, 2])
        played.update(
            status=MatchStatus.COMPLETED, result_status=ResultStatus.VALIDATED,
            score1=400, score2=300, counts_for_standings=True,
        )
        played_dates_before = dict(
            Match.objects.filter(division=division, matchday__number__in=[1, 2])
            .values_list("matchday__number", "scheduled_date")
        )

        championship.settings.max_matches_per_day = 4  # rythme doublé
        championship.settings.save()
        redate_league_calendar(championship)

        played_dates_after = dict(
            Match.objects.filter(division=division, matchday__number__in=[1, 2])
            .values_list("matchday__number", "scheduled_date")
        )
        self.assertEqual(played_dates_before, played_dates_after)

        today = datetime.date.today()
        remaining_dates = Match.objects.filter(
            division=division, matchday__number__gte=3
        ).values_list("scheduled_date", flat=True)
        for d in remaining_dates:
            self.assertGreaterEqual(d, today)


    def test_redate_moves_a_partially_played_matchday_as_a_whole(self):
        """Régression : une journée figée dès qu'UN seul match y était joué
        restait à une date passée pour tous les autres joueurs de cette même
        journée, qui n'y étaient pour rien — l'admin n'avait pourtant fait
        que changer le rythme quotidien."""
        from competition.services.scheduling import generate_schedule, redate_league_calendar
        from core.enums import MatchStatus, ResultStatus

        championship, division = self._division_with_players(n_players=8, per_day=2)
        start = datetime.date.today() - datetime.timedelta(days=4)
        generate_schedule(championship=championship, division=division, start_date=start, interval_days=1)

        # Journée 3 : 1 seul match sur 4 joué (les autres joueurs n'ont pas
        # encore joué leur adversaire de cette journée).
        one_match = Match.objects.filter(division=division, matchday__number=3).first()
        one_match.status, one_match.result_status = MatchStatus.COMPLETED, ResultStatus.VALIDATED
        one_match.score1, one_match.score2, one_match.counts_for_standings = 400, 300, True
        one_match.save()

        championship.settings.max_matches_per_day = 4  # rythme changé
        championship.settings.save()
        redate_league_calendar(championship)

        today = datetime.date.today()
        md3_dates = set(
            Match.objects.filter(division=division, matchday__number=3).values_list("scheduled_date", flat=True)
        )
        self.assertEqual(len(md3_dates), 1)  # toute la journée bouge ensemble
        self.assertGreaterEqual(md3_dates.pop(), today)  # plus jamais dans le passé


    def test_redate_is_truly_idempotent_with_out_of_order_completed_rounds(self):
        """Régression : le pas se déduisait de TOUTES les dates, y compris
        celles des journées qu'on vient de déplacer — il changeait donc d'un
        appel à l'autre et redéplaçait des journées à chaque nouvel appel."""
        from competition.services.scheduling import generate_schedule, redate_league_calendar
        from core.enums import MatchStatus, ResultStatus

        championship, division = self._division_with_players(n_players=8, per_day=2)
        start = datetime.date.today() - datetime.timedelta(days=5)
        generate_schedule(championship=championship, division=division, start_date=start, interval_days=1)

        # Journée 5 entièrement décidée alors que les journées 1 à 4 ne le
        # sont pas encore (ordre d'achèvement réel, pas forcément séquentiel).
        Match.objects.filter(division=division, matchday__number=5).update(
            status=MatchStatus.COMPLETED, result_status=ResultStatus.VALIDATED,
            score1=400, score2=300, counts_for_standings=True,
        )

        championship.settings.max_matches_per_day = 3
        championship.settings.save()

        first = redate_league_calendar(championship)
        dates_after_first = list(
            Match.objects.filter(division=division).order_by("id").values_list("scheduled_date", flat=True)
        )
        second = redate_league_calendar(championship)
        dates_after_second = list(
            Match.objects.filter(division=division).order_by("id").values_list("scheduled_date", flat=True)
        )

        self.assertGreater(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(dates_after_first, dates_after_second)


class SettingsFormTriggersRedateTests(TestCase):
    """Régression : après avoir changé « matchs max. par jour » via le
    formulaire des paramètres, le calendrier n'était pas recalé — le recalage
    automatique lisait championship.settings, une relation mise en cache
    depuis le dispatch de la requête (donc encore sur l'ancienne valeur),
    au lieu du réglage qui vient d'être enregistré."""

    def test_saving_the_setting_via_the_web_form_redates_the_calendar(self):
        import datetime

        from competition.models import Matchday
        from competition.services.scheduling import generate_schedule

        championship = make_championship(name="Redate Form", season="rdf-1")
        championship.settings.max_matches_per_day = 2
        championship.settings.save()
        division = make_division(championship)
        for i in range(6):
            register(championship, make_player(f"P{i}", "Rf"), division)
        generate_schedule(
            championship=championship, division=division,
            start_date=datetime.date(2026, 9, 1), interval_days=1,
        )
        admin = make_user("redate_form_admin_t", group="Super Admin")
        self.client.force_login(admin)
        data = {
            "points_win": "3", "points_draw": "1", "points_loss": "0",
            "points_forfeit_win": "3", "points_forfeit_loss": "0",
            "forfeit_score_for": "0", "forfeit_score_against": "0",
            "primary_tiebreak": "SCORE_DIFF", "round_robin_legs": "1",
            "result_entry_policy": "WINNER_ONLY", "result_confirmation_required": "on",
            "double_entry_auto_confirm": "on", "late_match_threshold_days": "0",
            "max_matches_per_day": "3", "upcoming_matches_shown": "3",
            "finals_qualifiers_count": "4", "finals_format": "SEMI_1V4_2V3",
            "finals_third_place": "on", "carry_over_between_editions": "on",
        }

        resp = self.client.post(f"/gestion/championnats/{championship.slug}/parametres/", data)

        self.assertEqual(resp.status_code, 302)
        dates = dict(
            Matchday.objects.filter(phase__championship=championship)
            .order_by("number").values_list("number", "scheduled_date")
        )
        self.assertEqual(dates[1], dates[2])
        self.assertEqual(dates[2], dates[3])
        self.assertNotEqual(dates[3], dates[4])


