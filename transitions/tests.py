"""Tests de génération de la saison suivante (§60)."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from championships.models import PromotionRelegationRule
from competition.models import Match, Phase
from competition.services.result import submit_result
from core.enums import ChampionshipStatus, MovementType, PhaseKind, PromotionMethod
from core.factories import make_championship, make_division, make_player, make_user, register
from transitions.services import confirm_transition, propose_transition


class SeasonTransitionTests(TestCase):
    def setUp(self):
        self.admin = make_user("tadmin_t", group="Super Admin")
        self.championship = make_championship(
            name="Transition Championship", season="trans-1", status=ChampionshipStatus.IN_PROGRESS
        )
        self.d1 = make_division(self.championship, name="D1", level=1, carryover_key="d1")
        self.d2 = make_division(self.championship, name="D2", level=2, carryover_key="d2")
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.PROMOTION,
            source_division=self.d2, target_division=self.d1, method=PromotionMethod.TOP_N, value_n=1,
        )
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.RELEGATION,
            source_division=self.d1, target_division=self.d2, method=PromotionMethod.BOTTOM_N, value_n=1,
        )

        def play(division, phase, a, b, s1, s2):
            m = Match.objects.create(
                championship=self.championship, division=division, phase=phase, player1=a, player2=b,
                pair_key=Match.compute_pair_key(a.id, b.id),
            )
            submit_result(match=m, user=self.admin, score1=s1, score2=s2)

        self.a = [register(self.championship, make_player(f"A{i}", "T"), self.d1) for i in range(3)]
        self.b = [register(self.championship, make_player(f"B{i}", "T"), self.d2) for i in range(3)]
        phase_d1 = Phase.objects.create(
            championship=self.championship, division=self.d1, kind=PhaseKind.LEAGUE, order=1, name="L1"
        )
        phase_d2 = Phase.objects.create(
            championship=self.championship, division=self.d2, kind=PhaseKind.LEAGUE, order=1, name="L2"
        )
        play(self.d1, phase_d1, self.a[0], self.a[1], 500, 300)
        play(self.d1, phase_d1, self.a[0], self.a[2], 500, 250)
        play(self.d1, phase_d1, self.a[1], self.a[2], 450, 300)
        play(self.d2, phase_d2, self.b[0], self.b[1], 500, 300)
        play(self.d2, phase_d2, self.b[0], self.b[2], 500, 250)
        play(self.d2, phase_d2, self.b[1], self.b[2], 450, 300)

    def test_propose_computes_correct_moves(self):
        transition = propose_transition(championship=self.championship, created_by=self.admin)
        moves = {m.source_participation_id: m for m in transition.moves.all()}
        self.assertEqual(moves[self.a[2].id].move_type, "RELEGATED")
        self.assertEqual(moves[self.a[2].id].to_carryover_key, "d2")
        self.assertEqual(moves[self.b[0].id].move_type, "PROMOTED")
        self.assertEqual(moves[self.b[0].id].to_carryover_key, "d1")
        self.assertEqual(moves[self.a[0].id].move_type, "KEPT")

    def test_confirm_creates_new_edition_correctly(self):
        transition = propose_transition(championship=self.championship, created_by=self.admin)
        new_champ = confirm_transition(
            transition=transition, confirmed_by=self.admin, new_name="Suivant", new_season="trans-2"
        )
        new_parts = {p.player_id: p for p in new_champ.participations.select_related("division")}
        self.assertEqual(new_parts[self.a[2].player_id].division.carryover_key, "d2")
        self.assertEqual(new_parts[self.b[0].player_id].division.carryover_key, "d1")
        self.assertEqual(new_parts[self.b[0].player_id].entry_origin, "PROMOTED_FROM")
        self.assertEqual(new_champ.previous_edition_id, self.championship.id)
        self.assertEqual(new_champ.settings.primary_tiebreak, self.championship.settings.primary_tiebreak)

        self.a[2].refresh_from_db()
        self.assertEqual(self.a[2].promotion_outcome, "RELEGATED")

    def test_double_proposal_blocked(self):
        propose_transition(championship=self.championship, created_by=self.admin)
        with self.assertRaises(ValidationError):
            propose_transition(championship=self.championship, created_by=self.admin)

    def test_double_confirmation_blocked(self):
        transition = propose_transition(championship=self.championship, created_by=self.admin)
        confirm_transition(transition=transition, confirmed_by=self.admin, new_name="X", new_season="trans-3")
        with self.assertRaises(ValidationError):
            confirm_transition(transition=transition, confirmed_by=self.admin, new_name="Y", new_season="trans-4")
