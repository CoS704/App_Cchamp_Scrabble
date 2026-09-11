"""Tests du profil compte : auto-édition de l'identifiant ScrabbleGO."""
from django.test import TestCase

from core.factories import make_player, make_user


class ScrabbleGoSelfEditTests(TestCase):
    def test_player_can_set_own_scrabblego_id(self):
        user = make_user("sgo_profile_t")
        player = make_player("Sam", "Profile", user=user)
        self.client.force_login(user)

        resp = self.client.post("/accounts/profil/", {"scrabblego_id": "sam_profile_99"})

        self.assertRedirects(resp, "/accounts/profil/")
        player.refresh_from_db()
        self.assertEqual(player.scrabblego_id, "sam_profile_99")

    def test_account_without_player_profile_is_unaffected(self):
        user = make_user("sgo_no_player_t")
        self.client.force_login(user)

        resp = self.client.get("/accounts/profil/")

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Identifiant ScrabbleGO")
