from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.enums import EntryOrigin, ParticipationStatus, PromotionOutcome
from core.models import TimeStampedModel


class ChampionshipParticipation(TimeStampedModel):
    """Participation d'un joueur à une édition précise — entité pivot.

    La division d'un joueur n'existe que dans ce contexte. L'historique complet
    se lit en suivant ``source_participation`` d'une édition à l'autre.
    """

    championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.CASCADE,
        related_name="participations",
    )
    player = models.ForeignKey(
        "players.Player", on_delete=models.PROTECT, related_name="participations"
    )
    division = models.ForeignKey(
        "championships.Division", on_delete=models.PROTECT, related_name="participations"
    )
    seed = models.PositiveIntegerField("tête de série", null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ParticipationStatus.choices,
        default=ParticipationStatus.REGISTERED,
        db_index=True,
    )
    entry_origin = models.CharField(
        max_length=16, choices=EntryOrigin.choices, default=EntryOrigin.NEW
    )
    source_participation = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_participations",
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    # --- Instantané figé à la clôture de l'édition -----------------------
    final_rank = models.PositiveIntegerField(null=True, blank=True)
    final_points = models.IntegerField(null=True, blank=True)
    final_played = models.PositiveIntegerField(null=True, blank=True)
    final_wins = models.PositiveIntegerField(null=True, blank=True)
    final_draws = models.PositiveIntegerField(null=True, blank=True)
    final_losses = models.PositiveIntegerField(null=True, blank=True)
    final_score_for = models.IntegerField(null=True, blank=True)
    final_score_against = models.IntegerField(null=True, blank=True)
    final_score_diff = models.IntegerField(null=True, blank=True)
    promotion_outcome = models.CharField(
        max_length=20, choices=PromotionOutcome.choices, blank=True
    )
    resulting_division_carryover_key = models.SlugField(max_length=40, blank=True)

    class Meta:
        verbose_name = "participation"
        verbose_name_plural = "participations"
        ordering = ["championship", "division", "seed"]
        constraints = [
            models.UniqueConstraint(
                fields=["championship", "player"],
                name="uniq_player_per_championship",
            ),
        ]
        indexes = [
            models.Index(fields=["championship", "division", "status"]),
        ]

    def __str__(self):
        return f"{self.player} — {self.championship} ({self.division.name})"

    def clean(self):
        if (
            self.division_id
            and self.championship_id
            and self.division.championship_id != self.championship_id
        ):
            raise ValidationError(
                {"division": "La division doit appartenir au championnat de la participation."}
            )
