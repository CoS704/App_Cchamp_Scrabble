from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

from core.enums import (
    ChampionshipStatus,
    FinalsFormat,
    MovementType,
    PrimaryTiebreak,
    PromotionMethod,
    ResultEntryPolicy,
    TiebreakCriterion,
)
from core.models import TimeStampedModel


class CompetitionSeries(TimeStampedModel):
    """Regroupe les éditions successives d'une même compétition."""

    name = models.CharField("nom", max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    organizer = models.CharField("organisateur", max_length=160, blank=True)
    is_active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "série de compétitions"
        verbose_name_plural = "séries de compétitions"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Championship(TimeStampedModel):
    """Une édition précise d'une compétition."""

    series = models.ForeignKey(
        CompetitionSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="editions",
        verbose_name="série",
    )
    name = models.CharField("nom", max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    season = models.CharField("saison", max_length=40, help_text="Ex. « 2026 ».")
    edition_number = models.PositiveIntegerField("numéro d'édition", null=True, blank=True)
    description = models.TextField(blank=True)
    start_date = models.DateField("date de début", null=True, blank=True)
    end_date = models.DateField("date de fin", null=True, blank=True)
    registration_opens_at = models.DateTimeField(
        "ouverture des inscriptions", null=True, blank=True
    )
    registration_closes_at = models.DateTimeField(
        "clôture des inscriptions", null=True, blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=ChampionshipStatus.choices,
        default=ChampionshipStatus.DRAFT,
        db_index=True,
    )
    is_inaugural = models.BooleanField(
        "édition inaugurale",
        default=False,
        help_text="Tous les joueurs peuvent démarrer dans la division inférieure.",
    )
    rules_locked_at = models.DateTimeField(
        "règles verrouillées le", null=True, blank=True
    )
    previous_edition = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_editions",
        verbose_name="édition précédente",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="championships_created",
    )

    class Meta:
        verbose_name = "championnat"
        verbose_name_plural = "championnats"
        ordering = ["-season", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["series", "season"], name="uniq_season_per_series"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def rules_locked(self) -> bool:
        return self.rules_locked_at is not None

    @property
    def is_running(self) -> bool:
        return self.status in {
            ChampionshipStatus.IN_PROGRESS,
            ChampionshipStatus.FINALS,
        }

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or slugify(f"championnat-{self.season}")
            slug, n = base, 2
            while Championship.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class ChampionshipSettings(TimeStampedModel):
    """Toutes les règles configurables de l'édition, en un objet auditable."""

    championship = models.OneToOneField(
        Championship, on_delete=models.CASCADE, related_name="settings"
    )

    # Barème
    points_win = models.IntegerField("points victoire", default=3)
    points_draw = models.IntegerField("points nul", default=1)
    points_loss = models.IntegerField("points défaite", default=0)
    points_forfeit_win = models.IntegerField("points victoire par forfait", default=3)
    points_forfeit_loss = models.IntegerField("points défaite par forfait", default=0)
    forfeit_score_for = models.PositiveIntegerField(
        "score attribué au vainqueur sur forfait", default=0
    )
    forfeit_score_against = models.PositiveIntegerField(
        "score attribué au perdant sur forfait", default=0
    )

    # Départage
    primary_tiebreak = models.CharField(
        "départage principal",
        max_length=16,
        choices=PrimaryTiebreak.choices,
        default=PrimaryTiebreak.SCORE_DIFF,
    )

    # Format
    round_robin_legs = models.PositiveSmallIntegerField(
        "nombre de confrontations (aller / aller-retour)",
        default=1,
        validators=[MinValueValidator(1)],
    )

    # Saisie des résultats
    result_entry_policy = models.CharField(
        "politique de saisie des résultats",
        max_length=16,
        choices=ResultEntryPolicy.choices,
        default=ResultEntryPolicy.WINNER_ONLY,
    )
    result_confirmation_required = models.BooleanField(
        "confirmation du résultat requise", default=True
    )
    double_entry_auto_confirm = models.BooleanField(
        "confirmation automatique si deux saisies identiques", default=True
    )
    late_match_threshold_days = models.PositiveSmallIntegerField(
        "seuil « match en retard » (jours)", default=3
    )

    # Phase finale
    finals_enabled = models.BooleanField("phase finale activée", default=False)
    finals_qualifiers_count = models.PositiveSmallIntegerField(
        "nombre de qualifiés par division", default=4
    )
    finals_format = models.CharField(
        "format de la phase finale",
        max_length=20,
        choices=FinalsFormat.choices,
        default=FinalsFormat.SEMI_1V4_2V3,
    )
    finals_third_place = models.BooleanField("petite finale", default=True)

    # Transitions inter-éditions
    carry_over_between_editions = models.BooleanField(
        "gérer promotions / relégations vers l'édition suivante", default=True
    )

    class Meta:
        verbose_name = "configuration du championnat"
        verbose_name_plural = "configurations des championnats"

    def __str__(self):
        return f"Configuration — {self.championship}"


class Division(TimeStampedModel):
    """Division propre à une édition (capacités et nombre variables)."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    STATUS_CHOICES = [(ACTIVE, "Active"), (INACTIVE, "Inactive")]

    championship = models.ForeignKey(
        Championship, on_delete=models.CASCADE, related_name="divisions"
    )
    name = models.CharField("nom", max_length=80)
    level = models.PositiveSmallIntegerField(
        "niveau", help_text="1 = élite. Détermine la hiérarchie."
    )
    carryover_key = models.SlugField(
        "clé inter-éditions",
        max_length=40,
        help_text="Clé stable d'une édition à l'autre (ex. « d1 »).",
    )
    capacity_min = models.PositiveIntegerField("capacité minimale", null=True, blank=True)
    capacity_max = models.PositiveIntegerField(
        "capacité maximale", null=True, blank=True, help_text="Vide = illimitée."
    )
    is_unlimited = models.BooleanField("capacité illimitée", default=False)
    color = models.CharField("couleur", max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    description = models.TextField(blank=True)
    params = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "division"
        verbose_name_plural = "divisions"
        ordering = ["championship", "level"]
        constraints = [
            models.UniqueConstraint(
                fields=["championship", "level"], name="uniq_division_level"
            ),
            models.UniqueConstraint(
                fields=["championship", "name"], name="uniq_division_name"
            ),
            models.UniqueConstraint(
                fields=["championship", "carryover_key"], name="uniq_division_carryover"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(capacity_min__isnull=True)
                    | models.Q(capacity_max__isnull=True)
                    | models.Q(capacity_max__gte=models.F("capacity_min"))
                ),
                name="division_capacity_min_lte_max",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.championship.season})"

    @property
    def registered_count(self) -> int:
        return self.participations.exclude(
            status__in=["WITHDRAWN", "DISQUALIFIED"]
        ).count()

    @property
    def seats_available(self):
        if self.is_unlimited or self.capacity_max is None:
            return None
        return max(self.capacity_max - self.registered_count, 0)


class ChampionshipTiebreak(TimeStampedModel):
    """Chaîne ordonnée de critères de départage (le tri par points est implicite)."""

    championship = models.ForeignKey(
        Championship, on_delete=models.CASCADE, related_name="tiebreaks"
    )
    position = models.PositiveSmallIntegerField("ordre d'application")
    criterion = models.CharField(max_length=20, choices=TiebreakCriterion.choices)
    is_active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "critère de départage"
        verbose_name_plural = "critères de départage"
        ordering = ["championship", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["championship", "position"], name="uniq_tiebreak_position"
            ),
            models.UniqueConstraint(
                fields=["championship", "criterion"], name="uniq_tiebreak_criterion"
            ),
        ]

    def __str__(self):
        return f"{self.position}. {self.get_criterion_display()}"


class PromotionRelegationRule(TimeStampedModel):
    """Un mouvement configurable entre deux divisions d'une édition."""

    championship = models.ForeignKey(
        Championship, on_delete=models.CASCADE, related_name="movement_rules"
    )
    movement_type = models.CharField(
        "type de mouvement", max_length=12, choices=MovementType.choices
    )
    source_division = models.ForeignKey(
        # RESTRICT plutôt que PROTECT : voir participations.ChampionshipParticipation.division.
        Division,
        on_delete=models.RESTRICT,
        related_name="movement_rules_out",
        verbose_name="division source",
    )
    target_division = models.ForeignKey(
        Division,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="movement_rules_in",
        verbose_name="division destination",
        help_text="Vide = sortie de la structure / maintien hors division.",
    )
    method = models.CharField("méthode", max_length=20, choices=PromotionMethod.choices)
    value_n = models.PositiveIntegerField("valeur N", null=True, blank=True)
    percentage = models.DecimalField(
        "pourcentage", max_digits=5, decimal_places=2, null=True, blank=True
    )
    rank_min = models.PositiveIntegerField("rang minimum", null=True, blank=True)
    rank_max = models.PositiveIntegerField("rang maximum", null=True, blank=True)
    priority = models.PositiveSmallIntegerField("priorité", default=100)
    is_active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "règle de promotion / relégation"
        verbose_name_plural = "règles de promotion / relégation"
        ordering = ["championship", "priority"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(source_division=models.F("target_division")),
                name="movement_source_ne_target",
            ),
        ]

    def __str__(self):
        target = self.target_division or "—"
        return f"{self.get_movement_type_display()} : {self.source_division} → {target}"

    def clean(self):
        errors = {}
        if self.method in {PromotionMethod.TOP_N, PromotionMethod.BOTTOM_N} and not self.value_n:
            errors["value_n"] = "Renseignez le nombre de joueurs pour cette méthode."
        if self.method in {
            PromotionMethod.TOP_PERCENTAGE,
            PromotionMethod.BOTTOM_PERCENTAGE,
        } and self.percentage is None:
            errors["percentage"] = "Renseignez le pourcentage pour cette méthode."
        if self.method == PromotionMethod.RANK_RANGE and (
            self.rank_min is None or self.rank_max is None
        ):
            errors["rank_min"] = "Renseignez la plage de classement (min et max)."
        if (
            self.source_division_id
            and self.target_division_id
            and self.source_division.championship_id != self.target_division.championship_id
        ):
            errors["target_division"] = "Les deux divisions doivent appartenir à la même édition."
        if errors:
            raise ValidationError(errors)
