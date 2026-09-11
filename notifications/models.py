from django.conf import settings
from django.db import models

from core.enums import NotificationKind, NotificationPriority
from core.models import TimeStampedModel


class Notification(TimeStampedModel):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    championship = models.ForeignKey(
        "championships.Championship",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    kind = models.CharField(
        max_length=32, choices=NotificationKind.choices, default=NotificationKind.GENERIC
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    link_url = models.CharField(max_length=300, blank=True)
    priority = models.CharField(
        max_length=8,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.recipient}"
