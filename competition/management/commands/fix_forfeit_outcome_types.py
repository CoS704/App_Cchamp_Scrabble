"""Corrige les matchs validés dont le forfait a été saisi comme un résultat
normal (score technique tapé à la main plutôt que via « Déclarer un
forfait »), ce qui fausse les statistiques qui excluent les forfaits
(distinctions de fin de championnat — voir
``rankings.services.championship_distinctions``).

Un match est repéré comme forfait si son score correspond exactement à la
convention configurée (``forfeit_score_for``/``forfeit_score_against``) —
jamais sur un simple écart important, qui peut très bien être un score réel
— ou si son score est 0-0 sans vainqueur (double forfait : il n'existe pas
de score technique dédié pour ce cas dans les réglages, 0-0 est la seule
convention observée en production).

    python manage.py fix_forfeit_outcome_types             # aperçu (aucune écriture)
    python manage.py fix_forfeit_outcome_types --apply      # applique la correction
    python manage.py fix_forfeit_outcome_types --apply --championship=mon-slug

Ne touche jamais au score, au vainqueur ni aux points déjà comptés : seul
``outcome_type`` (et le statut, mis à ``FORFEIT``) est corrigé, pour que les
vues qui filtrent sur ``outcome_type`` traitent enfin ces matchs comme les
forfaits qu'ils sont réellement.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from championships.models import Championship
from competition.models import Match
from core.enums import MatchStatus, OutcomeType, ResultStatus


class Command(BaseCommand):
    help = "Corrige l'outcome_type des forfaits saisis comme des résultats normaux."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Applique réellement la correction (sans cette option : aperçu seul).",
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

        total_changed = 0
        for championship in championships:
            settings_obj = championship.settings
            ffor, fagainst = settings_obj.forfeit_score_for, settings_obj.forfeit_score_against
            matches = Match.objects.filter(
                championship=championship,
                result_status=ResultStatus.VALIDATED,
                outcome_type=OutcomeType.NORMAL,
                player2__isnull=False,
            ).select_related("player1__player", "player2__player")

            changed_here = 0
            for match in matches:
                scores = {match.score1, match.score2}
                is_forfeit_scoreline = ffor != fagainst and scores == {ffor, fagainst}
                is_zero_zero = match.score1 == 0 and match.score2 == 0
                if not (is_forfeit_scoreline or is_zero_zero):
                    continue

                if is_zero_zero:
                    new_outcome = OutcomeType.DOUBLE_FORFEIT
                elif match.winner_id == match.player1_id:
                    new_outcome = OutcomeType.FORFEIT_P2
                elif match.winner_id == match.player2_id:
                    new_outcome = OutcomeType.FORFEIT_P1
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  id={match.id} {match.player1.player} {match.score1}-{match.score2} "
                        f"{match.player2.player} : score de forfait mais pas de vainqueur "
                        "— ignoré, à vérifier à la main."
                    ))
                    continue

                self.stdout.write(
                    f"  id={match.id} {match.player1.player} {match.score1}-{match.score2} "
                    f"{match.player2.player} : {match.outcome_type} -> {new_outcome}"
                )
                changed_here += 1
                if apply_changes:
                    match.outcome_type = new_outcome
                    match.status = MatchStatus.FORFEIT
                    match.save(update_fields=["outcome_type", "status", "updated_at"])

            if changed_here:
                self.stdout.write(self.style.SUCCESS(
                    f"{championship.name} : {changed_here} match(es) "
                    f"{'corrigé(s)' if apply_changes else 'à corriger (aperçu)'}."
                ))
                total_changed += changed_here

        if total_changed == 0:
            self.stdout.write("Aucun match à corriger.")
        elif not apply_changes:
            self.stdout.write(self.style.WARNING(
                f"\n{total_changed} match(es) au total seraient corrigés "
                "— relancer avec --apply pour appliquer."
            ))
