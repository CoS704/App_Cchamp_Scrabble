# Plateforme de gestion de championnats de Scrabble

Application web (Django 5 + PostgreSQL) pour organiser des championnats de Scrabble
multi-divisions : inscriptions, calendrier round-robin, saisie et validation des
résultats (anti-double-saisie), moteur de classement configurable (départage,
égalités persistantes), promotions/relégations, phases finales, dashboards
administrateur et joueur, statistiques, simulation « et si », notifications.

> **État d'avancement** : étapes 1 à 22 du plan en 24 étapes (voir
> [`docs/01-modelisation-bdd.md`](docs/01-modelisation-bdd.md) §7). Restent :
> optimisation (23) et exécution du déploiement (24) — la configuration de
> déploiement est prête depuis l'étape 6.

## Stack

| Couche | Choix |
|--------|-------|
| Backend | Python 3.10+, Django 5.2, Django REST Framework |
| Base de données | PostgreSQL (Neon en production/dev), SQLite pour les tests et le mode hors-ligne |
| Frontend | Django templates + Bootstrap 5, Bootstrap Icons, Chart.js |
| Déploiement | Render (web + build), Neon (PostgreSQL) |
| Statiques | WhiteNoise |
| Serveur | Gunicorn |

## Architecture des applications

```
config/          réglages (base / dev / prod / test), urls, wsgi/asgi
core/            modèles abstraits, énumérations métier, permissions, fabriques de tests
accounts/        User personnalisé, ChampionshipStaff (rôles par édition), auth
players/         Player (identité compétiteur, découplée du compte), import CSV
championships/   CompetitionSeries, Championship, ChampionshipSettings, Division,
                 ChampionshipTiebreak, PromotionRelegationRule, seed_demo
participations/  ChampionshipParticipation (entité pivot + historique), inscriptions
competition/     Phase, Matchday, Match, ResultSubmission, TieResolution,
                 génération du calendrier, cycle de vie des matchs, résultats
rankings/        StandingSnapshot, StandingRow (cache + historique), moteur de classement
finals/          Bracket, BracketSlot, tableau à élimination, progression automatique
transitions/     SeasonTransition, SeasonTransitionMove, génération de la saison suivante
dashboard/       Dashboards admin (KPIs, graphiques, alertes) et joueur, simulation
analytics/       Probabilités montée/maintien/relégation, simulation « et si »
notifications/   Notification, commande check_late_matches
audit/           AuditLog (trace immuable de toute action critique)
```

La logique métier vit dans des modules `services.py` (ou `services/`) par
app — jamais dans les templates ni dans les vues, qui restent fines.

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
python manage.py seed_demo      # optionnel : jeu de données de démonstration
python manage.py runserver
```

- Application : http://127.0.0.1:8000/
- Admin Django : http://127.0.0.1:8000/admin/
- Dashboard admin : `/gestion/championnats/<slug>/dashboard/`
- Espace joueur : `/mon-espace/`

## Données de démonstration

```bash
python manage.py seed_demo            # crée un championnat complet
python manage.py seed_demo --reset    # supprime la démo existante puis la régénère
```

Génère 20 joueurs répartis sur 2 divisions, calendrier round-robin complet,
des résultats déjà joués (avec **un litige** et **un forfait** de démonstration
volontaires), quelques matchs volontairement laissés en retard, et les
notifications générées automatiquement par ces événements.

Comptes créés (mot de passe unique, **usage local uniquement**) :

| Compte | Mot de passe | Rôle |
|---|---|---|
| `demo_admin` | `Demo-Pass-1234` | Administrateur (Super Admin) |
| `demo_arbitre` | `Demo-Pass-1234` | Arbitre de l'édition |
| `demo_joueur1` | `Demo-Pass-1234` | Joueur (Alice Bernard, Division 1) |
| `demo_joueur2` | `Demo-Pass-1234` | Joueur (Bastien Petit, Division 1) |

⚠️ Ne jamais utiliser ces identifiants sur une instance exposée publiquement.

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

## Tests

La suite (59 tests) couvre les points du cahier des charges (§60) : génération
de calendrier (invariants round-robin), double saisie/litiges/validation des
résultats, moteur de classement (points, départage, égalités persistantes,
zones de promotion/relégation), phases finales, saison suivante, permissions
et sécurité (un joueur ne peut jamais agir sur les données d'un autre).

```bash
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test
```

> Les tests tournent sur SQLite en mémoire (`config/settings/test.py`), pas sur
> Neon : le connecteur Neon utilisé en dev passe par un pooler PgBouncer
> incompatible avec le cycle CREATE/DROP DATABASE de `manage.py test`. Le code
> applicatif n'utilise aucune fonctionnalité propre à PostgreSQL.

## Commandes utiles

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test
python manage.py createsuperuser
python manage.py seed_demo
python manage.py check_late_matches   # à planifier périodiquement (cron)
```

## Suite du plan

Optimisation (requêtes, index, cache) et exécution du déploiement Render +
Neon. Voir `docs/01-modelisation-bdd.md` §7.
