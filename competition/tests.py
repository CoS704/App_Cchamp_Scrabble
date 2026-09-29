"""Tests calendrier (round-robin) et résultats (double saisie, litiges) — §60."""
from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase

from competition.models import Match, Phase
from competition.services.result import reject_result, submit_result
from competition.services.scheduling import (
    expected_match_count,
    expected_matchday_count,
    generate_round_robin_rounds,
    generate_schedule,
)
from core.enums import OutcomeType, PhaseKind, ResultEntryPolicy, ResultStatus
from core.factories import make_championship, make_division, make_player, make_user, register


class RoundRobinAlgorithmTests(TestCase):
    def test_invariants_for_various_sizes(self):
        for n in (2, 3, 4, 5, 6, 7, 10, 11, 20):
            with self.subTest(n=n):
                rounds = generate_round_robin_rounds(list(range(1, n + 1)))
                pairs = [p for r in rounds for p in r]
                self.assertTrue(all(a != b for a, b in pairs))
                normalized = {tuple(sorted(p)) for p in pairs}
                self.assertEqual(len(normalized), len(pairs))
                self.assertEqual(len(pairs), expected_match_count(n))
                self.assertEqual(len(rounds), expected_matchday_count(n))
                for r in rounds:
                    players_in_round = [x for p in r for x in p]
                    self.assertEqual(len(players_in_round), len(set(players_in_round)))

    def test_known_examples_from_spec(self):
        self.assertEqual(expected_match_count(10), 45)
        self.assertEqual(expected_match_count(20), 190)
        self.assertEqual(expected_match_count(50), 1225)

    def test_double_round_robin_doubles_match_count(self):
        self.assertEqual(expected_match_count(10, legs=2), 90)


class GenerateScheduleTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Schedule Championship", season="sched-1")
        self.division = make_division(self.championship)
        self.players = [make_player(f"P{i}", "T") for i in range(5)]
        for p in self.players:
            register(self.championship, p, self.division)

    def test_generates_correct_counts(self):
        matches = generate_schedule(championship=self.championship, division=self.division)
        self.assertEqual(len(matches), 10)
        self.assertEqual(Match.objects.filter(division=self.division).count(), 10)

    def test_requires_two_players(self):
        empty_division = make_division(self.championship, name="Empty", level=2, carryover_key="empty")
        with self.assertRaises(ValidationError):
            generate_schedule(championship=self.championship, division=empty_division)

    def test_regeneration_blocked_without_force(self):
        generate_schedule(championship=self.championship, division=self.division)
        with self.assertRaises(ValidationError):
            generate_schedule(championship=self.championship, division=self.division)


class ResultSubmissionTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Result Championship", season="res-1")
        self.division = make_division(self.championship)
        self.admin = make_user("radmin_t", group="Super Admin")
        self.user_a = make_user("ra_t")
        self.user_b = make_user("rb_t")
        self.player_a = make_player("A", "R", user=self.user_a)
        self.player_b = make_player("B", "R", user=self.user_b)
        self.part_a = register(self.championship, self.player_a, self.division)
        self.part_b = register(self.championship, self.player_b, self.division)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.match = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.part_a, player2=self.part_b,
        )

    def test_winner_only_blocks_self_declared_loser(self):
        with self.assertRaises(PermissionDenied):
            submit_result(
                match=self.match, user=self.user_b, score1=450, score2=300,
                submitting_participation=self.part_b,
            )

    def test_opponent_can_confirm_even_though_they_lose(self):
        submit_result(
            match=self.match, user=self.user_a, score1=450, score2=300,
            submitting_participation=self.part_a,
        )
        self.match.refresh_from_db()
        self.assertEqual(self.match.result_status, ResultStatus.SUBMITTED)
        self.assertFalse(self.match.counts_for_standings)

        submit_result(
            match=self.match, user=self.user_b, score1=450, score2=300,
            submitting_participation=self.part_b,
        )
        self.match.refresh_from_db()
        self.assertEqual(self.match.result_status, ResultStatus.VALIDATED)
        self.assertTrue(self.match.counts_for_standings)
        self.assertEqual(self.match.winner_id, self.part_a.id)

    def test_conflicting_submissions_create_dispute(self):
        submit_result(match=self.match, user=self.user_a, score1=450, score2=300, submitting_participation=self.part_a)
        submit_result(match=self.match, user=self.user_b, score1=420, score2=300, submitting_participation=self.part_b)
        self.match.refresh_from_db()
        self.assertEqual(self.match.result_status, ResultStatus.DISPUTED)
        self.assertFalse(self.match.counts_for_standings)

    def test_admin_resolves_dispute_immediately(self):
        submit_result(match=self.match, user=self.user_a, score1=450, score2=300, submitting_participation=self.part_a)
        submit_result(match=self.match, user=self.user_b, score1=420, score2=300, submitting_participation=self.part_b)
        submit_result(match=self.match, user=self.admin, score1=450, score2=300)
        self.match.refresh_from_db()
        self.assertEqual(self.match.result_status, ResultStatus.VALIDATED)
        self.assertTrue(self.match.counts_for_standings)

    def test_admin_only_policy_blocks_players(self):
        self.championship.settings.result_entry_policy = ResultEntryPolicy.ADMIN_ONLY
        self.championship.settings.save()
        with self.assertRaises(PermissionDenied):
            submit_result(
                match=self.match, user=self.user_a, score1=450, score2=300,
                submitting_participation=self.part_a,
            )

    def test_cannot_modify_validated_result_as_player(self):
        submit_result(match=self.match, user=self.admin, score1=450, score2=300)
        with self.assertRaises(ValidationError):
            submit_result(
                match=self.match, user=self.user_a, score1=400, score2=300,
                submitting_participation=self.part_a,
            )

    def test_reject_reopens_match(self):
        submit_result(match=self.match, user=self.admin, score1=450, score2=300)
        reject_result(self.match, user=self.admin, reason="Erreur de saisie")
        self.match.refresh_from_db()
        self.assertEqual(self.match.result_status, ResultStatus.REJECTED)
        self.assertFalse(self.match.counts_for_standings)
        self.assertIsNone(self.match.score1)

    def test_no_negative_scores(self):
        with self.assertRaises(ValidationError):
            submit_result(match=self.match, user=self.admin, score1=-5, score2=300)


class CalendarResultStatusFilterTests(TestCase):
    """Le dashboard renvoie vers le calendrier filtré : l'admin doit pouvoir
    y retrouver précisément les résultats en attente et les litiges (§22)."""

    def setUp(self):
        self.championship = make_championship(name="Filter Championship", season="filt-1")
        self.division = make_division(self.championship)
        self.admin = make_user("filt_admin_t", group="Super Admin")
        self.user_a = make_user("filt_a_t")
        self.user_b = make_user("filt_b_t")
        self.player_a = make_player("A", "F", user=self.user_a)
        self.player_b = make_player("B", "F", user=self.user_b)
        self.part_a = register(self.championship, self.player_a, self.division)
        self.part_b = register(self.championship, self.player_b, self.division)
        self.user_c = make_user("filt_c_t")
        self.user_d = make_user("filt_d_t")
        self.player_c = make_player("C", "F", user=self.user_c)
        self.player_d = make_player("D", "F", user=self.user_d)
        self.part_c = register(self.championship, self.player_c, self.division)
        self.part_d = register(self.championship, self.player_d, self.division)
        phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.pending_match = Match.objects.create(
            championship=self.championship, division=self.division, phase=phase,
            player1=self.part_a, player2=self.part_b,
        )
        submit_result(
            match=self.pending_match, user=self.user_a, score1=450, score2=300,
            submitting_participation=self.part_a,
        )
        self.disputed_match = Match.objects.create(
            championship=self.championship, division=self.division, phase=phase,
            player1=self.part_c, player2=self.part_d,
        )
        submit_result(
            match=self.disputed_match, user=self.user_c, score1=450, score2=300,
            submitting_participation=self.part_c,
        )
        submit_result(
            match=self.disputed_match, user=self.user_d, score1=420, score2=300,
            submitting_participation=self.part_d,
        )
        self.client.force_login(self.admin)

    def _list_url(self, **params):
        from urllib.parse import urlencode

        base = f"/gestion/championnats/{self.championship.slug}/calendrier/"
        return f"{base}?{urlencode(params)}" if params else base

    def test_pending_filter_shows_only_submitted_or_confirmed(self):
        resp = self.client.get(self._list_url(result_status="PENDING"))
        self.assertEqual(resp.status_code, 200)
        matches = list(resp.context["matches"])
        self.assertIn(self.pending_match, matches)

    def test_disputed_status_filter_is_reachable_from_dashboard_link(self):
        # Le lien du dashboard pointe vers ?status=DISPUTED (état du Match,
        # synchronisé avec result_status=DISPUTED par submit_result).
        resp = self.client.get(self._list_url(status="DISPUTED"))
        self.assertEqual(resp.status_code, 200)
        matches = list(resp.context["matches"])
        self.assertIn(self.disputed_match, matches)
        self.assertNotIn(self.pending_match, matches)


class FixForfeitOutcomeTypesCommandTests(TestCase):
    """Un forfait saisi à la main (score technique tapé au lieu d'utiliser
    « Déclarer un forfait ») reste taggé ``outcome_type=NORMAL`` et fausse
    les statistiques qui excluent les forfaits — la commande corrige ça sans
    toucher au score ni au vainqueur déjà enregistrés."""

    def setUp(self):
        self.championship = make_championship(name="Forfeit Fix Championship", season="ffix-1")
        self.championship.settings.forfeit_score_for = 300
        self.championship.settings.forfeit_score_against = 0
        self.championship.settings.save()
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.px = register(self.championship, make_player("X", "Ff"), self.division)
        self.py = register(self.championship, make_player("Y", "Ff"), self.division)
        self.pz = register(self.championship, make_player("Z", "Ff"), self.division)

        def validated(a, b, s1, s2, *, leg=1):
            return Match.objects.create(
                championship=self.championship, division=self.division, phase=self.phase,
                player1=a, player2=b, leg=leg, score1=s1, score2=s2,
                winner=(a if s1 > s2 else (b if s2 > s1 else None)),
                result_status=ResultStatus.VALIDATED, status="COMPLETED", counts_for_standings=True,
                pair_key=Match.compute_pair_key(a.id, b.id),
            )

        self.hand_typed_forfeit = validated(self.px, self.py, 300, 0)
        self.hand_typed_forfeit_reverse_side = validated(self.py, self.pz, 0, 300, leg=2)
        self.double_forfeit = validated(self.pz, self.px, 0, 0, leg=2)
        self.real_close_game = validated(self.px, self.pz, 301, 299, leg=3)

    def test_dry_run_reports_but_does_not_modify(self):
        out = StringIO()
        call_command("fix_forfeit_outcome_types", stdout=out)
        self.hand_typed_forfeit.refresh_from_db()
        self.assertEqual(self.hand_typed_forfeit.outcome_type, OutcomeType.NORMAL)
        self.assertIn(str(self.hand_typed_forfeit.id), out.getvalue())

    def test_apply_corrects_outcome_type_and_status_only(self):
        call_command("fix_forfeit_outcome_types", "--apply", stdout=StringIO())

        self.hand_typed_forfeit.refresh_from_db()
        self.assertEqual(self.hand_typed_forfeit.outcome_type, OutcomeType.FORFEIT_P2)
        self.assertEqual(self.hand_typed_forfeit.status, "FORFEIT")
        self.assertEqual(self.hand_typed_forfeit.score1, 300)  # score inchangé
        self.assertEqual(self.hand_typed_forfeit.winner_id, self.px.id)  # vainqueur inchangé

        self.hand_typed_forfeit_reverse_side.refresh_from_db()
        self.assertEqual(self.hand_typed_forfeit_reverse_side.outcome_type, OutcomeType.FORFEIT_P1)

        self.double_forfeit.refresh_from_db()
        self.assertEqual(self.double_forfeit.outcome_type, OutcomeType.DOUBLE_FORFEIT)
        self.assertIsNone(self.double_forfeit.winner_id)

    def test_real_lopsided_score_is_never_mistaken_for_a_forfeit(self):
        call_command("fix_forfeit_outcome_types", "--apply", stdout=StringIO())
        self.real_close_game.refresh_from_db()
        self.assertEqual(self.real_close_game.outcome_type, OutcomeType.NORMAL)

    def test_command_is_idempotent(self):
        call_command("fix_forfeit_outcome_types", "--apply", stdout=StringIO())
        out = StringIO()
        call_command("fix_forfeit_outcome_types", "--apply", stdout=out)
        self.assertIn("Aucun match à corriger", out.getvalue())
