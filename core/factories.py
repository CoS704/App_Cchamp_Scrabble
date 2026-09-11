"""Fabriques de données réutilisables entre suites de tests.

Ce module ne contient aucun test (nom volontairement hors du motif
``test*.py`` pour ne pas être ramassé par le test runner).
"""
from __future__ import annotations

from championships import services as championship_services
from championships.models import Championship, Division
from core.enums import ParticipationStatus
from participations.models import ChampionshipParticipation
from players.models import Player


def make_user(username, *, group=None, **extra):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=extra.pop("email", f"{username}@example.invalid"),
        password="Test-Pass-12345",
        **extra,
    )
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


def make_player(first_name, last_name, *, user=None, **extra):
    return Player.objects.create(first_name=first_name, last_name=last_name, user=user, **extra)


def make_championship(name="Test Championship", season="0001", **extra):
    championship = Championship.objects.create(name=name, season=season, **extra)
    championship_services.initialize_championship(championship)
    return championship


def make_division(championship, name="Division", level=1, carryover_key="d1", **extra):
    return Division.objects.create(
        championship=championship, name=name, level=level, carryover_key=carryover_key, **extra
    )


def register(championship, player, division, **extra):
    extra.setdefault("status", ParticipationStatus.REGISTERED)
    return ChampionshipParticipation.objects.create(
        championship=championship, player=player, division=division, **extra
    )
