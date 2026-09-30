"""Ajoute le critère de départage ALPHABETICAL (ordre alphabétique du nom)
juste avant MANUAL dans la chaîne d'un championnat déjà créé.

Ce critère a été ajouté après coup (voir ``core.enums.TiebreakCriterion`` et
``rankings.services._criterion_key``) : les nouveaux championnats l'ont déjà
dans leur chaîne par défaut (``championships.services.DEFAULT_TIEBREAK_CHAINS``),
mais un championnat créé avant ce changement doit être mis à jour
explicitement — sa chaîne existante n'est jamais modifiée en silence.

    python manage.py add_alphabetical_tiebreak                       # aperçu
    python manage.py add_alphabetical_tiebreak --apply                # applique
    python manage.py add_alphabetical_tiebreak --apply --championship=mon-slug

Ne touche qu'à la chaîne de départage (positions + nouvelle ligne) : aucun
résultat, score ou classement déjà calculé n'est modifié — le classement est
toujours recalculé à l'affichage à partir des matchs validés.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from championships.models import Championship, ChampionshipTiebreak
from core.enums import TiebreakCriterion


class Command(BaseCommand):
    help = "Insère le critère ALPHABETICAL avant MANUAL dans la chaîne de départage existante."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Applique réellement le changement (sans cette option : aperçu seul).",
        )
        parser.add_argument(
            "--championship", dest="championship_slug", default=None,
            help="Limiter à un seul championnat (slug). Par défaut : tous.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        slug = options["championship_slug"]
        championships = Championship.objects.all()
        if slug:
            championships = championships.filter(slug=slug)

        total = 0
        for championship in championships:
            chain = list(championship.tiebreaks.order_by("position"))
            criteria = {t.criterion for t in chain}
            if TiebreakCriterion.ALPHABETICAL in criteria:
                continue

            manual_entries = [t for t in chain if t.criterion == TiebreakCriterion.MANUAL]
            insert_position = manual_entries[0].position if manual_entries else (
                (chain[-1].position + 1) if chain else 1
            )

            self.stdout.write(
                f"{championship.name} : insertion de ALPHABETICAL en position {insert_position}"
                f"{' (avant MANUAL)' if manual_entries else ''}"
            )
            total += 1
            if apply_changes:
                with transaction.atomic():
                    to_shift = sorted(
                        (t for t in chain if t.position >= insert_position),
                        key=lambda t: -t.position,
                    )
                    for tiebreak in to_shift:
                        tiebreak.position += 1
                        tiebreak.save(update_fields=["position"])
                    ChampionshipTiebreak.objects.create(
                        championship=championship,
                        position=insert_position,
                        criterion=TiebreakCriterion.ALPHABETICAL,
                        is_active=True,
                    )

        if total == 0:
            self.stdout.write("Rien à faire : ALPHABETICAL déjà présent partout.")
        elif not apply_changes:
            self.stdout.write(self.style.WARNING(
                f"\n{total} championnat(s) seraient modifiés — relancer avec --apply pour appliquer."
            ))
