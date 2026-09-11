"""Énumérations métier centralisées (aucune valeur en dur ailleurs)."""
from django.db import models


class ChampionshipStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    CONFIGURING = "CONFIGURING", "Configuration"
    REGISTRATION_OPEN = "REGISTRATION_OPEN", "Inscriptions ouvertes"
    SCHEDULED = "SCHEDULED", "Calendrier généré"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    FINALS = "FINALS", "Phase finale"
    COMPLETED = "COMPLETED", "Terminé"
    ARCHIVED = "ARCHIVED", "Archivé"
    CANCELLED = "CANCELLED", "Annulé"


class StaffRole(models.TextChoices):
    ADMIN = "ADMIN", "Administrateur du championnat"
    REFEREE = "REFEREE", "Arbitre"


class PrimaryTiebreak(models.TextChoices):
    SCORE_DIFF = "SCORE_DIFF", "Différence de score"
    HEAD_TO_HEAD = "HEAD_TO_HEAD", "Confrontation directe"


class TiebreakCriterion(models.TextChoices):
    SCORE_DIFF = "SCORE_DIFF", "Différence de score"
    HEAD_TO_HEAD = "HEAD_TO_HEAD", "Confrontation directe"
    WINS = "WINS", "Nombre de victoires"
    SCORE_FOR = "SCORE_FOR", "Score total marqué"
    SCORE_AGAINST_ASC = "SCORE_AGAINST_ASC", "Score total encaissé (croissant)"
    FORM = "FORM", "Forme récente"
    SEED = "SEED", "Tête de série"
    DRAW_LOTS = "DRAW_LOTS", "Tirage au sort"
    MANUAL = "MANUAL", "Décision de l'arbitre"


class MovementType(models.TextChoices):
    PROMOTION = "PROMOTION", "Promotion"
    RELEGATION = "RELEGATION", "Relégation"


class PromotionMethod(models.TextChoices):
    TOP_N = "TOP_N", "N premiers"
    BOTTOM_N = "BOTTOM_N", "N derniers"
    TOP_PERCENTAGE = "TOP_PERCENTAGE", "Pourcentage supérieur"
    BOTTOM_PERCENTAGE = "BOTTOM_PERCENTAGE", "Pourcentage inférieur"
    RANK_RANGE = "RANK_RANGE", "Plage de classement"


class ParticipationStatus(models.TextChoices):
    REGISTERED = "REGISTERED", "Inscrit"
    CONFIRMED = "CONFIRMED", "Confirmé"
    ACTIVE = "ACTIVE", "Actif"
    WITHDRAWN = "WITHDRAWN", "Retiré"
    DISQUALIFIED = "DISQUALIFIED", "Disqualifié"
    FORFEIT_ALL = "FORFEIT_ALL", "Forfait général"


class EntryOrigin(models.TextChoices):
    NEW = "NEW", "Nouvelle inscription"
    PROMOTED_FROM = "PROMOTED_FROM", "Promu"
    RELEGATED_FROM = "RELEGATED_FROM", "Relégué"
    KEPT = "KEPT", "Maintenu"
    MANUAL = "MANUAL", "Placement manuel"


class PromotionOutcome(models.TextChoices):
    PROMOTED = "PROMOTED", "Promu"
    RELEGATED = "RELEGATED", "Relégué"
    STAYED = "STAYED", "Maintenu"
    QUALIFIED_FINALS = "QUALIFIED_FINALS", "Qualifié en phase finale"
    FINALIST = "FINALIST", "Finaliste"
    CHAMPION = "CHAMPION", "Champion"


class PhaseKind(models.TextChoices):
    LEAGUE = "LEAGUE", "Phase de ligue"
    SEMI_FINAL = "SEMI_FINAL", "Demi-finale"
    FINAL = "FINAL", "Finale"
    THIRD_PLACE = "THIRD_PLACE", "Petite finale"
    PLAYOFF = "PLAYOFF", "Play-off"
    BARRAGE = "BARRAGE", "Barrage"
    CUSTOM = "CUSTOM", "Personnalisée"


class MatchdayStatus(models.TextChoices):
    PENDING = "PENDING", "À planifier"
    SCHEDULED = "SCHEDULED", "Planifiée"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    COMPLETED = "COMPLETED", "Terminée"


class MatchStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Programmé"
    UPCOMING = "UPCOMING", "À venir"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    COMPLETED = "COMPLETED", "Terminé"
    POSTPONED = "POSTPONED", "Reporté"
    CANCELLED = "CANCELLED", "Annulé"
    FORFEIT = "FORFEIT", "Forfait"
    DISPUTED = "DISPUTED", "Litige"


class ResultStatus(models.TextChoices):
    NONE = "NONE", "Aucun"
    SUBMITTED = "SUBMITTED", "Soumis"
    CONFIRMED = "CONFIRMED", "Confirmé"
    VALIDATED = "VALIDATED", "Validé"
    DISPUTED = "DISPUTED", "Litige"
    REJECTED = "REJECTED", "Rejeté"


class OutcomeType(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    FORFEIT_P1 = "FORFEIT_P1", "Forfait joueur 1"
    FORFEIT_P2 = "FORFEIT_P2", "Forfait joueur 2"
    DOUBLE_FORFEIT = "DOUBLE_FORFEIT", "Double forfait"
    BYE = "BYE", "Exempt"
    NOT_PLAYED = "NOT_PLAYED", "Non joué"


class SubmissionSource(models.TextChoices):
    PLAYER = "PLAYER", "Joueur"
    OPPONENT = "OPPONENT", "Adversaire"
    REFEREE = "REFEREE", "Arbitre"
    ADMIN = "ADMIN", "Administrateur"
    IMPORT = "IMPORT", "Import"


class ResultEntryPolicy(models.TextChoices):
    WINNER_ONLY = "WINNER_ONLY", "Vainqueur uniquement"
    BOTH_PLAYERS = "BOTH_PLAYERS", "Les deux joueurs"
    ADMIN_ONLY = "ADMIN_ONLY", "Administrateur uniquement"


class FinalsFormat(models.TextChoices):
    SEMI_1V4_2V3 = "SEMI_1V4_2V3", "Demi-finales 1v4 / 2v3"
    KNOCKOUT = "KNOCKOUT", "Élimination directe (têtes de série)"
    CUSTOM = "CUSTOM", "Personnalisé"


class MovementZone(models.TextChoices):
    PROMOTION = "PROMOTION", "Promotion"
    FINALS = "FINALS", "Qualification phase finale"
    SAFE = "SAFE", "Maintien"
    RELEGATION = "RELEGATION", "Relégation"


class BracketStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    READY = "READY", "Prêt"
    IN_PROGRESS = "IN_PROGRESS", "En cours"
    COMPLETED = "COMPLETED", "Terminé"


class TransitionStatus(models.TextChoices):
    PROPOSED = "PROPOSED", "Proposée"
    ADJUSTED = "ADJUSTED", "Ajustée"
    CONFIRMED = "CONFIRMED", "Confirmée"
    CANCELLED = "CANCELLED", "Annulée"


class MoveType(models.TextChoices):
    PROMOTED = "PROMOTED", "Promu"
    RELEGATED = "RELEGATED", "Relégué"
    KEPT = "KEPT", "Maintenu"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE", "Ajustement manuel"
    NEW = "NEW", "Nouvel inscrit"
    WITHDRAWN = "WITHDRAWN", "Retiré"


class NotificationKind(models.TextChoices):
    MATCH_TODAY = "MATCH_TODAY", "Match aujourd'hui"
    RESULT_RECORDED = "RESULT_RECORDED", "Résultat enregistré"
    RESULT_NEEDS_CONFIRMATION = "RESULT_NEEDS_CONFIRMATION", "Résultat à confirmer"
    RESULT_DISPUTED = "RESULT_DISPUTED", "Résultat en litige"
    DISPUTE_TO_RESOLVE = "DISPUTE_TO_RESOLVE", "Litige à trancher"
    MATCH_LATE = "MATCH_LATE", "Match en retard"
    MATCH_LATE_ADMIN = "MATCH_LATE_ADMIN", "Match en retard (à relancer)"
    RANK_UPDATE = "RANK_UPDATE", "Classement mis à jour"
    PROMOTION_ZONE = "PROMOTION_ZONE", "Zone de promotion"
    RELEGATION_ZONE = "RELEGATION_ZONE", "Zone de relégation"
    FINALS_QUALIFIED = "FINALS_QUALIFIED", "Qualifié en phase finale"
    RULE_CHANGED = "RULE_CHANGED", "Règle modifiée"
    GENERIC = "GENERIC", "Information"


class NotificationPriority(models.TextChoices):
    LOW = "LOW", "Basse"
    NORMAL = "NORMAL", "Normale"
    HIGH = "HIGH", "Haute"


class AuditAction(models.TextChoices):
    CHAMPIONSHIP_CREATED = "CHAMPIONSHIP_CREATED", "Championnat créé"
    SETTINGS_UPDATED = "SETTINGS_UPDATED", "Configuration modifiée"
    DIVISION_CREATED = "DIVISION_CREATED", "Division créée"
    DIVISION_UPDATED = "DIVISION_UPDATED", "Division modifiée"
    DIVISION_DELETED = "DIVISION_DELETED", "Division supprimée"
    MOVEMENT_RULE_CREATED = "MOVEMENT_RULE_CREATED", "Règle de mouvement créée"
    MOVEMENT_RULE_DELETED = "MOVEMENT_RULE_DELETED", "Règle de mouvement supprimée"
    PLAYER_CREATED = "PLAYER_CREATED", "Joueur créé"
    PLAYER_UPDATED = "PLAYER_UPDATED", "Joueur modifié"
    PLAYER_IMPORTED = "PLAYER_IMPORTED", "Import de joueurs"
    RESULT_SUBMITTED = "RESULT_SUBMITTED", "Résultat soumis"
    RESULT_CONFIRMED = "RESULT_CONFIRMED", "Résultat confirmé"
    RESULT_VALIDATED = "RESULT_VALIDATED", "Résultat validé"
    RESULT_EDITED = "RESULT_EDITED", "Résultat modifié"
    RESULT_REJECTED = "RESULT_REJECTED", "Résultat rejeté"
    DISPUTE_OPENED = "DISPUTE_OPENED", "Litige ouvert"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED", "Litige résolu"
    TIE_RESOLVED = "TIE_RESOLVED", "Égalité tranchée"
    RULE_CHANGED = "RULE_CHANGED", "Règle modifiée"
    RULES_LOCKED = "RULES_LOCKED", "Règles verrouillées"
    SCHEDULE_GENERATED = "SCHEDULE_GENERATED", "Calendrier généré"
    MATCH_RESCHEDULED = "MATCH_RESCHEDULED", "Match reprogrammé"
    MATCH_POSTPONED = "MATCH_POSTPONED", "Match reporté"
    MATCH_CANCELLED = "MATCH_CANCELLED", "Match annulé"
    MATCH_FORFEIT_DECLARED = "MATCH_FORFEIT_DECLARED", "Forfait déclaré"
    BRACKET_GENERATED = "BRACKET_GENERATED", "Tableau final généré"
    TRANSITION_PROPOSED = "TRANSITION_PROPOSED", "Saison suivante proposée"
    TRANSITION_MOVE_ADJUSTED = "TRANSITION_MOVE_ADJUSTED", "Mouvement de transition ajusté"
    PLAYER_REGISTERED = "PLAYER_REGISTERED", "Joueur inscrit"
    PLAYER_WITHDRAWN = "PLAYER_WITHDRAWN", "Joueur retiré"
    PLAYER_PROMOTED = "PLAYER_PROMOTED", "Joueur promu"
    PLAYER_RELEGATED = "PLAYER_RELEGATED", "Joueur relégué"
    TRANSITION_CONFIRMED = "TRANSITION_CONFIRMED", "Transition de saison confirmée"
