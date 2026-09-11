"""Tests d'import CSV des joueurs (§60)."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from players.models import Player
from players.services import import_players_from_csv


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
