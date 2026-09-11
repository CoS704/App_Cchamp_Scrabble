"""Modèles abstraits réutilisables."""
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Ajoute des dates de création et de mise à jour à tout modèle."""

    created_at = models.DateTimeField("créé le", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("mis à jour le", auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    """Désactivation logique plutôt que suppression physique."""

    is_deleted = models.BooleanField("supprimé", default=False, db_index=True)
    deleted_at = models.DateTimeField("supprimé le", null=True, blank=True)

    objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def soft_delete(self, *, save=True):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if save:
            self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self, *, save=True):
        self.is_deleted = False
        self.deleted_at = None
        if save:
            self.save(update_fields=["is_deleted", "deleted_at"])
