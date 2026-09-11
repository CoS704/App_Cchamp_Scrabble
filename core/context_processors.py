def admin_nav(request):
    """Affiche l'entrée « Administration » de la navbar aux utilisateurs
    ayant au moins un rôle de gestion. Les vérifications réelles restent
    côté serveur (voir core.permissions) — ceci ne fait qu'orienter l'UI."""
    user = getattr(request, "user", None)
    show = False
    if user is not None and getattr(user, "is_authenticated", False):
        show = (
            user.is_superuser
            or user.groups.filter(name__in=["Super Admin", "Admin Championnat"]).exists()
            or user.staff_roles.filter(is_active=True).exists()
        )
    return {"show_admin_nav": show}


def unread_notifications(request):
    """Compteur de notifications non lues, affiché en badge dans la navbar."""
    user = getattr(request, "user", None)
    count = 0
    if user is not None and getattr(user, "is_authenticated", False):
        count = user.notifications.filter(is_read=False).count()
    return {"unread_notifications_count": count}
