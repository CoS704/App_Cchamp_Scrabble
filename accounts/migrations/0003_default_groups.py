"""Crée les groupes de rôles applicatifs (§39) et leurs permissions Django.

Ces groupes couvrent l'admin Django (étape 58) et servent de deuxième voie
d'accès « Super Admin » à côté de ``User.is_superuser``. Les vérifications
métier fines restent dans ``core.permissions`` / ``core.permissions``
mixins — ceci ne fait que cadrer ce que l'admin Django expose par rôle.
"""
from django.db import migrations

SUPER_ADMIN_APPS = [
    "accounts",
    "players",
    "championships",
    "participations",
    "competition",
    "rankings",
    "finals",
    "transitions",
    "notifications",
    "audit",
]

ADMIN_CHAMPIONNAT_PERMS = {
    "players": {"player": ["add", "change", "view"]},
    "championships": {
        "competitionseries": ["add", "change", "view"],
        "championship": ["add", "change", "view"],
        "championshipsettings": ["add", "change", "view"],
        "division": ["add", "change", "view"],
        "championshiptiebreak": ["add", "change", "view"],
        "promotionrelegationrule": ["add", "change", "view"],
    },
    "participations": {"championshipparticipation": ["add", "change", "view"]},
    "competition": {
        "phase": ["add", "change", "view"],
        "matchday": ["add", "change", "view"],
        "match": ["add", "change", "view"],
        "resultsubmission": ["add", "change", "view"],
        "tieresolution": ["add", "change", "view"],
    },
    "rankings": {"standingsnapshot": ["view"], "standingrow": ["view"]},
    "finals": {"bracket": ["add", "change", "view"], "bracketslot": ["add", "change", "view"]},
    "transitions": {
        "seasontransition": ["add", "change", "view"],
        "seasontransitionmove": ["add", "change", "view"],
    },
    "notifications": {"notification": ["add", "view"]},
    "accounts": {"championshipstaff": ["add", "change", "view"]},
    "audit": {"auditlog": ["view"]},
}

ARBITRE_PERMS = {
    "championships": {"championship": ["view"], "division": ["view"]},
    "participations": {"championshipparticipation": ["view"]},
    "competition": {
        "match": ["change", "view"],
        "resultsubmission": ["add", "change", "view"],
        "tieresolution": ["add", "view"],
    },
    "rankings": {"standingsnapshot": ["view"], "standingrow": ["view"]},
    "notifications": {"notification": ["view"]},
}

GROUP_NAMES = ["Super Admin", "Admin Championnat", "Arbitre"]


def _ensure_content_types_and_permissions(using):
    """ContentType/Permission sont normalement créés par le signal
    ``post_migrate`` à la toute fin de la commande ``migrate`` — trop tard
    pour cette migration de données. On les force ici pour les apps
    concernées (technique standard pour une migration de permissions)."""
    from django.apps import apps as global_apps
    from django.contrib.auth.management import create_permissions
    from django.contrib.contenttypes.management import create_contenttypes

    for app_config in global_apps.get_app_configs():
        create_contenttypes(app_config, verbosity=0, using=using)
        create_permissions(app_config, verbosity=0, using=using)


def _permissions_for(Permission, ContentType, using, mapping):
    perms = []
    for app_label, models in mapping.items():
        for model_name, actions in models.items():
            try:
                ct = ContentType.objects.using(using).get(
                    app_label=app_label, model=model_name
                )
            except ContentType.DoesNotExist:
                continue
            codenames = [f"{action}_{model_name}" for action in actions]
            perms.extend(
                Permission.objects.using(using).filter(
                    content_type=ct, codename__in=codenames
                )
            )
    return perms


def create_default_groups(apps, schema_editor):
    using = schema_editor.connection.alias
    _ensure_content_types_and_permissions(using)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    super_admin, _ = Group.objects.using(using).get_or_create(name="Super Admin")
    super_admin.permissions.set(
        Permission.objects.using(using).filter(
            content_type__app_label__in=SUPER_ADMIN_APPS
        )
    )

    admin_championnat, _ = Group.objects.using(using).get_or_create(
        name="Admin Championnat"
    )
    admin_championnat.permissions.set(
        _permissions_for(Permission, ContentType, using, ADMIN_CHAMPIONNAT_PERMS)
    )

    arbitre, _ = Group.objects.using(using).get_or_create(name="Arbitre")
    arbitre.permissions.set(
        _permissions_for(Permission, ContentType, using, ARBITRE_PERMS)
    )


def remove_default_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).filter(
        name__in=GROUP_NAMES
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("players", "0001_initial"),
        ("championships", "0001_initial"),
        ("participations", "0001_initial"),
        ("competition", "0001_initial"),
        ("rankings", "0001_initial"),
        ("finals", "0001_initial"),
        ("transitions", "0001_initial"),
        ("notifications", "0001_initial"),
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_groups, remove_default_groups),
    ]
