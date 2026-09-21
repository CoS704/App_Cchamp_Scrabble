"""Règles métier de configuration d'un championnat (§48, §17)."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.enums import ChampionshipStatus, PrimaryTiebreak, PromotionMethod, TiebreakCriterion

from .models import ChampionshipSettings, ChampionshipTiebreak

# Chaîne de départage amorcée automatiquement selon le critère principal
# choisi pour l'édition. Reste modifiable finement depuis l'admin Django.
DEFAULT_TIEBREAK_CHAINS = {
    PrimaryTiebreak.SCORE_DIFF: [
        TiebreakCriterion.SCORE_DIFF,
        TiebreakCriterion.HEAD_TO_HEAD,
        TiebreakCriterion.WINS,
        TiebreakCriterion.MANUAL,
    ],
    PrimaryTiebreak.HEAD_TO_HEAD: [
        TiebreakCriterion.HEAD_TO_HEAD,
        TiebreakCriterion.SCORE_DIFF,
        TiebreakCriterion.WINS,
        TiebreakCriterion.MANUAL,
    ],
}


def initialize_championship(championship):
    """Amorce la configuration par défaut d'une édition qui vient d'être créée."""
    settings_obj, _ = ChampionshipSettings.objects.get_or_create(championship=championship)
    regenerate_tiebreak_chain(championship, settings_obj.primary_tiebreak)
    return settings_obj


def regenerate_tiebreak_chain(championship, primary):
    """Réinitialise la chaîne de départage sur le critère principal choisi.

    N'appeler que lorsque ``primary_tiebreak`` change réellement : ceci
    écrase toute personnalisation fine de la chaîne faite depuis l'admin.
    """
    chain = DEFAULT_TIEBREAK_CHAINS[primary]
    championship.tiebreaks.all().delete()
    ChampionshipTiebreak.objects.bulk_create(
        ChampionshipTiebreak(championship=championship, position=i + 1, criterion=criterion)
        for i, criterion in enumerate(chain)
    )


def rule_rank_indices(rule, n: int) -> set[int]:
    """Rangs (1-indexés) auxquels une règle de promotion/relégation s'applique,
    pour un classement de ``n`` joueurs. Partagé entre le moteur de classement
    (badges de zone) et la génération de la saison suivante (destination
    réelle)."""
    if rule.method == PromotionMethod.TOP_N and rule.value_n:
        return set(range(1, min(rule.value_n, n) + 1))
    if rule.method == PromotionMethod.BOTTOM_N and rule.value_n:
        return set(range(max(n - rule.value_n + 1, 1), n + 1))
    if rule.method == PromotionMethod.TOP_PERCENTAGE and rule.percentage is not None:
        count = max(1, round(n * float(rule.percentage) / 100))
        return set(range(1, min(count, n) + 1))
    if rule.method == PromotionMethod.BOTTOM_PERCENTAGE and rule.percentage is not None:
        count = max(1, round(n * float(rule.percentage) / 100))
        return set(range(max(n - count + 1, 1), n + 1))
    if rule.method == PromotionMethod.RANK_RANGE and rule.rank_min and rule.rank_max:
        return set(range(rule.rank_min, min(rule.rank_max, n) + 1))
    return set()


def lock_rules(championship):
    """Verrouille les règles critiques de l'édition (§49)."""
    championship.rules_locked_at = timezone.now()
    championship.save(update_fields=["rules_locked_at", "updated_at"])
    return championship


# Statuts qui supposent un calendrier déjà généré : passer « En cours » sans
# aucun match n'a pas de sens (rien à jouer, rien à classer).
_STATUSES_REQUIRING_SCHEDULE = {
    ChampionshipStatus.SCHEDULED,
    ChampionshipStatus.IN_PROGRESS,
    ChampionshipStatus.FINALS,
}


def change_status(championship, new_status):
    """Change le statut d'une édition, avec les garde-fous d'intégrité.

    Jusqu'ici rien ne faisait jamais évoluer le statut : une édition créée
    depuis l'interface restait « Brouillon » indéfiniment (donc absente des
    classements publics, de « Mon espace » et des notifications de retard).
    """
    if new_status not in ChampionshipStatus.values:
        raise ValidationError("Statut inconnu.")
    if new_status == championship.status:
        raise ValidationError("Le championnat a déjà ce statut.")

    if new_status in _STATUSES_REQUIRING_SCHEDULE and not championship.matches.exists():
        raise ValidationError(
            "Générez d'abord le calendrier (page Calendrier) : ce statut suppose "
            "que des matchs existent."
        )
    if new_status == ChampionshipStatus.DRAFT and (
        championship.participations.exists() or championship.matches.exists()
    ):
        # Un brouillon est supprimable en un clic : on ne le redevient pas
        # une fois que des inscriptions ou des matchs existent.
        raise ValidationError(
            "Impossible de revenir en brouillon : des inscriptions ou des matchs existent déjà."
        )

    championship.status = new_status
    championship.save(update_fields=["status", "updated_at"])
    return championship
