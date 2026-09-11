"""Tests de permissions et de sécurité (§39, §57, §60)."""
from django.test import TestCase

from accounts.models import ChampionshipStaff
from competition.models import Match, Phase
from core.enums import PhaseKind
from core.factories import make_championship, make_division, make_player, make_user, register
from core.permissions import (
    can_enter_result,
    can_manage_championship,
    can_referee,
    is_global_admin,
    is_super_admin,
)


class PermissionHelperTests(TestCase):
    def setUp(self):
        self.super_admin = make_user("super_h", group="Super Admin")
        self.global_admin = make_user("gadmin_h", group="Admin Championnat")
        self.plain = make_user("plain_h")
        self.championship = make_championship(name="Perm Championship", season="perm-1")

    def test_is_super_admin(self):
        self.assertTrue(is_super_admin(self.super_admin))
        self.assertFalse(is_super_admin(self.plain))

    def test_is_global_admin_includes_super_admin(self):
        self.assertTrue(is_global_admin(self.super_admin))
        self.assertTrue(is_global_admin(self.global_admin))
        self.assertFalse(is_global_admin(self.plain))

    def test_scoped_staff_admin_without_global_group(self):
        scoped_admin = make_user("scoped_admin_h")
        self.assertFalse(can_manage_championship(scoped_admin, self.championship))
        ChampionshipStaff.objects.create(championship=self.championship, user=scoped_admin, role="ADMIN")
        self.assertTrue(can_manage_championship(scoped_admin, self.championship))

    def test_anonymous_like_user_has_no_permissions(self):
        from django.contrib.auth.models import AnonymousUser

        anon = AnonymousUser()
        self.assertFalse(is_super_admin(anon))
        self.assertFalse(is_global_admin(anon))
        self.assertFalse(can_manage_championship(anon, self.championship))


class MatchResultSecurityTests(TestCase):
    """Un joueur ne doit jamais pouvoir agir sur le match d'un autre (§57)."""

    def setUp(self):
        self.championship = make_championship(name="Security Championship", season="sec-1")
        self.division = make_division(self.championship)
        self.user_a = make_user("resa_h")
        self.user_b = make_user("resb_h")
        self.stranger = make_user("stranger_h")
        self.player_a = make_player("A", "Test", user=self.user_a)
        self.player_b = make_player("B", "Test", user=self.user_b)
        self.part_a = register(self.championship, self.player_a, self.division)
        self.part_b = register(self.championship, self.player_b, self.division)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.match = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.part_a, player2=self.part_b,
        )

    def test_participants_can_enter_result(self):
        self.assertTrue(can_enter_result(self.user_a, self.match))
        self.assertTrue(can_enter_result(self.user_b, self.match))

    def test_stranger_cannot_enter_result(self):
        self.assertFalse(can_enter_result(self.stranger, self.match))

    def test_stranger_gets_403_on_result_page(self):
        self.client.force_login(self.stranger)
        resp = self.client.get(
            f"/gestion/championnats/{self.championship.slug}/calendrier/{self.match.pk}/resultat/"
        )
        self.assertEqual(resp.status_code, 403)

    def test_participant_can_access_own_match_result_page(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(
            f"/gestion/championnats/{self.championship.slug}/calendrier/{self.match.pk}/resultat/"
        )
        self.assertEqual(resp.status_code, 200)

    def test_anonymous_redirected_from_admin_dashboard(self):
        resp = self.client.get(f"/gestion/championnats/{self.championship.slug}/dashboard/")
        self.assertEqual(resp.status_code, 302)

    def test_plain_user_forbidden_on_admin_dashboard(self):
        self.client.force_login(self.stranger)
        resp = self.client.get(f"/gestion/championnats/{self.championship.slug}/dashboard/")
        self.assertEqual(resp.status_code, 403)

    def test_referee_scoped_to_their_division_only(self):
        other_division = make_division(self.championship, name="Autre", level=2, carryover_key="autre")
        referee = make_user("referee_scoped_h")
        staff = ChampionshipStaff.objects.create(championship=self.championship, user=referee, role="REFEREE")
        staff.divisions.add(other_division)  # cadré sur une AUTRE division que celle du match
        self.assertFalse(can_referee(referee, self.championship, self.division))
        self.assertTrue(can_referee(referee, self.championship, other_division))

    def test_unscoped_referee_covers_all_divisions(self):
        other_division = make_division(self.championship, name="Autre2", level=3, carryover_key="autre2")
        referee = make_user("referee_unscoped_h")
        ChampionshipStaff.objects.create(championship=self.championship, user=referee, role="REFEREE")
        self.assertTrue(can_referee(referee, self.championship, self.division))
        self.assertTrue(can_referee(referee, self.championship, other_division))
