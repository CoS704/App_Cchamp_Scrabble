"""Tests du tableau final : tirage, progression automatique (§60)."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from competition.models import Match, Phase
from competition.services.result import submit_result
from core.enums import PhaseKind
from core.factories import make_championship, make_division, make_player, make_user, register
from finals.models import BracketSlot
from finals.services import _standard_seed_order, generate_bracket


class SeedOrderTests(TestCase):
    def test_standard_orders(self):
        self.assertEqual(_standard_seed_order(2), [1, 2])
        self.assertEqual(_standard_seed_order(4), [1, 4, 2, 3])
        self.assertEqual(_standard_seed_order(8), [1, 8, 4, 5, 2, 7, 3, 6])


class BracketGenerationTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Bracket Championship", season="brk-1")
        self.championship.settings.finals_enabled = True
        self.championship.settings.save()
        self.division = make_division(self.championship)
        self.admin = make_user("fadmin_t", group="Super Admin")
        self.players = [
            register(self.championship, make_player(n, "F"), self.division)
            for n in ["Un", "Deux", "Trois", "Quatre"]
        ]
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )

        def play(a, b, s1, s2):
            m = Match.objects.create(
                championship=self.championship, division=self.division, phase=self.phase, player1=a, player2=b,
                pair_key=Match.compute_pair_key(a.id, b.id),
            )
            submit_result(match=m, user=self.admin, score1=s1, score2=s2)

        p1, p2, p3, p4 = self.players
        play(p1, p2, 500, 300)
        play(p1, p3, 500, 250)
        play(p1, p4, 500, 200)
        play(p2, p3, 450, 300)
        play(p2, p4, 450, 280)
        play(p3, p4, 400, 350)

    def test_seeding_matches_standard_order(self):
        bracket = generate_bracket(championship=self.championship, division=self.division)
        round0 = list(
            BracketSlot.objects.filter(bracket=bracket, round_index=0, is_third_place=False).order_by("position")
        )
        self.assertEqual([s.seed for s in round0], [1, 4, 2, 3])
        self.assertEqual(round0[0].participation_id, self.players[0].id)
        self.assertEqual(round0[1].participation_id, self.players[3].id)

    def test_progression_creates_final_after_semis(self):
        bracket = generate_bracket(championship=self.championship, division=self.division)
        round0 = list(
            BracketSlot.objects.filter(bracket=bracket, round_index=0, is_third_place=False).order_by("position")
        )
        submit_result(match=round0[0].match, user=self.admin, score1=500, score2=300)
        submit_result(match=round0[2].match, user=self.admin, score1=480, score2=320)

        final_slot = BracketSlot.objects.get(bracket=bracket, round_index=1, is_third_place=False, position=0)
        self.assertIsNotNone(final_slot.match)
        self.assertEqual(
            {final_slot.match.player1_id, final_slot.match.player2_id},
            {self.players[0].id, self.players[1].id},
        )

    def test_disabled_finals_blocked(self):
        self.championship.settings.finals_enabled = False
        self.championship.settings.save()
        with self.assertRaises(ValidationError):
            generate_bracket(championship=self.championship, division=self.division)

    def test_duplicate_generation_blocked(self):
        generate_bracket(championship=self.championship, division=self.division)
        with self.assertRaises(ValidationError):
            generate_bracket(championship=self.championship, division=self.division)
