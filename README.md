# Plateforme de gestion de championnats de Scrabble

Application web (Django 5 + PostgreSQL) pour organiser des championnats de Scrabble
multi-divisions : inscriptions, calendrier round-robin, saisie et validation des
résultats, moteur de classement configurable, promotions / relégations, phases
finales, dashboards administrateur et joueur.

> **État d'avancement** : étape 6 du plan — projet, applications, modèles et
> migrations. La couche de services, les vues et l'UI arrivent aux étapes suivantes.
> La conception détaillée de la base est décrite dans
> [`docs/01-modelisation-bdd.md`](docs/01-modelisation-bdd.md).

## Stack

| Couche | Choix |
|--------|-------|
| Backend | Python 3.12, Django 5.2, Django REST Framework |
| Base de données | PostgreSQL (Neon en production), SQLite en local hors-ligne |
| Frontend | Django templates + Bootstrap 5, Chart.js (étapes UI) |
| Déploiement | Render (web + build), Neon (PostgreSQL) |
| Statiques | WhiteNoise |
| Serveur | Gunicorn |

## Architecture des applications

```
config/          réglages (base / dev / prod), urls, wsgi/asgi
core/            modèles abstraits, énumérations métier, permissions
accounts/        User personnalisé, ChampionshipStaff (rôles par édition)
players/         Player (identité compétiteur, découplée du compte)
championships/   CompetitionSeries, Championship, ChampionshipSettings,
                 Division, ChampionshipTiebreak, PromotionRelegationRule
participations/  ChampionshipParticipation (entité pivot + historique)
competition/     Phase, Matchday, Match, ResultSubmission, TieResolution
rankings/        StandingSnapshot, StandingRow (cache + historique)
finals/          Bracket, BracketSlot
transitions/     SeasonTransition, SeasonTransitionMove (saison suivante)
notifications/   Notification
audit/           AuditLog (trace immuable)
```

## Installation locale

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # puis éditez .env
```

Sans `DATABASE_URL`, l'application utilise SQLite (aucun serveur requis).
Avec une URL Neon, elle utilise PostgreSQL.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Application : http://127.0.0.1:8000/
- Admin Django : http://127.0.0.1:8000/admin/

## Variables d'environnement

| Variable | Rôle | Exemple |
|----------|------|---------|
| `DJANGO_SETTINGS_MODULE` | Module de réglages | `config.settings.dev` / `config.settings.prod` |
| `SECRET_KEY` | Clé secrète Django (obligatoire en prod) | chaîne longue aléatoire |
| `DEBUG` | Mode debug | `True` / `False` |
| `ALLOWED_HOSTS` | Hôtes autorisés (virgules) | `localhost,127.0.0.1` |
| `DATABASE_URL` | Connexion PostgreSQL (vide = SQLite) | `postgres://…@…neon.tech/db?sslmode=require` |
| `CSRF_TRUSTED_ORIGINS` | Origines de confiance CSRF | `https://mon-app.onrender.com` |
| `TIME_ZONE` | Fuseau horaire | `Europe/Paris` |

## Déploiement Render + Neon

1. Créer une base PostgreSQL sur [Neon](https://neon.tech) et récupérer l'URL de connexion (`sslmode=require`).
2. Sur [Render](https://render.com), créer un *Web Service* à partir du dépôt (le fichier `render.yaml` fournit la configuration).
3. Renseigner les variables : `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `DJANGO_SETTINGS_MODULE=config.settings.prod`.
4. `build.sh` installe les dépendances, exécute `collectstatic` puis `migrate`.
5. Démarrage : `gunicorn config.wsgi:application`.

## Commandes utiles

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test
python manage.py createsuperuser
```

## Suite du plan

Services métier (calendrier, résultats, classement, départages, promotions),
dashboards, statistiques et simulations, notifications, tests, `seed_demo`,
optimisation, déploiement. Voir `docs/01-modelisation-bdd.md` §7.
