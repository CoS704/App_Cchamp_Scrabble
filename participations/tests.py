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

    def _two_players_with_match(self, **match_kwargs):
        from competition.models import Match

        p1 = register_participation(
            championship=self.championship, player=make_player("A", "Wd"), division=self.division
        )
        p2 = register_participation(
            championship=self.championship, player=make_player("B", "Wd"), division=self.division
        )
        match = Match.objects.create(
            championship=self.championship, division=self.division, phase=self.phase,
            player1=p1, player2=p2, pair_key=Match.compute_pair_key(p1.id, p2.id),
            **match_kwargs,
        )
        return p1, p2, match

    def test_withdraw_with_played_match_keeps_the_row_marked_withdrawn(self):
        from core.enums import ParticipationStatus, ResultStatus

        p1, p2, match = self._two_players_with_match(
            score1=400, score2=300, result_status=ResultStatus.VALIDATED,
            status="COMPLETED", counts_for_standings=True,
        )

        result = withdraw_participation(p1)

        self.assertIsNotNone(result)
        p1.refresh_from_db()
        self.assertEqual(p1.status, ParticipationStatus.WITHDRAWN)

    def test_withdraw_with_only_unplayed_scheduled_matches_removes_everything(self):
        """Régression : un calendrier généré mais vierge comptait comme un
        historique — le joueur restait « Retiré » à vie et introuvable dans le
        formulaire d'inscription (impossible de permuter deux joueurs)."""
        from competition.models import Match

        p1, p2, match = self._two_players_with_match()

        result = withdraw_participation(p1)

        self.assertIsNone(result)
        self.assertFalse(ChampionshipParticipation.objects.filter(pk=p1.pk).exists())
        self.assertFalse(Match.objects.filter(pk=match.pk).exists())
        self.assertTrue(ChampionshipParticipation.objects.filter(pk=p2.pk).exists())

    def test_withdrawn_player_is_offered_again_and_can_change_division(self):
        """Un joueur déjà retiré (ancienne ligne « Retiré » avec calendrier
        vierge) doit pouvoir être réinscrit dans une autre division."""
        from competition.models import Match
        from core.enums import ParticipationStatus
        from participations.forms import ParticipationForm

        p1, p2, match = self._two_players_with_match()
        p1.status = ParticipationStatus.WITHDRAWN
        p1.save()
        division2 = make_division(self.championship, name="D2", level=2, carryover_key="d2")

        form = ParticipationForm(championship=self.championship)
        self.assertIn(p1.player, form.fields["player"].queryset)

        result = register_participation(
            championship=self.championship, player=p1.player, division=division2
        )

        self.assertEqual(result.pk, p1.pk)
        self.assertEqual(result.division_id, division2.id)
        self.assertEqual(result.status, ParticipationStatus.REGISTERED)
        self.assertFalse(Match.objects.filter(pk=match.pk).exists())

    def test_withdrawn_player_with_played_matches_cannot_change_division(self):
        from core.enums import ParticipationStatus, ResultStatus

        p1, p2, match = self._two_players_with_match(
            score1=400, score2=300, result_status=ResultStatus.VALIDATED,
            status="COMPLETED", counts_for_standings=True,
        )
        p1.status = ParticipationStatus.WITHDRAWN
        p1.save()
        division2 = make_division(self.championship, name="D2", level=2, carryover_key="d2")

        with self.assertRaises(ValidationError):
            register_participation(
                championship=self.championship, player=p1.player, division=division2
            )

    def test_active_player_still_cannot_be_registered_twice(self):
        p1, p2, match = self._two_players_with_match()
        with self.assertRaises(ValidationError):
            register_participation(
                championship=self.championship, player=p1.player, division=self.division
            )

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
