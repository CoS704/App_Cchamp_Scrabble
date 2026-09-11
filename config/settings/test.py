"""Réglages pour `manage.py test`.

Le connecteur Neon utilisé en développement passe par un *pooler* PgBouncer
(transaction pooling), incompatible avec le cycle CREATE/DROP DATABASE que
`manage.py test` exécute à chaque run. On isole donc les tests sur SQLite en
mémoire : rapide, fiable, aucune dépendance réseau — le code applicatif
n'utilise aucune fonctionnalité propre à PostgreSQL.
"""
from .dev import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
