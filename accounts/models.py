from django.contrib.auth.models import AbstractUser
from django.db import models

from core.enums import StaffRole
from core.models import TimeStampedModel


class User(AbstractUser):
    """Compte de connexion. L'identité *compétiteur* vit dans ``players.Player``."""

    email = models.EmailField("adresse e-mail", unique=True)
    photo = models.ImageField("photo", upload_to="avatars/", blank=True, null=True)
    phone = models.CharField("téléphone", max_length=32, blank=True)

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"

    def __str__(self):
        return self.get_full_name() or self.get_username()


class ChampionshipStaff(TimeStampedModel):
    """Rôle d'administration ou d'arbitrage cadré à une édition (et éventuellement
    à certaines divisions pour un arbitre)."""

    championship = models.ForeignKey(
        "championships.Championship", on_delete=models.CASCADE, related_name="staff"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_roles")
    role = models.CharField(max_length=16, choices=StaffRole.choices)
    divisions = models.ManyToManyField(
        "championships.Division",
        blank=True,
        related_name="staff",
        help_text="Vide = toutes les divisions de l'édition.",
    )
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_assignments_made",
    )

    class Meta:
        verbose_name = "membre du staff"
        verbose_name_plural = "staff du championnat"
        constraints = [
            models.UniqueConstraint(
                fields=["championship", "user", "role"],
                name="uniq_staff_role_per_championship",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} ({self.championship})"
