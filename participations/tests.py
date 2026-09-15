"""Tests d'inscription : capacité, doublons (§60)."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.factories import make_championship, make_division, make_player, register
from participations.models import ChampionshipParticipation
from participations.services import register_participation, withdraw_participation


class RegistrationTests(TestCase):
    def setUp(self):
        self.championship = make_championship(name="Registration Championship", season="reg-1")
        self.division = make_division(self.championship, capacity_max=2)
        self.p1 = make_player("A", "One")
        self.p2 = make_player("B", "Two")
        self.p3 = make_player("C", "Three")

    def test_register_success(self):
        participation = register_participation(
            championship=self.championship, player=self.p1, division=self.division
        )
        self.assertEqual(participation.division, self.division)

    def test_duplicate_registration_blocked(self):
        register_participation(championship=self.championship, player=self.p1, division=self.division)
        with self.assertRaises(ValidationError):
            register_participation(championship=self.championship, player=self.p1, division=self.division)

    def test_capacity_enforced(self):
        register_participation(championship=self.championship, player=self.p1, division=self.division)
        register_participation(championship=self.championship, player=self.p2, division=self.division)
        with self.assertRaises(ValidationError):
            register_participation(championship=self.championship, player=self.p3, division=self.division)

    def test_unlimited_division_bypasses_capacity(self):
        self.division.is_unlimited = True
        self.division.save()
        register_participation(championship=self.championship, player=self.p1, division=self.division)
        register_participation(championship=self.championship, player=self.p2, division=self.division)
        register_participation(championship=self.championship, player=self.p3, division=self.division)

    def test_db_unique_constraint_player_per_championship(self):
        register(self.championship, self.p1, self.division)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChampionshipParticipation.objects.create(
                    championship=self.championship, player=self.p1, division=self.division
                )

    def test_withdraw_frees_capacity(self):
        p = register_participation(championship=self.championship, player=self.p1, division=self.division)
        register_participation(championship=self.championship, player=self.p2, division=self.division)
        withdraw_participation(p)
        register_participation(championship=self.championship, player=self.p3, division=self.division)


class WithdrawParticipationTests(TestCase):
    """Retirer un joueur qui n'a joué aucun match doit effacer l'inscription
    (pas de fantôme « Retiré » éternel, et le joueur redevient supprimable) ;
    un joueur avec un historique de matchs réel garde son inscription,
    simplement marquée retirée (§ jamais perdre un historique réel)."""

    def setUp(self):
        from core.enums import PhaseKind
        from competition.models import Phase

        self.championship = make_championship(name="Withdraw Championship", season="wd-1")
        self.division = make_division(self.championship)
        self.phase = Phase.objects.create(
            championship=self.championship, division=self.division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )

    def test_withdraw_without_match_history_deletes_the_row(self):
        p = register_participation(
            championship=self.championship, player=make_player("A", "Wd"), division=self.division
        )
        result = withdraw_participation(p)
        self.assertIsNone(result)
        self.assertFalse(ChampionshipParticipation.objects.filter(pk=p.pk).exists())

    def test_withdraw_with_match_history_keeps_the_row_marked_withdrawn(self):
        from core.enums import ParticipationStatus
        from competition.models import Match

        p1 = register_participation(
            championship=self.championship, player=make_player("A", "Wd"), division=self.division
        )
        p2 = register_participation(
            championship=self.championship, player=make_player("B", "Wd"), division=self.division
        )
        Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=p1, player2=p2, pair_key=Match.compute_pair_key(p1.id, p2.id),
        )

        result = withdraw_participation(p1)

        self.assertIsNotNone(result)
        p1.refresh_from_db()
        self.assertEqual(p1.status, ParticipationStatus.WITHDRAWN)

    def test_withdrawing_only_participation_makes_player_deletable(self):
        from core.factories import make_user

        player = make_player("Free", "ToDelete")
        participation = register_participation(
            championship=self.championship, player=player, division=self.division
        )
        admin = make_user("withdraw_admin_t", group="Super Admin")
        self.client.force_login(admin)

        self.client.post(
            f"/gestion/championnats/{self.championship.slug}/joueurs/{participation.pk}/retirer/"
        )
        resp = self.client.post(f"/gestion/joueurs/{player.slug}/supprimer/")

        from players.models import Player

        self.assertRedirects(resp, "/gestion/joueurs/")
        self.assertFalse(Player.objects.filter(pk=player.pk).exists())
