"""Génère un jeu de données de démonstration complet (§59).

    python manage.py seed_demo            # crée (ou complète) les données
    python manage.py seed_demo --reset    # supprime l'édition de démo existante d'abord

Ne jamais exécuter en production avec des identifiants réels : les comptes
créés ici utilisent un mot de passe de démonstration fixe, documenté dans le
README, destiné au développement local uniquement.
"""
from __future__ import annotations

import random
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import ChampionshipStaff, User
from championships import services as championship_services
from championships.models import Championship, Division, PromotionRelegationRule
from competition.models import Match
from competition.services.match import declare_forfeit
from competition.services.result import submit_result
from competition.services.scheduling import generate_schedule
from core.enums import ChampionshipStatus, MovementType, ParticipationStatus, PromotionMethod
from participations.models import ChampionshipParticipation
from players.models import Player

DEMO_SEASON = "2026-demo"
DEMO_PASSWORD = "Demo-Pass-1234"
DEMO_MARKER = "__seed_demo__"

FIRST_NAMES = [
    "Bastien", "Camille", "David", "Elise", "Farid", "Gaelle", "Hugo", "Ines",
    "Julien", "Karim", "Laura", "Mathieu", "Nora", "Omar", "Pauline", "Quentin",
    "Rania", "Simon", "Theo", "Valentine", "William", "Yasmine", "Zoe",
]
LAST_NAMES = [
    "Bernard", "Petit", "Robert", "Richard", "Durand", "Dubois", "Moreau",
    "Laurent", "Simon", "Michel", "Lefebvre", "Leroy", "Roux", "David", "Bertrand",
]


class Command(BaseCommand):
    help = "Crée un championnat de démonstration complet : joueurs, calendrier, résultats, litiges, forfaits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Supprime l'édition de démonstration existante avant de la régénérer.",
        )

    def handle(self, *args, **options):
        random.seed(42)  # jeu de données reproductible d'un run à l'autre

        if options["reset"]:
            self._reset()

        if Championship.objects.filter(season=DEMO_SEASON).exists():
            self.stdout.write(self.style.WARNING(
                "Une édition de démonstration existe déjà. Utilisez --reset pour la régénérer."
            ))
            return

        with transaction.atomic():
            users = self._create_demo_users()
            players = self._create_players(users)
            championship = self._create_championship()
            d1, d2 = self._create_divisions(championship)
            self._create_movement_rules(championship, d1, d2)
            self._register_players(championship, players, d1, d2)
            self._assign_staff(championship, users)
            self._generate_and_play(championship, d1, users)
            self._generate_and_play(championship, d2, users)

        self._print_summary(championship)

    # --- Nettoyage -----------------------------------------------------
    def _reset(self):
        for championship in Championship.objects.filter(season=DEMO_SEASON):
            Match.objects.filter(championship=championship).delete()
            PromotionRelegationRule.objects.filter(championship=championship).delete()
            ChampionshipParticipation.objects.filter(championship=championship).delete()
            championship.delete()
        Player.objects.filter(bio=DEMO_MARKER).delete()
        User.objects.filter(username__startswith="demo_").delete()
        self.stdout.write("Anciennes données de démonstration supprimées.")

    # --- Comptes & joueurs -----------------------------------------------
    def _create_demo_users(self):
        for name in ("Super Admin", "Admin Championnat", "Arbitre"):
            Group.objects.get_or_create(name=name)

        def get_or_create_user(username, first_name, last_name, **extra):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.local",
                    "first_name": first_name,
                    "last_name": last_name,
                    **extra,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            return user

        admin = get_or_create_user("demo_admin", "Admin", "Démo", is_staff=True)
        admin.groups.add(Group.objects.get(name="Super Admin"))
        referee = get_or_create_user("demo_arbitre", "Arbitre", "Démo")
        player1 = get_or_create_user("demo_joueur1", "Alice", "Bernard")
        player2 = get_or_create_user("demo_joueur2", "Bastien", "Petit")
        return {"admin": admin, "referee": referee, "player1": player1, "player2": player2}

    def _create_players(self, users):
        players = [
            Player.objects.create(
                first_name="Alice", last_name="Bernard", user=users["player1"], bio=DEMO_MARKER
            ),
        ]
        used = {("Alice", "Bernard")}
        # Bastien Petit est déjà dans FIRST_NAMES/LAST_NAMES : on le crée à part
        # pour le lier au compte demo_joueur2, puis on l'exclut du tirage.
        players.append(
            Player.objects.create(
                first_name="Bastien", last_name="Petit", user=users["player2"], bio=DEMO_MARKER
            )
        )
        used.add(("Bastien", "Petit"))

        while len(players) < 20:
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            if (first, last) in used:
                continue
            used.add((first, last))
            players.append(Player.objects.create(first_name=first, last_name=last, bio=DEMO_MARKER))
        return players

    # --- Championnat -----------------------------------------------------
    def _create_championship(self):
        championship = Championship.objects.create(
            name="Championnat de Scrabble Démo 2026",
            season=DEMO_SEASON,
            description="Édition de démonstration générée par `manage.py seed_demo`.",
            status=ChampionshipStatus.IN_PROGRESS,
            is_inaugural=True,
        )
        championship_services.initialize_championship(championship)
        championship.settings.finals_enabled = True
        championship.settings.finals_qualifiers_count = 4
        championship.settings.save()
        return championship

    def _create_divisions(self, championship):
        d1 = Division.objects.create(
            championship=championship, name="Division 1", level=1, carryover_key="d1",
            capacity_max=10, color="#0d6efd", description="Division d'élite.",
        )
        d2 = Division.objects.create(
            championship=championship, name="Division 2", level=2, carryover_key="d2",
            capacity_max=50, color="#6c757d", description="Division d'accession.",
        )
        return d1, d2

    def _create_movement_rules(self, championship, d1, d2):
        PromotionRelegationRule.objects.create(
            championship=championship, movement_type=MovementType.PROMOTION,
            source_division=d2, target_division=d1, method=PromotionMethod.TOP_N, value_n=2,
        )
        PromotionRelegationRule.objects.create(
            championship=championship, movement_type=MovementType.RELEGATION,
            source_division=d1, target_division=d2, method=PromotionMethod.BOTTOM_N, value_n=2,
        )

    def _register_players(self, championship, players, d1, d2):
        for i, player in enumerate(players[:8]):
            ChampionshipParticipation.objects.create(
                championship=championship, player=player, division=d1, seed=i + 1,
                status=ParticipationStatus.REGISTERED,
            )
        for i, player in enumerate(players[8:]):
            ChampionshipParticipation.objects.create(
                championship=championship, player=player, division=d2, seed=i + 1,
                status=ParticipationStatus.REGISTERED,
            )

    def _assign_staff(self, championship, users):
        ChampionshipStaff.objects.get_or_create(
            championship=championship, user=users["admin"], role="ADMIN",
        )
        ChampionshipStaff.objects.get_or_create(
            championship=championship, user=users["referee"], role="REFEREE",
        )

    # --- Calendrier & résultats -------------------------------------------
    def _generate_and_play(self, championship, division, users):
        admin = users["admin"]
        start_date = timezone.localdate() - timedelta(days=35)
        generate_schedule(championship=championship, division=division, start_date=start_date, interval_days=7)

        matches = list(
            Match.objects.filter(division=division)
            .select_related("matchday", "player1", "player2")
            .order_by("matchday__number", "id")
        )
        today = timezone.localdate()
        due_matches = [m for m in matches if m.scheduled_date and m.scheduled_date <= today]

        reserved, remaining = due_matches[:2], due_matches[2:]

        if reserved:
            # Un litige de démonstration : deux saisies contradictoires.
            m = reserved[0]
            submit_result(match=m, user=users["player1"], score1=420, score2=380, submitting_participation=m.player1)
            submit_result(match=m, user=users["player2"], score1=400, score2=390, submitting_participation=m.player2)
        if len(reserved) > 1:
            # Un forfait de démonstration.
            m = reserved[1]
            declare_forfeit(m, loser=m.player1, declared_by=admin, note="Forfait (démonstration).")

        for match in remaining:
            if random.random() < 0.10:
                continue  # laissé non joué : alimente les alertes « match en retard »
            score1, score2 = self._random_score()
            submit_result(match=match, user=admin, score1=score1, score2=score2)

    @staticmethod
    def _random_score():
        a = random.randint(280, 520)
        b = random.randint(280, 520)
        if a == b and random.random() < 0.7:
            b += random.choice([-15, 15])
        return a, b

    # --- Résumé ------------------------------------------------------------
    def _print_summary(self, championship):
        self.stdout.write(self.style.SUCCESS("\nDonnées de démonstration créées."))
        self.stdout.write(f"Championnat : {championship.name} (/gestion/championnats/{championship.slug}/)")
        self.stdout.write(f"Joueurs : {championship.participations.count()}")
        self.stdout.write(f"Matchs : {Match.objects.filter(championship=championship).count()}")
        self.stdout.write("\nComptes de démonstration (mot de passe : " + DEMO_PASSWORD + ") :")
        self.stdout.write("  demo_admin    — administrateur (Super Admin)")
        self.stdout.write("  demo_arbitre  — arbitre de l'édition")
        self.stdout.write("  demo_joueur1  — Alice Bernard (Division 1)")
        self.stdout.write("  demo_joueur2  — Bastien Petit (Division 1)")
        self.stdout.write(self.style.WARNING(
            "\nÀ usage local/développement uniquement — ne jamais utiliser ces identifiants en production."
        ))
