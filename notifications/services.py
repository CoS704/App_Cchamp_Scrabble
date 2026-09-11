"""Génération des notifications (§40)."""
from __future__ import annotations

from core.enums import NotificationKind, NotificationPriority

from .models import Notification


def notify(*, recipient_id, kind, title, body="", championship=None, link_url="", data=None, priority=NotificationPriority.NORMAL):
    if not recipient_id:
        return None
    return Notification.objects.create(
        recipient_id=recipient_id,
        championship=championship,
        kind=kind,
        title=title,
        body=body,
        link_url=link_url,
        data=data or {},
        priority=priority,
    )


def championship_admin_user_ids(championship):
    """Comptes à notifier pour les événements nécessitant une action
    d'administration sur cette édition : administrateurs globaux (Super
    Admin / Admin Championnat) et staff ``ADMIN`` actif de l'édition —
    jamais les arbitres cadrés à une seule division (§40, §22)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    global_admin_ids = User.objects.filter(
        Q(is_superuser=True) | Q(groups__name__in=["Super Admin", "Admin Championnat"]),
        is_active=True,
    ).values_list("id", flat=True)
    staff_admin_ids = championship.staff.filter(role="ADMIN", is_active=True).values_list(
        "user_id", flat=True
    )
    return set(global_admin_ids) | set(staff_admin_ids)


_RESULT_EVENTS = {
    "submitted": (
        NotificationKind.RESULT_NEEDS_CONFIRMATION,
        "Résultat à confirmer",
        NotificationPriority.NORMAL,
    ),
    "confirmed": (
        NotificationKind.RESULT_RECORDED,
        "Résultat confirmé",
        NotificationPriority.NORMAL,
    ),
    "validated": (
        NotificationKind.RESULT_RECORDED,
        "Résultat validé",
        NotificationPriority.NORMAL,
    ),
    "disputed": (
        NotificationKind.RESULT_DISPUTED,
        "Litige sur votre résultat",
        NotificationPriority.HIGH,
    ),
}


def notify_result_event(match, *, event: str, exclude_participation_id=None):
    """Notifie le(s) participant(s) concerné(s) par un changement d'état du
    résultat. ``submitted`` ne notifie que l'adversaire (celui qui doit
    confirmer) ; les autres événements notifient les deux camps."""
    if event not in _RESULT_EVENTS:
        return
    kind, title, priority = _RESULT_EVENTS[event]

    opponent_label = str(match.player2.player) if match.player2 else "Exempt"
    body_by_event = {
        "submitted": f"Un résultat a été saisi pour votre match ({match.player1.player} vs {opponent_label}).",
        "confirmed": "Votre résultat est confirmé, en attente de validation.",
        "validated": f"Votre résultat a été enregistré : {match.score1} - {match.score2}.",
        "disputed": "Les saisies ne correspondent pas : un administrateur ou un arbitre va trancher.",
    }
    body = body_by_event[event]

    for participation in (match.player1, match.player2):
        if not participation or not participation.player.user_id:
            continue
        if exclude_participation_id and participation.id == exclude_participation_id:
            continue
        notify(
            recipient_id=participation.player.user_id,
            championship=match.championship,
            kind=kind,
            title=title,
            body=body,
            data={"match_id": match.id},
            priority=priority,
        )

    if event == "disputed":
        _notify_admins_of_dispute(match)


def _notify_admins_of_dispute(match):
    """Un litige exige une action d'administration : sans ceci, aucune
    notification n'était jamais créée côté admin (seuls les joueurs étaient
    notifiés), qui ne voyait donc jamais rien apparaître dans sa cloche."""
    championship = match.championship
    link_url = f"/gestion/championnats/{championship.slug}/calendrier/?status=DISPUTED"
    p1 = str(match.player1.player) if match.player1 else "Exempt"
    p2 = str(match.player2.player) if match.player2 else "Exempt"
    for admin_user_id in championship_admin_user_ids(championship):
        notify(
            recipient_id=admin_user_id,
            championship=championship,
            kind=NotificationKind.DISPUTE_TO_RESOLVE,
            title="Litige à trancher",
            body=f"Les saisies ne correspondent pas pour {p1} vs {p2} — une décision est requise.",
            link_url=link_url,
            data={"match_id": match.id},
            priority=NotificationPriority.HIGH,
        )
