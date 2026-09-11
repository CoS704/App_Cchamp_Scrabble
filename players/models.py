from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import TimeStampedModel


class Player(TimeStampedModel):
    """Identité du compétiteur, découplée du compte de connexion.

    Un joueur peut être créé ou importé par un administrateur avant d'avoir un
    compte ; le lien ``user`` est optionnel et peut être ajouté plus tard.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="player",
    )
    first_name = models.CharField("prénom", max_length=100)
    last_name = models.CharField("nom", max_length=100)
    display_name = models.CharField("nom affiché", max_length=120, blank=True)
    scrabblego_id = models.CharField(
        "identifiant ScrabbleGO",
        max_length=64,
        blank=True,
        help_text=(
            "Identifiant unique du joueur sur l'application ScrabbleGO, affiché "
            "publiquement (classements, adversaires) pour permettre aux joueurs "
            "de s'y retrouver d'une division à l'autre."
        ),
    )
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    photo = models.ImageField(upload_to="players/", blank=True, null=True)
    birth_date = models.DateField("date de naissance", null=True, blank=True)
    country = models.CharField("pays", max_length=64, blank=True)
    club = models.CharField("club", max_length=120, blank=True)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField("actif", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="players_created",
    )

    class Meta:
        verbose_name = "joueur"
        verbose_name_plural = "joueurs"
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["is_active"])]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        return self.display_name or f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.first_name}-{self.last_name}") or "joueur"
            slug, n = base, 2
            while Player.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)
