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
