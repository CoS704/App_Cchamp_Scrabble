from django.conf import settings
from django.db import models

from core.enums import (
    MatchStatus,
    MatchdayStatus,
    OutcomeType,
    PhaseKind,
    ResultStatus,
    SubmissionSource,
)
from core.models import TimeStampedModel


class Phase(TimeStampedModel):
    """Segment de compétition (ligue, demi-finale, finale, barrage…)."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    STATUS_CHOICES = [
        (PENDING, "En attente"),
        (IN_PROGRESS, "En cours"),
        (COMPLETED, "Terminée"),
    ]

    championship = models.ForeignKey(
        "championships.Championship", on_delete=models.CASCADE, related_name="phases"
    )
    division = models.ForeignKey(
        "championships.Division",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="phases",
        help_text="Vide = phase commune à toutes les divisions.",
    )
    kind = models.CharField(max_length=16, choices=PhaseKind.choices, default=PhaseKind.LEAGUE)
    name = models.CharField("nom", max_length=120)
    order = models.PositiveSmallIntegerField("ordre", default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "phase"
        verbose_name_plural = "phases"
        ordering = ["championship", "division", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "kind", "order"],
                name="uniq_phase_per_division_kind_order",
            ),
        ]

    def __str__(self):
        scope = self.division.name if self.division_id else "Toutes divisions"
        return f"{self.name} — {scope}"


class Matchday(TimeStampedModel):
    """Journée de championnat au sein d'une phase."""

    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="matchdays")
    number = models.PositiveSmallIntegerField("numéro")
    name = models.CharField("nom", max_length=80, blank=True)
    scheduled_date = models.DateField("date prévue", null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=MatchdayStatus.choices, default=MatchdayStatus.PENDING
    )

    class Meta:
        verbose_name = "journée"
        verbose_name_plural = "journées"
        ordering = ["phase", "number"]
        constraints = [
            models.UniqueConstraint(fields=["phase", "number"], name="uniq_matchday_number"),
        ]

    def __str__(self):
        return self.name or f"Journée {self.number}"


class Match(TimeStampedModel):
    """Confrontation entre deux participations (ou une participation exempte)."""

    GENERATED = "GENERATED"
    MANUAL = "MANUAL"
    SOURCE_CHOICES = [(GENERATED, "Généré"), (MANUAL, "Manuel")]

    championship = models.ForeignKey(
        "championships.Championship", on_delete=models.CASCADE, related_name="matches"
    )
    division = models.ForeignKey(
        "championships.Division", on_delete=models.PROTECT, related_name="matches"
    )
    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="matches")
    matchday = models.ForeignKey(
        Matchday,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches",
    )
    player1 = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.PROTECT,
        related_name="matches_as_p1",
    )
    player2 = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches_as_p2",
        help_text="Vide = joueur exempt (bye).",
    )
    pair_key = models.CharField(max_length=40, editable=False, db_index=True)
    leg = models.PositiveSmallIntegerField("manche", default=1)

    scheduled_date = models.DateField("date prévue", null=True, blank=True)
    scheduled_time = models.TimeField("heure prévue", null=True, blank=True)
    played_at = models.DateTimeField("joué le", null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=MatchStatus.choices,
        default=MatchStatus.SCHEDULED,
        db_index=True,
    )
    result_status = models.CharField(
        max_length=16,
        choices=ResultStatus.choices,
        default=ResultStatus.NONE,
        db_index=True,
    )
    outcome_type = models.CharField(
        max_length=16, choices=OutcomeType.choices, default=OutcomeType.NORMAL
    )

    score1 = models.IntegerField("score joueur 1", null=True, blank=True)
    score2 = models.IntegerField("score joueur 2", null=True, blank=True)
    winner = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches_won",
    )

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches_entered",
    )
    entered_at = models.DateTimeField(null=True, blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    referee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches_refereed",
    )

    postponed_from = models.DateField(null=True, blank=True)
    reschedule_count = models.PositiveSmallIntegerField(default=0)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default=GENERATED)
    notes = models.TextField(blank=True)
    counts_for_standings = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "match"
        verbose_name_plural = "matchs"
        ordering = ["championship", "division", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(player2__isnull=True)
                    | ~models.Q(player1=models.F("player2"))
                ),
                name="match_no_self_play",
            ),
            models.UniqueConstraint(
                fields=["phase", "leg", "pair_key"],
                name="uniq_match_pair_per_phase_leg",
            ),
        ]
        indexes = [
            models.Index(fields=["championship", "division", "status"]),
            models.Index(fields=["result_status"]),
            models.Index(fields=["scheduled_date"]),
        ]

    def __str__(self):
        p2 = self.player2.player if self.player2_id else "Exempt"
        return f"{self.player1.player} vs {p2}"

    def save(self, *args, **kwargs):
        ids = sorted(i for i in (self.player1_id, self.player2_id) if i)
        if len(ids) == 2:
            self.pair_key = f"{ids[0]}-{ids[1]}"
        elif ids:
            self.pair_key = f"bye-{ids[0]}"
        if self.phase_id and not self.championship_id:
            self.championship_id = self.phase.championship_id
        super().save(*args, **kwargs)


class ResultSubmission(TimeStampedModel):
    """Déclaration brute d'un résultat. Le ``Match`` ne porte qu'un seul résultat
    officiel ; ces saisies sont réconciliées par ``services.result``."""

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="submissions")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="result_submissions",
    )
    submitted_by_participation = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="result_submissions",
    )
    score1 = models.IntegerField("score joueur 1")
    score2 = models.IntegerField("score joueur 2")
    claimed_winner = models.ForeignKey(
        "participations.ChampionshipParticipation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    outcome_type = models.CharField(
        max_length=16, choices=OutcomeType.choices, default=OutcomeType.NORMAL
    )
    source = models.CharField(max_length=12, choices=SubmissionSource.choices)
    note = models.TextField(blank=True)
    is_superseded = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "saisie de résultat"
        verbose_name_plural = "saisies de résultat"
        ordering = ["match", "submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["match", "submitted_by"],
                condition=models.Q(is_superseded=False),
                name="uniq_active_submission_per_user_match",
            ),
        ]

    def __str__(self):
        return f"{self.match} : {self.score1}-{self.score2}"


class TieResolution(TimeStampedModel):
    """Décision humaine sur une égalité que la chaîne de départage ne tranche pas."""

    championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.CASCADE,
        related_name="tie_resolutions",
    )
    division = models.ForeignKey(
        "championships.Division", on_delete=models.CASCADE, related_name="tie_resolutions"
    )
    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="tie_resolutions")
    participations = models.ManyToManyField(
        "participations.ChampionshipParticipation", related_name="tie_resolutions"
    )
    ordered_result = models.JSONField(
        default=list, help_text="Liste ordonnée d'identifiants de participations."
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tie_resolutions",
    )
    reason = models.TextField(blank=True)

    class Meta:
        verbose_name = "résolution d'égalité"
        verbose_name_plural = "résolutions d'égalité"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Égalité {self.division} — {self.championship}"
