"""Tests du moteur de classement : points, départage, égalités, zones (§60)."""
from django.test import TestCase

from championships.models import PromotionRelegationRule
from competition.models import Match, Phase, TieResolution
from core.enums import ChampionshipStatus, MovementType, OutcomeType, PhaseKind, PromotionMethod, ResultStatus
from core.factories import make_championship, make_division, make_player, register
from rankings.services import championship_distinctions, compute_standings


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


class ChampionshipDistinctionsTests(TestCase):
    """Distinctions de fin de championnat (§ demande utilisateur : meilleure
    attaque/défense, plus large score) — toutes divisions confondues."""

    def setUp(self):
        self.championship = make_championship(name="Distinctions Championship", season="dist-1")
        self.division_a = make_division(self.championship, name="A", carryover_key="a")
        self.division_b = make_division(self.championship, name="B", level=2, carryover_key="b")
        self.phase_a = Phase.objects.create(
            championship=self.championship, division=self.division_a, kind=PhaseKind.LEAGUE, order=1, name="Ligue A"
        )
        self.phase_b = Phase.objects.create(
            championship=self.championship, division=self.division_b, kind=PhaseKind.LEAGUE, order=1, name="Ligue B"
        )
        self.attacker = register(self.championship, make_player("Attacker", "D"), self.division_a)
        self.weak = register(self.championship, make_player("Weak", "D"), self.division_a)
        self.weak2 = register(self.championship, make_player("Weak2", "D"), self.division_a)
        self.defender = register(self.championship, make_player("Defender", "D"), self.division_b)
        self.other = register(self.championship, make_player("Other", "D"), self.division_b)

        # Attacker marque énormément (attaque), Defender concède très peu (défense).
        _validated_match(self.championship, self.division_a, self.phase_a, self.attacker, self.weak, 600, 100)
        _validated_match(self.championship, self.division_a, self.phase_a, self.attacker, self.weak2, 550, 150)
        _validated_match(self.championship, self.division_b, self.phase_b, self.defender, self.other, 400, 50)

    def test_best_attack_ranks_by_average_not_total(self):
        distinctions = championship_distinctions(self.championship)
        self.assertEqual(distinctions["best_attack"][0]["participation"], self.attacker)
        self.assertEqual(distinctions["best_attack"][0]["average"], 575.0)

    def test_best_defense_lowest_average_conceded(self):
        distinctions = championship_distinctions(self.championship)
        self.assertEqual(distinctions["best_defense"][0]["participation"], self.defender)
        self.assertEqual(distinctions["best_defense"][0]["average"], 50.0)

    def test_biggest_margin_and_best_individual_score(self):
        distinctions = championship_distinctions(self.championship)
        self.assertEqual(distinctions["biggest_margins"][0]["margin"], 500)
        self.assertEqual(distinctions["best_individual_scores"][0]["score"], 600)
        self.assertEqual(distinctions["best_individual_scores"][0]["participation"], self.attacker)

    def test_closest_match(self):
        Match.objects.create(
            championship=self.championship, division=self.division_b, phase=self.phase_b,
            player1=self.defender, player2=self.other, leg=2, score1=300, score2=295,
            winner=self.defender, result_status=ResultStatus.VALIDATED, status="COMPLETED",
            counts_for_standings=True,
            pair_key=Match.compute_pair_key(self.defender.id, self.other.id),
        )
        distinctions = championship_distinctions(self.championship)
        self.assertEqual(distinctions["closest_matches"][0]["margin"], 5)

    def test_forfeits_are_excluded(self):
        forfeit = Match.objects.create(
            championship=self.championship, division=self.division_a, phase=self.phase_a,
            player1=self.weak, player2=self.attacker, leg=2, score1=0, score2=0,
            winner=self.attacker, outcome_type=OutcomeType.FORFEIT_P1,
            result_status=ResultStatus.VALIDATED, status="FORFEIT", counts_for_standings=True,
            pair_key=Match.compute_pair_key(self.weak.id, self.attacker.id),
        )
        distinctions = championship_distinctions(self.championship)
        # Le forfait (0-0) ne doit pas faire chuter la moyenne d'attaque de l'attaquant.
        self.assertEqual(distinctions["best_attack"][0]["average"], 575.0)
        self.assertNotIn(forfeit, [row["match"] for row in distinctions["biggest_margins"]])

    def test_matches_with_a_zero_score_are_excluded_even_without_forfeit_tag(self):
        # Un forfait mal saisi (outcome_type resté NORMAL) a souvent un score
        # à 0 d'un côté : on l'exclut quand même, par sécurité, même sans le
        # tag forfait (§ demande utilisateur : "ne pas considérer les scores
        # où l'un des score est nul").
        zero_score_match = Match.objects.create(
            championship=self.championship, division=self.division_a, phase=self.phase_a,
            player1=self.weak, player2=self.attacker, leg=2, score1=0, score2=250,
            winner=self.attacker, result_status=ResultStatus.VALIDATED, status="COMPLETED",
            counts_for_standings=True,
            pair_key=Match.compute_pair_key(self.weak.id, self.attacker.id),
        )
        distinctions = championship_distinctions(self.championship)
        self.assertEqual(distinctions["best_attack"][0]["average"], 575.0)
        self.assertNotIn(zero_score_match, [row["match"] for row in distinctions["biggest_margins"]])
        self.assertNotIn(zero_score_match, [row["match"] for row in distinctions["closest_matches"]])
        self.assertNotIn(250, [row["score"] for row in distinctions["best_individual_scores"] if row["participation"] == self.attacker and row["opponent"] == self.weak])

    def test_by_division_breakdown_is_scoped_to_each_division(self):
        distinctions = championship_distinctions(self.championship)
        by_division = {entry["division"].id: entry for entry in distinctions["by_division"]}
        self.assertEqual(set(by_division), {self.division_a.id, self.division_b.id})

        division_a_entry = by_division[self.division_a.id]
        self.assertEqual(division_a_entry["best_attack"][0]["participation"], self.attacker)
        self.assertEqual({r["participation"] for r in division_a_entry["best_attack"]}, {self.attacker, self.weak, self.weak2})

        division_b_entry = by_division[self.division_b.id]
        self.assertEqual(division_b_entry["best_attack"][0]["participation"], self.defender)
        self.assertEqual({r["participation"] for r in division_b_entry["best_attack"]}, {self.defender, self.other})

    def test_public_distinctions_view_accessible_without_login(self):
        self.championship.status = ChampionshipStatus.IN_PROGRESS
        self.championship.save(update_fields=["status"])
        resp = self.client.get(f"/classements/{self.championship.slug}/distinctions/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Attacker")
        self.assertContains(resp, "Defender")
