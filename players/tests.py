"""Tests d'import CSV des joueurs (§60)."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.factories import make_user
from players.models import Player
from players.services import (
    create_player_login,
    import_players_from_csv,
    reset_player_login_password,
    suggest_username,
)


class CsvImportTests(TestCase):
    def test_valid_and_invalid_rows(self):
        content = (
            "prenom,nom,club,pays\n"
            "Carla,Rossi,Club Lyon,France\n"
            ",Sansnom,,\n"
            "Denis,Petit,,\n"
        )
        uploaded = SimpleUploadedFile("import.csv", content.encode("utf-8"))
        report = import_players_from_csv(uploaded)
        self.assertEqual(len(report.created), 2)
        self.assertEqual(len(report.skipped), 1)
        self.assertTrue(Player.objects.filter(first_name="Carla", last_name="Rossi").exists())

    def test_missing_required_columns_skips_everything(self):
        uploaded = SimpleUploadedFile("bad.csv", b"foo,bar\n1,2\n")
        report = import_players_from_csv(uploaded)
        self.assertEqual(len(report.created), 0)
        self.assertEqual(len(report.skipped), 1)


class ScrabbleGoIdVisibilityTests(TestCase):
    """L'identifiant ScrabbleGO doit être visible publiquement dans les
    classements (identifiant unique inter division)."""

    def test_appears_in_public_standings(self):
        from competition.models import Match, Phase
        from core.enums import ChampionshipStatus, PhaseKind, ResultStatus
        from core.factories import make_championship, make_division, register

        championship = make_championship(
            name="ScrabbleGo Championship", season="sgo-1", status=ChampionshipStatus.IN_PROGRESS
        )
        division = make_division(championship)
        phase = Phase.objects.create(
            championship=championship, division=division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        p1 = Player.objects.create(first_name="Alice", last_name="Sgo", scrabblego_id="alice_sg_42")
        p2 = Player.objects.create(first_name="Bob", last_name="Sgo")
        part1 = register(championship, p1, division)
        part2 = register(championship, p2, division)
        Match.objects.create(
            championship=championship, division=division, phase=phase, player1=part1, player2=part2,
            score1=400, score2=300, winner=part1, result_status=ResultStatus.VALIDATED,
            status="COMPLETED", counts_for_standings=True,
            pair_key=Match.compute_pair_key(part1.id, part2.id),
        )

        resp = self.client.get(f"/classements/{championship.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "alice_sg_42")


class PlayerLoginAccessTests(TestCase):
    """Un admin doit pouvoir créer/partager l'accès de connexion d'un joueur
    qui n'en a pas — sans quoi il n'a aucun moyen de le lui transmettre."""

    def setUp(self):
        self.admin = make_user("login_admin_t", group="Super Admin")
        self.player = Player.objects.create(first_name="Nadia", last_name="Access")

    def test_create_player_login_sets_password_and_links_user(self):
        user, password = create_player_login(
            self.player, username="nadia.access", email="nadia@example.invalid"
        )
        self.player.refresh_from_db()
        self.assertEqual(self.player.user_id, user.id)
        self.assertTrue(user.check_password(password))

    def test_cannot_create_login_twice(self):
        create_player_login(self.player, username="nadia.access", email="nadia@example.invalid")
        with self.assertRaises(ValidationError):
            create_player_login(self.player, username="another", email="other@example.invalid")

    def test_reset_requires_existing_account(self):
        with self.assertRaises(ValidationError):
            reset_player_login_password(self.player)

    def test_reset_changes_password(self):
        _, old_password = create_player_login(
            self.player, username="nadia.access", email="nadia@example.invalid"
        )
        new_password = reset_player_login_password(self.player)
        self.player.user.refresh_from_db()
        self.assertNotEqual(old_password, new_password)
        self.assertTrue(self.player.user.check_password(new_password))
        self.assertFalse(self.player.user.check_password(old_password))

    def test_suggest_username_avoids_collision(self):
        get_user_model().objects.create_user(username="nadia.access", password="x")
        suggested = suggest_username(self.player)
        self.assertNotEqual(suggested, "nadia.access")

    def test_view_creates_login_and_shows_credentials_once(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/gestion/joueurs/{self.player.slug}/creer-acces/",
            {"username": "nadia.access", "email": "nadia@example.invalid"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "nadia.access")
        self.player.refresh_from_db()
        self.assertIsNotNone(self.player.user_id)

    def test_view_requires_player_manager_permission(self):
        stranger = make_user("login_stranger_t")
        self.client.force_login(stranger)
        resp = self.client.get(f"/gestion/joueurs/{self.player.slug}/creer-acces/")
        self.assertEqual(resp.status_code, 403)


class PlayerDeleteTests(TestCase):
    """Un joueur créé par erreur doit pouvoir être supprimé — mais jamais un
    joueur déjà inscrit à un championnat (historique de matchs réel)."""

    def setUp(self):
        self.admin = make_user("del_player_admin_t", group="Super Admin")

    def test_unregistered_player_is_deleted(self):
        player = Player.objects.create(first_name="Léa", last_name="Suppr")
        self.client.force_login(self.admin)

        resp = self.client.post(f"/gestion/joueurs/{player.slug}/supprimer/")

        self.assertRedirects(resp, "/gestion/joueurs/")
        self.assertFalse(Player.objects.filter(pk=player.pk).exists())

    def test_deleting_player_also_removes_their_login(self):
        player = Player.objects.create(first_name="Léa", last_name="AvecCompte")
        user, _ = create_player_login(player, username="lea.avec", email="lea@example.invalid")
        self.client.force_login(self.admin)

        self.client.post(f"/gestion/joueurs/{player.slug}/supprimer/")

        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())

    def test_registered_player_cannot_be_deleted(self):
        from core.enums import ChampionshipStatus
        from core.factories import make_championship, make_division, register

        player = Player.objects.create(first_name="Léa", last_name="Inscrite")
        championship = make_championship(name="Del Player Championship", season="delp-1")
        division = make_division(championship)
        register(championship, player, division)
        self.client.force_login(self.admin)

        resp = self.client.post(f"/gestion/joueurs/{player.slug}/supprimer/")

        self.assertRedirects(resp, "/gestion/joueurs/")
        self.assertTrue(Player.objects.filter(pk=player.pk).exists())
