"""Tests des notifications d'administration (§40).

Avant ce correctif, seuls les joueurs étaient notifiés (litige, match en
retard) : un administrateur ne voyait donc jamais rien apparaître dans sa
cloche de notifications, quelle que soit la situation."""
from django.core import management
from django.test import TestCase

from accounts.models import ChampionshipStaff
from competition.models import Match, Phase
from competition.services.result import submit_result
from core.enums import PhaseKind
from core.factories import make_championship, make_division, make_player, make_user, register

from .models import Notification


class AdminDisputeNotificationTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Notif Championship", season="notif-1")
        self.division = make_division(self.championship)
        self.staff_admin = make_user("notif_staffadmin_t")
        ChampionshipStaff.objects.create(
            championship=self.championship, user=self.staff_admin, role="ADMIN"
        )
        self.global_admin = make_user("notif_globaladmin_t", group="Super Admin")
        self.user_a = make_user("notif_a_t")
        self.user_b = make_user("notif_b_t")
        player_a = make_player("A", "Notif", user=self.user_a)
        player_b = make_player("B", "Notif", user=self.user_b)
        self.part_a = register(self.championship, player_a, self.division)
        self.part_b = register(self.championship, player_b, self.division)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        self.match = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=self.part_a, player2=self.part_b,
        )

    def test_dispute_notifies_championship_admin_and_global_admin(self):
        submit_result(match=self.match, user=self.user_a, score1=450, score2=300, submitting_participation=self.part_a)
        submit_result(match=self.match, user=self.user_b, score1=420, score2=300, submitting_participation=self.part_b)

        admin_notif = Notification.objects.filter(
            recipient=self.staff_admin, kind="DISPUTE_TO_RESOLVE"
        )
        self.assertTrue(admin_notif.exists())
        self.assertIn(f"/gestion/championnats/{self.championship.slug}/calendrier/", admin_notif.first().link_url)

        self.assertTrue(
            Notification.objects.filter(recipient=self.global_admin, kind="DISPUTE_TO_RESOLVE").exists()
        )

    def test_referee_scoped_staff_is_not_notified(self):
        referee_user = make_user("notif_referee_t")
        ChampionshipStaff.objects.create(
            championship=self.championship, user=referee_user, role="REFEREE"
        )
        submit_result(match=self.match, user=self.user_a, score1=450, score2=300, submitting_participation=self.part_a)
        submit_result(match=self.match, user=self.user_b, score1=420, score2=300, submitting_participation=self.part_b)

        self.assertFalse(
            Notification.objects.filter(recipient=referee_user, kind="DISPUTE_TO_RESOLVE").exists()
        )

    def test_confirmed_result_does_not_spam_admin(self):
        submit_result(match=self.match, user=self.user_a, score1=450, score2=300, submitting_participation=self.part_a)
        submit_result(match=self.match, user=self.user_b, score1=450, score2=300, submitting_participation=self.part_b)

        self.assertFalse(
            Notification.objects.filter(recipient=self.staff_admin, kind="DISPUTE_TO_RESOLVE").exists()
        )


class LateMatchAdminNotificationTests(TestCase):
    def test_admin_is_notified_once_for_a_late_match(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.enums import ChampionshipStatus

        championship = make_championship(
            name="Late Notif Championship", season="latenotif-1", status=ChampionshipStatus.IN_PROGRESS
        )
        division = make_division(championship)
        staff_admin = make_user("late_notif_admin_t")
        ChampionshipStaff.objects.create(championship=championship, user=staff_admin, role="ADMIN")
        player_a = make_player("A", "Late")
        player_b = make_player("B", "Late")
        part_a = register(championship, player_a, division)
        part_b = register(championship, player_b, division)
        phase = Phase.objects.create(
            championship=championship, division=division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        Match.objects.create(
            championship=championship, division=division, phase=phase,
            player1=part_a, player2=part_b,
            scheduled_date=timezone.localdate() - timedelta(days=30),
        )

        management.call_command("check_late_matches")
        self.assertEqual(
            Notification.objects.filter(recipient=staff_admin, kind="MATCH_LATE_ADMIN").count(), 1
        )

        # Un second passage (cron régulier) ne doit pas dupliquer la notification.
        management.call_command("check_late_matches")
        self.assertEqual(
            Notification.objects.filter(recipient=staff_admin, kind="MATCH_LATE_ADMIN").count(), 1
        )
