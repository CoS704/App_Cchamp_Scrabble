"""Tests du dashboard « Mon espace » pour un compte sans profil joueur."""
from django.test import TestCase

from core.factories import make_championship, make_user


class PlayerDashboardOpponentScrabbleGoTests(TestCase):
    """Chaque joueur doit voir l'identifiant ScrabbleGO de son adversaire
    pour le prochain match (identifiant unique inter division)."""

    def test_next_match_opponent_scrabblego_id_is_shown(self):
        from competition.models import Match, Phase
        from core.enums import ChampionshipStatus, PhaseKind
        from core.factories import make_division, make_player, register

        championship = make_championship(
            name="Dash Sgo Championship", season="dsg-1", status=ChampionshipStatus.IN_PROGRESS
        )
        division = make_division(championship)
        phase = Phase.objects.create(
            championship=championship, division=division, kind=PhaseKind.LEAGUE, order=1, name="Ligue"
        )
        me_user = make_user("dsg_me_t")
        me = make_player("Me", "Dsg", user=me_user)
        opponent = make_player("Op", "Dsg", scrabblego_id="op_dsg_77")
        me_part = register(championship, me, division)
        opp_part = register(championship, opponent, division)
        Match.objects.create(
            championship=championship, division=division, phase=phase,
            player1=me_part, player2=opp_part,
        )
        self.client.force_login(me_user)

        resp = self.client.get("/mon-espace/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "op_dsg_77")


class PlayerDashboardFallbackTests(TestCase):
    """Un admin sans profil joueur doit voir ses championnats, pas une
    impasse lui demandant de contacter... un administrateur (lui-même)."""

    def test_global_admin_without_player_sees_managed_championships(self):
        admin = make_user("dash_admin_h", group="Super Admin")
        championship = make_championship(name="Dash Fallback Championship", season="dfh-1")
        self.client.force_login(admin)

        resp = self.client.get("/mon-espace/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dash Fallback Championship")
        self.assertNotContains(resp, "Contactez un administrateur")

    def test_plain_user_without_player_or_role_sees_contact_message(self):
        stranger = make_user("dash_stranger_h")
        self.client.force_login(stranger)

        resp = self.client.get("/mon-espace/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Contactez un administrateur")
