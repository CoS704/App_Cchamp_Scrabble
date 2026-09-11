"""Tests du moteur de classement : points, départage, égalités, zones (§60)."""
from django.test import TestCase

from championships.models import PromotionRelegationRule
from competition.models import Match, Phase, TieResolution
from core.enums import ChampionshipStatus, MovementType, PhaseKind, PromotionMethod, ResultStatus
from core.factories import make_championship, make_division, make_player, register
from rankings.services import compute_standings


def _validated_match(championship, division, phase, p1, p2, s1, s2):
    return Match.objects.create(
        championship=championship, division=division, phase=phase, player1=p1, player2=p2,
        score1=s1, score2=s2, winner=(p1 if s1 > s2 else (p2 if s2 > s1 else None)),
        result_status=ResultStatus.VALIDATED, status="COMPLETED", counts_for_standings=True,
        pair_key=Match.compute_pair_key(p1.id, p2.id),
    )


class RankingEngineTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Ranking Championship", season="rank-1")
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.px = register(self.championship, make_player("X", "R"), self.division)
        self.py = register(self.championship, make_player("Y", "R"), self.division)
        self.pz = register(self.championship, make_player("Z", "R"), self.division)

    def test_points_for_win_draw_loss(self):
        _validated_match(self.championship, self.division, self.phase, self.px, self.py, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.py, self.pz, 350, 350)
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        rows = {r.participation_id: r for r in snapshot.rows.all()}
        self.assertEqual(rows[self.px.id].points, 3)
        self.assertEqual(rows[self.py.id].points, 1)  # défaite (0) + nul (1)
        self.assertEqual(rows[self.pz.id].points, 1)

    def test_score_diff_then_head_to_head_tiebreak(self):
        # X bat Y / Y bat Z / Z bat X : tous à 3 pts, X et Z à égalité de
        # différence (-50) après Y (+100) -> départagés par confrontation directe.
        _validated_match(self.championship, self.division, self.phase, self.px, self.py, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.py, self.pz, 400, 200)
        _validated_match(self.championship, self.division, self.phase, self.pz, self.px, 400, 250)
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        order = list(snapshot.rows.order_by("rank").values_list("participation_id", flat=True))
        self.assertEqual(order, [self.py.id, self.pz.id, self.px.id])
        self.assertFalse(snapshot.has_unresolved_tie)

    def test_persistent_tie_is_flagged_not_invented(self):
        # Cycle parfaitement symétrique : aucun critère ne peut départager.
        _validated_match(self.championship, self.division, self.phase, self.px, self.py, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.py, self.pz, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.pz, self.px, 400, 300)
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        self.assertTrue(snapshot.has_unresolved_tie)
        tie_groups = {r.tie_group for r in snapshot.rows.all()}
        self.assertEqual(len(tie_groups), 1)
        self.assertNotIn(None, tie_groups)

    def test_tie_resolution_override_is_applied(self):
        _validated_match(self.championship, self.division, self.phase, self.px, self.py, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.py, self.pz, 400, 300)
        _validated_match(self.championship, self.division, self.phase, self.pz, self.px, 400, 300)
        resolution = TieResolution.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            ordered_result=[self.pz.id, self.px.id, self.py.id],
        )
        resolution.participations.set([self.px, self.py, self.pz])

        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        order = list(snapshot.rows.order_by("rank").values_list("participation_id", flat=True))
        self.assertEqual(order, [self.pz.id, self.px.id, self.py.id])
        self.assertFalse(snapshot.has_unresolved_tie)

    def test_disputed_match_excluded_from_standings(self):
        _validated_match(self.championship, self.division, self.phase, self.px, self.py, 400, 300)
        Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.py, player2=self.pz, leg=2, result_status=ResultStatus.DISPUTED,
            status="DISPUTED", counts_for_standings=False,
            pair_key=Match.compute_pair_key(self.py.id, self.pz.id),
        )
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        rows = {r.participation_id: r for r in snapshot.rows.all()}
        self.assertEqual(rows[self.pz.id].played, 0)


class MovementZoneTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Zone Championship", season="zone-1")
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.parts = [
            register(self.championship, make_player(f"P{i}", "M"), self.division) for i in range(4)
        ]
        p0, p1, p2, p3 = self.parts  # classement décisif souhaité : p0 > p1 > p2 > p3
        _validated_match(self.championship, self.division, self.phase, p0, p1, 500, 300)
        _validated_match(self.championship, self.division, self.phase, p0, p2, 500, 250)
        _validated_match(self.championship, self.division, self.phase, p0, p3, 500, 200)
        _validated_match(self.championship, self.division, self.phase, p1, p2, 450, 300)
        _validated_match(self.championship, self.division, self.phase, p1, p3, 450, 280)
        _validated_match(self.championship, self.division, self.phase, p2, p3, 400, 350)

    def test_top_n_and_bottom_n(self):
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.PROMOTION,
            source_division=self.division, target_division=None, method=PromotionMethod.TOP_N, value_n=1,
        )
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.RELEGATION,
            source_division=self.division, target_division=None, method=PromotionMethod.BOTTOM_N, value_n=1,
        )
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        rows = {r.participation_id: r for r in snapshot.rows.all()}
        self.assertEqual(rows[self.parts[0].id].movement_zone, "PROMOTION")
        self.assertEqual(rows[self.parts[3].id].movement_zone, "RELEGATION")
        self.assertEqual(rows[self.parts[1].id].movement_zone, "SAFE")

    def test_rank_range(self):
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.RELEGATION,
            source_division=self.division, target_division=None,
            method=PromotionMethod.RANK_RANGE, rank_min=3, rank_max=4,
        )
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        rows = {r.participation_id: r for r in snapshot.rows.all()}
        self.assertEqual(rows[self.parts[2].id].movement_zone, "RELEGATION")
        self.assertEqual(rows[self.parts[3].id].movement_zone, "RELEGATION")

    def test_top_percentage(self):
        PromotionRelegationRule.objects.create(
            championship=self.championship, movement_type=MovementType.PROMOTION,
            source_division=self.division, target_division=None,
            method=PromotionMethod.TOP_PERCENTAGE, percentage=25,
        )
        snapshot = compute_standings(championship=self.championship, division=self.division, phase=self.phase)
        rows = {r.participation_id: r for r in snapshot.rows.all()}
        self.assertEqual(rows[self.parts[0].id].movement_zone, "PROMOTION")


class PublicStandingsViewTests(TestCase):
    """Régression : les classements doivent être consultables par tout le
    monde, sans connexion (§32) — un import manquant avait cassé la page."""

    def setUp(self):
        self.championship = make_championship(
            name="Public Championship", season="pub-1", status=ChampionshipStatus.IN_PROGRESS
        )
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        p1 = register(self.championship, make_player("A", "Pub"), self.division)
        p2 = register(self.championship, make_player("B", "Pub"), self.division)
        _validated_match(self.championship, self.division, self.phase, p1, p2, 400, 300)

    def test_list_accessible_without_login(self):
        resp = self.client.get("/classements/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Public Championship")

    def test_detail_accessible_without_login_and_shows_ranking(self):
        resp = self.client.get(f"/classements/{self.championship.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "A Pub")

    def test_admin_standings_view_also_uses_shared_helper(self):
        from core.factories import make_user

        staff_user = make_user("pub_admin_h", group="Super Admin")
        self.client.force_login(staff_user)
        resp = self.client.get(f"/gestion/championnats/{self.championship.slug}/classement/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "A Pub")
