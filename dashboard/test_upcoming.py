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

    def test_daily_allowance_caps_the_list(self):
        """Limite de 1 match/jour et 0 joué : on ne dévoile qu'un adversaire
        même si 2 sont demandés (jamais au-delà du quota du jour)."""
        self._set(upcoming_matches_shown=2, max_matches_per_day=1)
        resp = self.client.get("/mon-espace/")
        self.assertContains(resp, "adv_id_1")
        self.assertNotContains(resp, "adv_id_2")

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
