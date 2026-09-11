from django.conf import settings
from django.db import models

from core.enums import MoveType, TransitionStatus
from core.models import TimeStampedModel


class SeasonTransition(TimeStampedModel):
    """Génération de la composition de l'édition suivante à partir des classements
    finaux et des règles de promotion / relégation."""

    from_championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.PROTECT,
        related_name="transitions_out",
    )
    to_championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transitions_in",
    )
    status = models.CharField(
        max_length=12,
        choices=TransitionStatus.choices,
        default=TransitionStatus.PROPOSED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transitions_created",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transitions_confirmed",
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "transition de saison"
        verbose_name_plural = "transitions de saison"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.from_championship} → {self.to_championship or '?'}"


class SeasonTransitionMove(TimeStampedModel):
    transition = models.ForeignKey(
        SeasonTransition, on_delete=models.CASCADE, related_name="moves"
    )
    source_participation = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.PROTECT,
        related_name="transition_moves",
    )
    player = models.ForeignKey(
        "players.Player", on_delete=models.PROTECT, related_name="transition_moves"
    )
    from_carryover_key = models.SlugField(max_length=40)
    to_carryover_key = models.SlugField(max_length=40, blank=True)
    move_type = models.CharField(max_length=16, choices=MoveType.choices)
    is_manual_override = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "mouvement de transition"
        verbose_name_plural = "mouvements de transition"
        ordering = ["transition", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["transition", "source_participation"],
                name="uniq_move_per_participation",
            ),
        ]

    def __str__(self):
        target = self.to_carryover_key or "—"
        return f"{self.player}: {self.from_carryover_key} → {target} ({self.move_type})"
