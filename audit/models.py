from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class AuditLog(models.Model):
    """Trace immuable des opérations critiques (aucune modification / suppression
    applicative)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    actor_label = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=64, db_index=True)

    target_content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    target_object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_content_type", "target_object_id")
    target_repr = models.CharField(max_length=255, blank=True)

    championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    changes = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "entrée d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_content_type", "target_object_id"]),
            models.Index(fields=["championship", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} · {self.actor_label or 'système'} · {self.action}"
