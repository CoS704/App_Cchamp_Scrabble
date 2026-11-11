"""Tests des formats de compétition : coupe du monde (groupes + élimination),
élimination directe avec exempts, système suisse."""
import random

from django.core.exceptions import ValidationError
from django.test import TestCase

from championships.forms import ChampionshipSettingsForm
from competition.models import Match, Matchday, Phase
from competition.services.result import submit_result
from competition.services.scheduling import draw_groups, format_plan, generate_group_stage, generate_schedule
from competition.services.swiss import generate_next_swiss_round, swiss_rounds_total, swiss_status
from core.enums import (
    ChampionshipStatus, CompetitionFormat, MatchStatus, MovementZone, OutcomeType, PhaseKind, ResultStatus,
)
from core.factories import make_championship, make_division, make_player, make_user, register
from finals.models import BracketSlot
from finals.services import generate_bracket
from rankings.services import all_divisions_standings, compute_standings


def _setup(fmt, n_players, *, name="Format", seeded=False, **settings_changes):
    championship = make_championship(name=name, season=f"{fmt.lower()}-{n_players}",
                                     status=ChampionshipStatus.IN_PROGRESS)
    s = championship.settings
    s.competition_format = fmt
    for key, value in settings_changes.items():
        setattr(s, key, value)
    s.save()
    division = make_division(championship)
    players = [
        register(championship, make_player(f"J{i:02d}", "T"), division, seed=(i + 1) if seeded else None)
        for i in range(n_players)
    ]
    return championship, division, players


def _play_all(championship, admin, phase_qs, *, favour_lower_index=True):
    """Joue chaque match en donnant la victoire au joueur d'id le plus bas."""
    for match in phase_qs.exclude(status__in=[MatchStatus.COMPLETED, MatchStatus.FORFEIT]):
        if match.player2_id is None:
            continue
        low_wins = match.player1_id < match.player2_id
        s1, s2 = (400, 300) if low_wins == favour_lower_index else (300, 400)
        submit_result(match=match, user=admin, score1=s1, score2=s2)


class GroupDrawTests(TestCase):
    def _players(self, n, seeded=False):
        championship = make_championship(name="Draw", season=f"draw-{n}-{seeded}")
        division = make_division(championship)
        return [
            register(championship, make_player(f"D{i:02d}", "X"), division, seed=(i + 1) if seeded else None)
            for i in range(n)
        ]

    def test_every_player_is_in_exactly_one_group_and_sizes_are_balanced(self):
        players = self._players(14)
        groups = draw_groups(players, 4, random.Random(1))
        self.assertEqual(sorted(p.id for g in groups for p in g), sorted(p.id for p in players))
        self.assertLessEqual(max(map(len, groups)) - min(map(len, groups)), 1)

    def test_same_seed_gives_same_draw(self):
        players = self._players(12)
        a = [[p.id for p in g] for g in draw_groups(players, 4, random.Random(42))]
        b = [[p.id for p in g] for g in draw_groups(players, 4, random.Random(42))]
        self.assertEqual(a, b)

    def test_top_seeds_never_share_a_group(self):
        players = self._players(16, seeded=True)
        for seed in range(20):
            groups = draw_groups(players, 4, random.Random(seed))
            for group in groups:
                self.assertEqual(sum(1 for p in group if p.seed <= 4), 1)


class GroupStageTests(TestCase):
    def setUp(self):
        self.championship, self.division, self.players = _setup(
            CompetitionFormat.GROUPS_KNOCKOUT, 8, groups_count=2, group_qualifiers=2, finals_third_place=True,
        )
        self.admin = make_user("grp_admin", group="Super Admin")

    def test_generate_schedule_creates_one_group_phase_per_group(self):
        matches = generate_schedule(championship=self.championship, division=self.division)
        phases = Phase.objects.filter(division=self.division, kind=PhaseKind.GROUP).order_by("order")
        self.assertEqual([p.name for p in phases], ["Groupe A", "Groupe B"])
        self.assertEqual(len(matches), 12)  # 2 groupes de 4 : 6 matchs chacun
        for phase in phases:
            self.assertEqual(phase.participants.count(), 4)
            self.assertEqual(Match.objects.filter(phase=phase).count(), 6)
            members = set(phase.participants.values_list("id", flat=True))
            for m in Match.objects.filter(phase=phase):
                self.assertIn(m.player1_id, members)
                self.assertIn(m.player2_id, members)

    def test_not_enough_players_is_refused(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 3, groups_count=2,
                                          name="Small")
        with self.assertRaises(ValidationError):
            generate_schedule(championship=championship, division=division)

    def test_redraw_requires_force_and_no_validated_result(self):
        generate_schedule(championship=self.championship, division=self.division)
        with self.assertRaises(ValidationError):
            generate_schedule(championship=self.championship, division=self.division)
        generate_schedule(championship=self.championship, division=self.division, force=True)
        self.assertEqual(Phase.objects.filter(division=self.division, kind=PhaseKind.GROUP).count(), 2)

        match = Match.objects.filter(division=self.division).first()
        submit_result(match=match, user=self.admin, score1=400, score2=300)
        with self.assertRaises(ValidationError):
            generate_schedule(championship=self.championship, division=self.division, force=True)

    def test_standings_are_per_group_and_mark_qualifiers(self):
        generate_schedule(championship=self.championship, division=self.division)
        _play_all(self.championship, self.admin, Match.objects.filter(division=self.division))
        entries = all_divisions_standings(self.championship)
        self.assertEqual([e["label"] for e in entries], [
            f"{self.division.name} — Groupe A", f"{self.division.name} — Groupe B"])
        for entry in entries:
            rows = list(entry["rows"])
            self.assertEqual(len(rows), 4)
            self.assertEqual([r.movement_zone for r in rows[:2]], [MovementZone.FINALS] * 2)
            self.assertNotEqual(rows[2].movement_zone, MovementZone.FINALS)

    def test_bracket_waits_for_groups_to_finish(self):
        generate_schedule(championship=self.championship, division=self.division)
        with self.assertRaises(ValidationError):
            generate_bracket(championship=self.championship, division=self.division)

    def test_world_cup_cross_pairing_avoids_same_group_in_first_round(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 16, groups_count=4,
                                          group_qualifiers=2, name="WC")
        generate_schedule(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(division=division))
        bracket = generate_bracket(championship=championship, division=division)

        self.assertEqual(bracket.size, 8)
        group_of = {}
        for phase in Phase.objects.filter(division=division, kind=PhaseKind.GROUP):
            for pid in phase.participants.values_list("id", flat=True):
                group_of[pid] = phase.name
        first_round = Match.objects.filter(bracket_slots__bracket=bracket, bracket_slots__round_index=0).distinct()
        self.assertEqual(first_round.count(), 4)
        for m in first_round:
            self.assertNotEqual(group_of[m.player1_id], group_of[m.player2_id])
        # chaque groupe a exactement deux qualifiés
        qualified = BracketSlot.objects.filter(bracket=bracket, round_index=0).values_list("participation_id", flat=True)
        counts = {}
        for pid in qualified:
            counts[group_of[pid]] = counts.get(group_of[pid], 0) + 1
        self.assertEqual(sorted(counts.values()), [2, 2, 2, 2])

    def test_group_winner_meets_runner_up_of_the_paired_group(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 8, groups_count=2,
                                          group_qualifiers=2, name="WC2")
        generate_schedule(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(division=division))
        phases = list(Phase.objects.filter(division=division, kind=PhaseKind.GROUP).order_by("order"))
        ranked = {}
        for phase in phases:
            snap = compute_standings(championship=championship, division=division, phase=phase)
            ranked[phase.name] = [r.participation_id for r in snap.rows.order_by("rank")]
        bracket = generate_bracket(championship=championship, division=division)
        pairs = {frozenset((m.player1_id, m.player2_id))
                 for m in Match.objects.filter(bracket_slots__bracket=bracket, bracket_slots__round_index=0)}
        self.assertEqual(pairs, {
            frozenset((ranked["Groupe A"][0], ranked["Groupe B"][1])),
            frozenset((ranked["Groupe B"][0], ranked["Groupe A"][1])),
        })

    def test_wildcards_take_the_best_next_ranked(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 12, groups_count=3,
                                          group_qualifiers=1, group_wildcards=1, name="WCW")
        generate_schedule(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(division=division))
        bracket = generate_bracket(championship=championship, division=division)
        self.assertEqual(bracket.size, 4)
        self.assertEqual(
            BracketSlot.objects.filter(bracket=bracket, round_index=0, participation__isnull=False).count(), 4)

    def test_knockout_match_cannot_end_in_a_draw(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 8, groups_count=2,
                                          group_qualifiers=2, name="Draw KO")
        generate_schedule(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(division=division))
        bracket = generate_bracket(championship=championship, division=division)
        ko_match = Match.objects.filter(bracket_slots__bracket=bracket).first()
        with self.assertRaises(ValidationError):
            submit_result(match=ko_match, user=self.admin, score1=350, score2=350)

    def test_draws_remain_allowed_in_groups(self):
        generate_schedule(championship=self.championship, division=self.division)
        match = Match.objects.filter(division=self.division).first()
        submit_result(match=match, user=self.admin, score1=350, score2=350)
        match.refresh_from_db()
        self.assertEqual(match.result_status, ResultStatus.VALIDATED)


class KnockoutFormatTests(TestCase):
    def setUp(self):
        self.admin = make_user("ko_admin", group="Super Admin")

    def test_no_calendar_for_pure_knockout(self):
        championship, division, _ = _setup(CompetitionFormat.KNOCKOUT, 6)
        with self.assertRaises(ValidationError):
            generate_schedule(championship=championship, division=division)

    def test_byes_go_to_top_seeds_and_advance_automatically(self):
        championship, division, players = _setup(CompetitionFormat.KNOCKOUT, 6, seeded=True,
                                                 finals_third_place=False)
        bracket = generate_bracket(championship=championship, division=division)
        self.assertEqual(bracket.size, 8)
        first = Match.objects.filter(bracket_slots__bracket=bracket, bracket_slots__round_index=0).distinct()
        self.assertEqual(first.count(), 2)  # 8 places, 6 joueurs : 2 vrais matchs
        round1 = BracketSlot.objects.filter(bracket=bracket, round_index=1, is_third_place=False)
        advanced = {s.participation_id for s in round1 if s.participation_id}
        self.assertEqual(advanced, {players[0].id, players[1].id})  # têtes de série 1 et 2

    def test_full_knockout_produces_a_champion(self):
        championship, division, players = _setup(CompetitionFormat.KNOCKOUT, 5, seeded=True,
                                                 finals_third_place=False)
        bracket = generate_bracket(championship=championship, division=division)
        for _ in range(4):
            _play_all(championship, self.admin, Match.objects.filter(bracket_slots__bracket=bracket).distinct())
        final_slot = BracketSlot.objects.filter(bracket=bracket, round_index=2).first()
        self.assertIsNotNone(final_slot.match)
        self.assertEqual(final_slot.match.result_status, ResultStatus.VALIDATED)
        self.assertIsNotNone(final_slot.match.winner_id)

    def test_cannot_generate_twice(self):
        championship, division, _ = _setup(CompetitionFormat.KNOCKOUT, 4)
        generate_bracket(championship=championship, division=division)
        with self.assertRaises(ValidationError):
            generate_bracket(championship=championship, division=division)

    def test_plan_summary(self):
        championship, _division, _ = _setup(CompetitionFormat.KNOCKOUT, 6)
        plan = format_plan(championship.settings, 6)
        self.assertEqual(plan["matches"], 5)
        self.assertIn("8 places", plan["summary"])


class SwissTests(TestCase):
    def setUp(self):
        self.admin = make_user("swiss_admin", group="Super Admin")

    def _start(self, n, **extra):
        championship, division, players = _setup(CompetitionFormat.SWISS, n, seeded=True, **extra)
        generate_schedule(championship=championship, division=division)
        return championship, division, players

    def test_first_round_pairs_top_half_against_bottom_half(self):
        championship, division, players = self._start(8)
        pairs = {frozenset((m.player1_id, m.player2_id)) for m in Match.objects.filter(division=division)}
        self.assertEqual(pairs, {frozenset((players[i].id, players[i + 4].id)) for i in range(4)})

    def test_odd_field_gives_a_bye_counted_as_a_win(self):
        championship, division, players = self._start(5)
        bye = Match.objects.get(division=division, player2__isnull=True)
        self.assertEqual(bye.outcome_type, OutcomeType.BYE)
        self.assertEqual(bye.player1_id, players[-1].id)  # le moins bien classé
        snapshot = compute_standings(championship=championship, division=division,
                                     phase=Phase.objects.get(division=division, kind=PhaseKind.SWISS))
        row = snapshot.rows.get(participation=players[-1])
        self.assertEqual((row.wins, row.points), (1, championship.settings.points_win))

    def test_next_round_requires_previous_round_to_be_finished(self):
        championship, division, _ = self._start(6)
        with self.assertRaises(ValidationError):
            generate_next_swiss_round(championship=championship, division=division)

    def test_no_rematch_and_every_round_is_generated(self):
        championship, division, _ = self._start(8)
        phase = Phase.objects.get(division=division, kind=PhaseKind.SWISS)
        total = swiss_rounds_total(championship.settings, 8)
        self.assertEqual(total, 3)
        for _ in range(total - 1):
            _play_all(championship, self.admin, Match.objects.filter(phase=phase))
            generate_next_swiss_round(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(phase=phase))

        pairs = [frozenset((m.player1_id, m.player2_id)) for m in Match.objects.filter(phase=phase)]
        self.assertEqual(len(pairs), len(set(pairs)))  # aucune revanche
        self.assertEqual(Matchday.objects.filter(phase=phase).count(), total)
        status = swiss_status(championship, division)
        self.assertTrue(status["finished"])
        with self.assertRaises(ValidationError):
            generate_next_swiss_round(championship=championship, division=division)

    def test_byes_rotate_between_players(self):
        championship, division, _ = self._start(5, swiss_rounds=4)
        phase = Phase.objects.get(division=division, kind=PhaseKind.SWISS)
        for _ in range(3):
            _play_all(championship, self.admin, Match.objects.filter(phase=phase))
            generate_next_swiss_round(championship=championship, division=division)
        byes = list(Match.objects.filter(phase=phase, player2__isnull=True).values_list("player1_id", flat=True))
        self.assertEqual(len(byes), 4)
        self.assertEqual(len(set(byes)), 4)

    def test_rounds_never_exceed_possible_opponents(self):
        self.assertEqual(swiss_rounds_total(type("S", (), {"swiss_rounds": 10})(), 4), 3)

    def test_swiss_top_cut_feeds_a_bracket(self):
        championship, division, _ = self._start(8, finals_enabled=True, finals_qualifiers_count=4)
        phase = Phase.objects.get(division=division, kind=PhaseKind.SWISS)
        for _ in range(2):
            _play_all(championship, self.admin, Match.objects.filter(phase=phase))
            generate_next_swiss_round(championship=championship, division=division)
        _play_all(championship, self.admin, Match.objects.filter(phase=phase))
        snapshot = compute_standings(championship=championship, division=division, phase=phase)
        if snapshot.has_unresolved_tie:
            self.skipTest("égalité non résolue dans ce tirage")
        bracket = generate_bracket(championship=championship, division=division)
        self.assertEqual(bracket.size, 4)


class FormatSettingsFormTests(TestCase):
    def _data(self, championship, **overrides):
        s = championship.settings
        data = {
            "points_win": s.points_win, "points_draw": s.points_draw, "points_loss": s.points_loss,
            "points_forfeit_win": s.points_forfeit_win, "points_forfeit_loss": s.points_forfeit_loss,
            "forfeit_score_for": 0, "forfeit_score_against": 0, "primary_tiebreak": s.primary_tiebreak,
            "competition_format": s.competition_format, "groups_count": 4, "group_qualifiers": 2,
            "group_wildcards": 0, "round_robin_legs": 1, "result_entry_policy": s.result_entry_policy,
            "late_match_threshold_days": 0, "upcoming_matches_shown": 2,
            "finals_qualifiers_count": 4, "finals_format": s.finals_format,
        }
        data.update(overrides)
        return data

    def test_format_locked_once_matches_exist(self):
        championship, division, _ = _setup(CompetitionFormat.LEAGUE, 4, name="Locked")
        generate_schedule(championship=championship, division=division)
        form = ChampionshipSettingsForm(
            self._data(championship, competition_format=CompetitionFormat.SWISS), instance=championship.settings)
        self.assertFalse(form.is_valid())
        self.assertIn("competition_format", form.errors)

    def test_format_can_change_before_any_match(self):
        championship, _division, _ = _setup(CompetitionFormat.LEAGUE, 4, name="Free")
        form = ChampionshipSettingsForm(
            self._data(championship, competition_format=CompetitionFormat.SWISS), instance=championship.settings)
        self.assertTrue(form.is_valid(), form.errors)

    def test_more_wildcards_than_groups_is_refused(self):
        championship, _division, _ = _setup(CompetitionFormat.LEAGUE, 4, name="Wild")
        form = ChampionshipSettingsForm(
            self._data(championship, competition_format=CompetitionFormat.GROUPS_KNOCKOUT,
                       groups_count=2, group_wildcards=3), instance=championship.settings)
        self.assertFalse(form.is_valid())
        self.assertIn("group_wildcards", form.errors)


class FormatScreensTests(TestCase):
    """Les écrans d'administration et publics s'affichent pour chaque format."""

    def setUp(self):
        self.admin = make_user("screens_admin", group="Super Admin")
        self.client.force_login(self.admin)

    def _urls(self, championship, division):
        slug = championship.slug
        return [
            f"/gestion/championnats/{slug}/calendrier/",
            f"/gestion/championnats/{slug}/calendrier/generer/{division.pk}/",
            f"/gestion/championnats/{slug}/classement/",
            f"/gestion/championnats/{slug}/finales/",
            f"/gestion/championnats/{slug}/dashboard/",
            f"/classements/{slug}/",
        ]

    def test_screens_render_for_every_format_before_and_after_generation(self):
        for fmt in CompetitionFormat.values:
            with self.subTest(fmt=fmt):
                championship, division, _ = _setup(fmt, 8, groups_count=2, name=f"Screens {fmt}")
                for url in self._urls(championship, division):
                    resp = self.client.get(url, follow=True)
                    self.assertEqual(resp.status_code, 200, url)
                if fmt == CompetitionFormat.KNOCKOUT:
                    self.client.post(f"/gestion/championnats/{championship.slug}/finales/generer/{division.pk}/")
                else:
                    self.client.post(
                        f"/gestion/championnats/{championship.slug}/calendrier/generer/{division.pk}/",
                        {"interval_days": 7},
                    )
                self.assertTrue(Match.objects.filter(division=division).exists(), fmt)
                for url in self._urls(championship, division):
                    resp = self.client.get(url, follow=True)
                    self.assertEqual(resp.status_code, 200, url)

    def test_swiss_next_round_button_flow(self):
        championship, division, _ = _setup(CompetitionFormat.SWISS, 6, name="Swiss UI")
        generate_schedule(championship=championship, division=division)
        url = f"/gestion/championnats/{championship.slug}/calendrier/ronde-suivante/{division.pk}/"
        self.client.post(url)  # ronde 1 pas finie : refusé
        self.assertEqual(Matchday.objects.filter(phase__division=division).count(), 1)
        _play_all(championship, self.admin, Match.objects.filter(division=division))
        self.client.post(url)
        self.assertEqual(Matchday.objects.filter(phase__division=division).count(), 2)

    def test_public_standings_show_one_table_per_group(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 8, groups_count=2, name="Pub groups")
        generate_schedule(championship=championship, division=division)
        self.client.logout()
        resp = self.client.get(f"/classements/{championship.slug}/")
        self.assertContains(resp, "Groupe A")
        self.assertContains(resp, "Groupe B")

    def test_player_dashboard_and_simulation_work_in_a_group(self):
        championship, division, _ = _setup(CompetitionFormat.GROUPS_KNOCKOUT, 8, groups_count=2,
                                           name="Dash groups")
        user = make_user("grp_player")
        member = register(championship, make_player("Joueur", "Connecté", user=user), division)
        # 9 joueurs → groupes de 5 et 4
        generate_schedule(championship=championship, division=division)
        self.client.force_login(user)
        resp = self.client.get("/mon-espace/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/mon-espace/simulation/")
        self.assertEqual(resp.status_code, 200)

        from dashboard.services import admin_dashboard_context

        context = admin_dashboard_context(championship)
        self.assertIsNotNone(context)
