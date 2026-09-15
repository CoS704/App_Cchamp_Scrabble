"""Import de joueurs en masse (§37, §59, §61) et gestion des accès joueur."""
from __future__ import annotations

import csv
import io
import secrets
import string
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.utils.text import slugify


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


REQUIRED_COLUMNS = {"prenom", "nom"}


def import_players_from_csv(file_obj, *, created_by=None) -> ImportReport:
    from .models import Player

    report = ImportReport()
    text_stream = io.TextIOWrapper(file_obj, encoding="utf-8-sig")
    try:
        reader = csv.DictReader(text_stream)
        fieldnames = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
        if not REQUIRED_COLUMNS.issubset(fieldnames):
            report.skipped.append((0, "Colonnes requises manquantes : prenom, nom."))
            return report

        for line_number, row in enumerate(reader, start=2):
            normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            first_name = normalized.get("prenom")
            last_name = normalized.get("nom")
            if not first_name or not last_name:
                report.skipped.append((line_number, "Prénom ou nom manquant."))
                continue
            player = Player.objects.create(
                first_name=first_name,
                last_name=last_name,
                club=normalized.get("club", ""),
                country=normalized.get("pays", ""),
                created_by=created_by,
            )
            report.created.append(player.full_name)
    finally:
        # Détache le buffer sous-jacent pour ne pas fermer le fichier uploadé
        # géré par Django lorsque le TextIOWrapper est libéré.
        text_stream.detach()

    return report


# --- Accès joueur (compte de connexion) -------------------------------------
# Un Player peut exister sans User (inscription à la volée par un admin) ;
# ces fonctions créent/réinitialisent le compte de connexion à partager avec
# le joueur, sans jamais faire transiter le mot de passe en clair ailleurs
# qu'à l'écran de confirmation, une seule fois (§ jamais de secret en base
# hors hash, jamais loggé).

_PASSWORD_ALPHABET = "".join(
    c for c in string.ascii_letters + string.digits if c not in "0OoIl1"
)


def generate_temp_password(length: int = 10) -> str:
    """Mot de passe temporaire lisible (pas de caractères ambigus 0/O/1/l)."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def suggest_username(player) -> str:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    first = slugify(player.first_name)
    last = slugify(player.last_name)
    base = f"{first}.{last}".strip(".") or "joueur"
    username, n = base, 2
    while User.objects.filter(username=username).exists():
        username = f"{base}{n}"
        n += 1
    return username


def suggest_email(username: str) -> str:
    return f"{username}@joueurs.local"


def create_player_login(player, *, username: str, email: str) -> tuple[object, str]:
    """Crée le compte de connexion d'un joueur qui n'en a pas encore.

    Retourne ``(user, mot_de_passe_en_clair)`` — le mot de passe n'est
    disponible qu'à cet instant, jamais reconstituable ensuite (seul son hash
    est conservé)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if player.user_id:
        raise ValidationError("Ce joueur a déjà un compte.")
    if User.objects.filter(username=username).exists():
        raise ValidationError("Cet identifiant est déjà utilisé.")
    if User.objects.filter(email=email).exists():
        raise ValidationError("Cette adresse e-mail est déjà utilisée.")

    password = generate_temp_password()
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=player.first_name,
        last_name=player.last_name,
    )
    player.user = user
    player.save(update_fields=["user"])
    return user, password


def reset_player_login_password(player) -> str:
    """Réinitialise le mot de passe d'un joueur déjà pourvu d'un compte —
    utile en cas de perte, avant de repartager l'accès."""
    if not player.user_id:
        raise ValidationError("Ce joueur n'a pas encore de compte.")
    password = generate_temp_password()
    player.user.set_password(password)
    player.user.save(update_fields=["password"])
    return password
