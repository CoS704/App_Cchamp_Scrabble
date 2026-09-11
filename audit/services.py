"""Point d'entrée unique pour écrire dans le journal d'audit (§55).

Toute opération critique (règles, résultats, promotions…) doit passer par
``log_action`` plutôt que créer un ``AuditLog`` à la main, pour garder une
forme cohérente (acteur, IP, cible) dans tout le projet.
"""
from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from .middleware import get_current_request
from .models import AuditLog


def log_action(
    *,
    action: str,
    actor=None,
    target=None,
    championship=None,
    changes: dict | None = None,
    reason: str = "",
    request=None,
) -> AuditLog:
    request = request or get_current_request()
    ip_address = None
    user_agent = ""
    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
        if actor is None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor = user

    content_type = None
    object_id = ""
    target_repr = ""
    if target is not None:
        content_type = ContentType.objects.get_for_model(target)
        object_id = str(target.pk)
        target_repr = str(target)[:255]

    return AuditLog.objects.create(
        actor=actor,
        actor_label=str(actor) if actor else "système",
        action=action,
        target_content_type=content_type,
        target_object_id=object_id,
        target_repr=target_repr,
        championship=championship,
        changes=changes or {},
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
