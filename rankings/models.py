from django.db import models

from core.enums import MovementZone, PrimaryTiebreak
from core.models import TimeStampedModel


class StandingSnapshot(TimeStampedModel):
    """Photo d'un classement — *cache + historique*, jamais source de vérité.

    Le classement reste recalculable à tout moment depuis les matchs validés
    (``python manage.py rebuild_standings``).
    """

    championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.CASCADE,
        related_name="standing_snapshots",
    )
    division = models.ForeignKey(
        "championships.Division",
        on_delete=models.CASCADE,
        related_name="standing_snapshots",
    )
    phase = models.ForeignKey(
        "competition.Phase", on_delete=models.CASCADE, related_name="standing_snapshots"
    )
    as_of_matchday = models.ForeignKey(
        "competition.Matchday",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="standing_snapshots",
        help_text="Vide = état courant.",
    )
    is_current = models.BooleanField(default=False, db_index=True)
    computed_at = models.DateTimeField(auto_now_add=True)
    tiebreak_primary_used = models.CharField(
        max_length=16, choices=PrimaryTiebreak.choices, blank=True
    )
    has_unresolved_tie = models.BooleanField(default=False)

    class Meta:
        verbose_name = "instantané de classement"
        verbose_name_plural = "instantanés de classement"
        ordering = ["-computed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "phase"],
                condition=models.Q(is_current=True),
                name="uniq_current_snapshot_per_division_phase",
            ),
        ]

    def __str__(self):
        return f"Classement {self.division} @ {self.computed_at:%Y-%m-%d %H:%M}"


class StandingRow(TimeStampedModel):
    snapshot = models.ForeignKey(
        StandingSnapshot, on_delete=models.CASCADE, related_name="rows"
    )
    participation = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.CASCADE,
        related_name="standing_rows",
    )
    rank = models.PositiveIntegerField()
    played = models.PositiveIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    points = models.IntegerField(default=0)
    score_for = models.IntegerField(default=0)
    score_against = models.IntegerField(default=0)
    score_diff = models.IntegerField(default=0)
    win_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    form = models.JSONField(default=list, blank=True)
    tie_group = models.PositiveIntegerField(null=True, blank=True)
    movement_zone = models.CharField(
        max_length=12, choices=MovementZone.choices, blank=True
    )
    rank_change = models.IntegerField(default=0)
    movement_probabilities = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "ligne de classement"
        verbose_name_plural = "lignes de classement"
        ordering = ["snapshot", "rank"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "participation"],
                name="uniq_row_per_snapshot_participation",
            ),
        ]

    def __str__(self):
        return f"#{self.rank} {self.participation.player} ({self.points} pts)"
