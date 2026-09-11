from django.db import models

from core.enums import BracketStatus
from core.models import TimeStampedModel


class Bracket(TimeStampedModel):
    """Tableau à élimination, générique (taille et format libres)."""

    championship = models.ForeignKey(
        "championships.Championship", on_delete=models.CASCADE, related_name="brackets"
    )
    division = models.ForeignKey(
        "championships.Division",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="brackets",
    )
    phase = models.ForeignKey(
        "competition.Phase", on_delete=models.CASCADE, related_name="brackets"
    )
    size = models.PositiveSmallIntegerField("nombre de qualifiés")
    format = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16, choices=BracketStatus.choices, default=BracketStatus.PENDING
    )

    class Meta:
        verbose_name = "tableau final"
        verbose_name_plural = "tableaux finaux"

    def __str__(self):
        scope = self.division.name if self.division_id else "général"
        return f"Tableau {scope} — {self.championship}"


class BracketSlot(TimeStampedModel):
    """Emplacement du tableau, relié à ses emplacements sources (vainqueur / perdant)."""

    bracket = models.ForeignKey(Bracket, on_delete=models.CASCADE, related_name="slots")
    round_index = models.PositiveSmallIntegerField(help_text="0 = premier tour.")
    position = models.PositiveSmallIntegerField()
    seed = models.PositiveSmallIntegerField(null=True, blank=True)
    participation = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bracket_slots",
    )
    source_slot_win = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feeds_win",
    )
    source_slot_lose = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feeds_lose",
    )
    match = models.OneToOneField(
        "competition.Match",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bracket_slot",
    )
    is_third_place = models.BooleanField(default=False)

    class Meta:
        verbose_name = "emplacement de tableau"
        verbose_name_plural = "emplacements de tableau"
        ordering = ["bracket", "round_index", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["bracket", "round_index", "position"], name="uniq_slot_position"
            ),
        ]

    def __str__(self):
        return f"R{self.round_index}·P{self.position} — {self.bracket}"
