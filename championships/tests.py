"""Tests championnats, divisions, règles de promotion/relégation (§60)."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from championships.models import Championship, Division, PromotionRelegationRule
from championships.services import regenerate_tiebreak_chain
from core.enums import ChampionshipStatus, MovementType, PrimaryTiebreak, PromotionMethod
from core.factories import make_championship, make_division, make_user


class ChampionshipInitializationTests(TestCase):
    def test_initialize_creates_settings_and_default_tiebreak_chain(self):
        championship = make_championship(name="Init Championship", season="init-1")
        self.assertTrue(hasattr(championship, "settings"))
        chain = list(championship.tiebreaks.order_by("position").values_list("criterion", flat=True))
        self.assertEqual(chain, ["SCORE_DIFF", "HEAD_TO_HEAD", "WINS", "MANUAL"])

    def test_regenerate_chain_on_head_to_head_primary(self):
        championship = make_championship(name="Init Championship 2", season="init-2")
        regenerate_tiebreak_chain(championship, PrimaryTiebreak.HEAD_TO_HEAD)
        chain = list(championship.tiebreaks.order_by("position").values_list("criterion", flat=True))
        self.assertEqual(chain[0], "HEAD_TO_HEAD")


class DivisionConstraintTests(TestCase):
    def test_capacity_min_must_not_exceed_capacity_max(self):
        championship = make_championship(name="Div Championship", season="div-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Division.objects.create(
                    championship=championship, name="D", level=1, carryover_key="d1",
                    capacity_min=10, capacity_max=5,
                )

    def test_unique_level_per_championship(self):
        championship = make_championship(name="Div Championship 2", season="div-2")
        make_division(championship, name="D1", level=1, carryover_key="d1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Division.objects.create(championship=championship, name="D1 bis", level=1, carryover_key="d1b")

    def test_registered_count_excludes_withdrawn(self):
        from core.enums import ParticipationStatus
        from core.factories import make_player, register

        championship = make_championship(name="Div Championship 3", season="div-3")
        division = make_division(championship)
        p1 = register(championship, make_player("A", "D"), division)
        register(championship, make_player("B", "D"), division)
        self.assertEqual(division.registered_count, 2)
        p1.status = ParticipationStatus.WITHDRAWN
        p1.save()
        self.assertEqual(division.registered_count, 1)


class PromotionRelegationRuleValidationTests(TestCase):
    def test_top_n_requires_value_n(self):
        championship = make_championship(name="Rule Championship", season="rule-1")
        d1 = make_division(championship, name="D1", level=1, carryover_key="d1")
        d2 = make_division(championship, name="D2", level=2, carryover_key="d2")
        rule = PromotionRelegationRule(
            championship=championship, movement_type=MovementType.PROMOTION,
            source_division=d2, target_division=d1, method=PromotionMethod.TOP_N,
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_rank_range_requires_min_and_max(self):
        championship = make_championship(name="Rule Championship 2", season="rule-2")
        d1 = make_division(championship, name="D1", level=1, carryover_key="d1")
        d2 = make_division(championship, name="D2", level=2, carryover_key="d2")
        rule = PromotionRelegationRule(
            championship=championship, movement_type=MovementType.RELEGATION,
            source_division=d1, target_division=d2, method=PromotionMethod.RANK_RANGE, rank_min=5,
        )
        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_source_and_target_must_differ_at_db_level(self):
        championship = make_championship(name="Rule Championship 3", season="rule-3")
        d1 = make_division(championship, name="D1", level=1, carryover_key="d1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PromotionRelegationRule.objects.create(
                    championship=championship, movement_type=MovementType.PROMOTION,
                    source_division=d1, target_division=d1, method=PromotionMethod.TOP_N, value_n=1,
                )


class ChampionshipDeleteTests(TestCase):
    """Un admin doit pouvoir supprimer un championnat créé par erreur — mais
    jamais une édition qui a réellement démarré (§ jamais perdre l'historique)."""

    def setUp(self):
        self.global_admin = make_user("del_champ_admin_t", group="Super Admin")

    def test_draft_championship_deleted_with_matching_name(self):
        championship = make_championship(name="Draft To Delete", season="del-1")
        self.client.force_login(self.global_admin)

        resp = self.client.post(
            f"/gestion/championnats/{championship.slug}/supprimer/",
            {"confirm_name": "Draft To Delete"},
        )

        self.assertRedirects(resp, "/gestion/championnats/")
        self.assertFalse(Championship.objects.filter(pk=championship.pk).exists())

    def test_mismatched_name_cancels_deletion(self):
        championship = make_championship(name="Draft Keep", season="del-2")
        self.client.force_login(self.global_admin)

        self.client.post(
            f"/gestion/championnats/{championship.slug}/supprimer/",
            {"confirm_name": "Wrong Name"},
        )

        self.assertTrue(Championship.objects.filter(pk=championship.pk).exists())

    def test_non_draft_championship_cannot_be_deleted(self):
        championship = make_championship(
            name="Live Championship", season="del-3", status=ChampionshipStatus.IN_PROGRESS
        )
        self.client.force_login(self.global_admin)

        self.client.post(
            f"/gestion/championnats/{championship.slug}/supprimer/",
            {"confirm_name": "Live Championship"},
        )

        self.assertTrue(Championship.objects.filter(pk=championship.pk).exists())

    def test_scoped_staff_admin_cannot_delete(self):
        from accounts.models import ChampionshipStaff

        championship = make_championship(name="Scoped Championship", season="del-4")
        staff_admin = make_user("del_champ_staff_t")
        ChampionshipStaff.objects.create(championship=championship, user=staff_admin, role="ADMIN")
        self.client.force_login(staff_admin)

        resp = self.client.get(f"/gestion/championnats/{championship.slug}/supprimer/")

        self.assertEqual(resp.status_code, 403)
