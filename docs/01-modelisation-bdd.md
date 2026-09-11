# Championnat de Scrabble — Modélisation de la base de données & architecture

> Étapes 2 à 5 du plan de développement : modèle de données, entités / relations /
> cardinalités, règles métier, architecture Django.
> **Aucune ligne de code applicatif n'est encore écrite.** Ce document doit être validé
> avant de passer à l'étape 6 (modèles + migrations).

---

## 0. Principes directeurs (choix structurants pour l'évolutivité et la fiabilité)

| # | Principe | Conséquence concrète |
|---|----------|----------------------|
| P1 | **Toute règle est rattachée à une édition** | `Division`, `ChampionshipSettings`, `ChampionshipTiebreak`, `PromotionRelegationRule`, `ChampionshipStaff`, `Phase` ont tous une FK vers `Championship`. Aucune constante métier dans le code (barème, nb divisions, nb promus…). Les éditions passées restent figées. |
| P2 | **`ChampionshipParticipation` est le pivot** | La division d'un joueur n'existe **que** dans le contexte d'une édition. L'historique, la frise du joueur, la garantie « une seule division par édition », et l'intégrité des matchs passent par cette entité. |
| P3 | **Les matchs référencent des *participations*, pas des *joueurs*** | Impossible de créer un match entre deux personnes qui ne sont pas inscrites dans la même édition et affectées à une division. La division et le championnat du match sont déductibles et vérifiables. |
| P4 | **Séparation « claim » / « résultat officiel »** | `ResultSubmission` = ce que les joueurs déclarent (données brutes, multiples). `Match` = **un seul** résultat officiel, avec un cycle de vie explicite. C'est le rempart anti-double-saisie et anti-litige. |
| P5 | **Le classement est *calculé*, jamais *source de vérité*** | Il est recalculé à partir des matchs `VALIDATED`. On persiste des **snapshots** (`StandingSnapshot` / `StandingRow`) comme *cache + historique* (graphes d'évolution, page publique rapide), régénérables à tout moment. |
| P6 | **Instantané figé en fin d'édition** | `ChampionshipParticipation.final_*` est écrit à la clôture. Changer la méthode de départage en 2029 ne modifie jamais le classement 2026. |
| P7 | **Phases, journées et brackets sont des *données*** | Le format « 1v4 / 2v3 puis finale + petite finale » n'est pas codé en dur. `Phase` / `Matchday` / `Bracket` / `BracketSlot` permettent tout format (élimination directe, barrages, best-of, plus tard double élimination / Elo / équipes). |
| P8 | **Continuité inter-éditions via des clés stables** | `Division.carryover_key` (`"d1"`, `"d2"`…) + `ChampionshipParticipation.source_participation` permettent au moteur « générer la saison suivante » de faire correspondre les divisions d'une édition à l'autre même si les noms changent. |
| P9 | **Rôles cadrés par édition** | `ChampionshipStaff` (admin / arbitre, éventuellement limité à certaines divisions) en plus des groupes Django globaux. Permissions **toujours** vérifiées côté serveur. |
| P10 | **Contraintes en base, pas seulement en Python** | `UniqueConstraint`, `CheckConstraint`, `on_delete` explicites (`PROTECT` pour les données de référence, `CASCADE` uniquement pour les enfants réellement possédés). |
| P11 | **Logique métier dans une couche `services`** | Les modèles restent fins. Le moteur de classement, la génération de calendrier, la réconciliation des résultats, les promotions/relégations, les prédictions sont des modules testables indépendamment de l'UI. |

---

## 1. Cartographie des applications Django

```
config/                 settings (base / dev / prod), urls, wsgi, asgi
core/                   TimeStampedModel, SoftDeleteModel, enums, permissions, mixins, pagination
accounts/               User (custom), ChampionshipStaff, auth (login, reset, profil compte)
players/                Player (identité compétiteur, découplée du compte)
championships/          CompetitionSeries, Championship, ChampionshipSettings, Division,
                        ChampionshipTiebreak, PromotionRelegationRule
participations/         ChampionshipParticipation, import CSV/Excel
competition/            Phase, Matchday, Match, ResultSubmission, TieResolution
                        + services: scheduling, match, result
rankings/               StandingSnapshot, StandingRow + ranking_service
finals/                 Bracket, BracketSlot + bracket_service
transitions/            SeasonTransition, SeasonTransitionMove + promotion_service
analytics/              agrégations dashboard, prediction_service, simulation_service (pas de modèle)
notifications/          Notification + notification_service
audit/                  AuditLog + audit_service
dashboard/              vues fines admin + joueur (assemblent analytics/rankings/...)
api/                    ViewSets DRF (AJAX : simulation, filtres, saisie de résultat)
templates/  static/  media/
```

> Ajustements par rapport à l'arborescence proposée dans le cahier des charges :
> `core` (socle commun) ajouté ; `matches` → `competition` (regroupe phases + journées + matchs
> + résultats) ; `tournaments` → `finals` ; `statistics` fusionné avec les prédictions dans
> `analytics` ; `transitions` isolé (promotions/relégations = workflow à part entière).
> Les `services` vivent dans chaque app (`competition/services/scheduling.py`, etc.).

---

## 2. Modèle de données détaillé

Légende : 🔑 clé / index important · ⚠️ contrainte d'intégrité · *(dérivable)* = non stocké, calculé.

Tous les modèles héritent de `TimeStampedModel` (`created_at`, `updated_at`).

### 2.1 `accounts`

#### `User(AbstractUser)`
| Champ | Type | Notes |
|-------|------|-------|
| `username` | slug | hérité |
| `email` | Email | **unique**, requis 🔑 |
| `first_name`, `last_name` | Char | hérité |
| `photo` | Image | `media/avatars/…`, optionnel |
| `phone` | Char | optionnel |
| `is_active`, `date_joined`, `last_login` | — | hérité |

Rôles globaux via **groupes Django** : `Super Admin`, `Admin Championnat`, `Arbitre`.
Le mot de passe est haché par Django (jamais en clair). Aucun rôle métier stocké en dur sur `User`.

#### `ChampionshipStaff`
Affectation d'un rôle **cadré à une édition** (et éventuellement à des divisions).
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `user` | FK User (CASCADE) | 🔑 |
| `role` | enum `ADMIN` / `REFEREE` | |
| `divisions` | M2M Division | vide = toutes les divisions de l'édition (arbitre global) |
| `is_active` | bool | |
| `assigned_by` | FK User (SET_NULL) | |

⚠️ `unique_together (championship, user, role)`.
⚠️ Les divisions de `divisions` doivent appartenir à `championship` (validation).

---

### 2.2 `players`

#### `Player`
Identité du **compétiteur**, volontairement découplée du compte de connexion :
un admin peut créer / importer des joueurs avant qu'ils n'aient un compte, et l'historique
sportif reste stable même si le compte change.

| Champ | Type | Notes |
|-------|------|-------|
| `user` | OneToOne User (SET_NULL, null) | lien optionnel vers le compte 🔑 |
| `first_name`, `last_name` | Char | |
| `display_name` | Char | nom affiché (peut différer) |
| `slug` | Slug | **unique**, pour la fiche publique 🔑 |
| `photo` | Image | optionnel |
| `birth_date` | Date | optionnel |
| `country` | Char | optionnel |
| `club` | Char | optionnel (entité `Club` = évolution future) |
| `bio` | Text | optionnel |
| `is_active` | bool | désactivation = soft delete |
| `created_by` | FK User (SET_NULL) | |

⚠️ `on_delete=PROTECT` depuis `ChampionshipParticipation` : on ne supprime pas un joueur
qui a une histoire ; on le désactive.

---

### 2.3 `championships`

#### `CompetitionSeries` *(recommandé)*
Regroupe les éditions d'une même compétition récurrente (« Championnat National » →
éditions 2026, 2027…). Sert la navigation, le palmarès et la future plateforme multi-compétitions.
| Champ | Type | Notes |
|-------|------|-------|
| `name` | Char | |
| `slug` | Slug | **unique** |
| `description` | Text | |
| `organizer` | Char | fédération / club / association |
| `is_active` | bool | |

#### `Championship`
Une **édition** précise.
| Champ | Type | Notes |
|-------|------|-------|
| `series` | FK CompetitionSeries (SET_NULL, null) | 🔑 |
| `name` | Char | ex. « Championnat de Scrabble 2026 » |
| `slug` | Slug | **unique** 🔑 |
| `season` | Char | ex. « 2026 » (libre, pas forcément une année) |
| `edition_number` | int | optionnel |
| `description` | Text | |
| `start_date`, `end_date` | Date | prévisionnel |
| `registration_opens_at`, `registration_closes_at` | DateTime | |
| `status` | enum | `DRAFT` → `CONFIGURING` → `REGISTRATION_OPEN` → `SCHEDULED` → `IN_PROGRESS` → `FINALS` → `COMPLETED` → `ARCHIVED` ; `CANCELLED` possible 🔑 |
| `is_inaugural` | bool | 1re édition : tous les joueurs peuvent démarrer dans la division inférieure |
| `rules_locked_at` | DateTime null | verrouillage des règles critiques (§49) |
| `previous_edition` | FK self (SET_NULL, null) | chaînage des éditions |
| `created_by` | FK User (SET_NULL) | |

⚠️ `unique_together (series, season)` (souple : `series` peut être nul).
Suppression bloquée dès que `status >= SCHEDULED` (garde applicative) ; sinon `CASCADE`
vers tous les objets de configuration et de compétition (réellement possédés).

#### `ChampionshipSettings` (OneToOne Championship, CASCADE)
Toutes les règles configurables de l'édition, en un objet auditable d'un bloc.
| Champ | Type | Défaut | Notes |
|-------|------|--------|-------|
| `points_win` | int | 3 | barème (§16) |
| `points_draw` | int | 1 | |
| `points_loss` | int | 0 | |
| `points_forfeit_win` | int | 3 | score technique paramétrable |
| `points_forfeit_loss` | int | 0 | |
| `forfeit_score_for` / `forfeit_score_against` | int | ex. 400 / 0 | score attribué sur forfait |
| `primary_tiebreak` | enum `SCORE_DIFF` / `HEAD_TO_HEAD` | `SCORE_DIFF` | **choix imposé avant chaque championnat (§17)** ; détaille l'ordre via `ChampionshipTiebreak` |
| `round_robin_legs` | int | 1 | 1 = aller simple, 2 = aller-retour (§12) |
| `result_entry_policy` | enum `WINNER_ONLY` / `BOTH_PLAYERS` / `ADMIN_ONLY` | `WINNER_ONLY` | qui saisit (§13) |
| `result_confirmation_required` | bool | true | |
| `double_entry_auto_confirm` | bool | true | si 2 saisies identiques → confirmation auto (§14) |
| `late_match_threshold_days` | int | 3 | seuil « match en retard » (§24) |
| `finals_enabled` | bool | false | |
| `finals_qualifiers_count` | int | 4 | par division |
| `finals_format` | enum / JSON | `SEMI_1V4_2V3` | extensible |
| `finals_third_place` | bool | true | petite finale |
| `carry_over_between_editions` | bool | true | active le workflow promo/relégation vers l'édition suivante |

#### `Division`
**Par édition** (les capacités, le nombre et parfois les noms changent d'une année à l'autre).
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `name` | Char | ex. « Division 1 » |
| `level` | int | 1 = élite ; ordre hiérarchique 🔑 |
| `carryover_key` | slug | ex. `"d1"` — stable d'une édition à l'autre (P8) |
| `capacity_min` | int null | |
| `capacity_max` | int null | `null` = illimité |
| `is_unlimited` | bool | cohérent avec `capacity_max is null` |
| `color` / `theme_key` | Char | identité visuelle (§42) |
| `status` | enum `ACTIVE` / `INACTIVE` | |
| `description` | Text | |
| `params` | JSON | extension |
| *places disponibles* | *(dérivable)* | `capacity_max - inscrits` |
| *inscrits* | *(dérivable)* | `count(participations status ∈ actifs)` |

⚠️ `unique_together` : `(championship, level)`, `(championship, name)`, `(championship, carryover_key)`.
⚠️ `CheckConstraint` : `capacity_min <= capacity_max` quand les deux sont renseignés.
⚠️ Suppression autorisée seulement si `championship.status == DRAFT` (sinon `PROTECT` de fait
via participations/matchs).

#### `ChampionshipTiebreak`
Chaîne ordonnée de critères de départage (le classement primaire par points est implicite).
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `position` | int | 1 = premier critère appliqué |
| `criterion` | enum | `SCORE_DIFF`, `HEAD_TO_HEAD`, `WINS`, `SCORE_FOR`, `SCORE_AGAINST_ASC`, `FORM`, `SEED`, `DRAW_LOTS`, `MANUAL` |
| `is_active` | bool | |

⚠️ `unique_together` : `(championship, position)`, `(championship, criterion)`.
À la création, la chaîne est amorcée selon `primary_tiebreak` :
`[SCORE_DIFF, HEAD_TO_HEAD, WINS, MANUAL]` ou `[HEAD_TO_HEAD, SCORE_DIFF, WINS, MANUAL]`.
`MANUAL` = si on arrive là sans avoir départagé → **égalité persistante signalée**, jamais inventée (§20).
Architecture ouverte : ajouter un critère = ajouter une valeur d'enum + une fonction dans `ranking_service`.

#### `PromotionRelegationRule`
Un mouvement configurable entre deux divisions d'une édition (topologie quelconque, effectifs asymétriques).
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `movement_type` | enum `PROMOTION` / `RELEGATION` | |
| `source_division` | FK Division (PROTECT) | |
| `target_division` | FK Division (PROTECT, null) | `null` = sortie / maintien hors division |
| `method` | enum | `TOP_N`, `BOTTOM_N`, `TOP_PERCENTAGE`, `BOTTOM_PERCENTAGE`, `RANK_RANGE` |
| `value_n` | int null | pour `TOP_N` / `BOTTOM_N` |
| `percentage` | Decimal null | pour `*_PERCENTAGE` |
| `rank_min`, `rank_max` | int null | pour `RANK_RANGE` |
| `priority` | int | ordre d'application quand plusieurs règles interagissent |
| `is_active` | bool | |

⚠️ `CheckConstraint` : le(s) champ(s) de valeur cohérent(s) avec `method` renseigné(s).
⚠️ `source_division` et `target_division` appartiennent au même `championship` ; `source ≠ target`.
Exemple « Division 1, `BOTTOM_N = 2` » → 9e et 10e relégués.

---

### 2.4 `participations`

#### `ChampionshipParticipation`  ← **pivot (P2)**
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `player` | FK Player (PROTECT) | 🔑 |
| `division` | FK Division (PROTECT) | 🔑 |
| `seed` | int null | force / position initiale |
| `status` | enum | `REGISTERED`, `CONFIRMED`, `ACTIVE`, `WITHDRAWN`, `DISQUALIFIED`, `FORFEIT_ALL` |
| `entry_origin` | enum | `NEW`, `PROMOTED_FROM`, `RELEGATED_FROM`, `KEPT`, `MANUAL` (comment le joueur a atterri dans cette division) |
| `source_participation` | FK self (SET_NULL, null) | participation à l'édition précédente → frise du joueur en O(1) |
| `registered_at` | DateTime | |
| `final_rank` | int null | **figé à la clôture** (P6) |
| `final_points`, `final_played`, `final_wins`, `final_draws`, `final_losses` | int null | figés |
| `final_score_for`, `final_score_against`, `final_score_diff` | int null | figés |
| `promotion_outcome` | enum null | `PROMOTED`, `RELEGATED`, `STAYED`, `QUALIFIED_FINALS`, `FINALIST`, `CHAMPION` |
| `resulting_division_carryover_key` | slug null | destination édition suivante (posé par le workflow transitions) |

⚠️ `unique_together (championship, player)` → **un joueur une seule fois par édition, une seule division** (§7).
⚠️ `division.championship_id == championship_id` (validation).
⚠️ `on_delete=PROTECT` depuis `Match` : une participation référencée par un match ne se supprime pas
(on passe `status = WITHDRAWN`).

Frise d'un joueur : `Player → participations` ordonnées par `championship.season`, chaînées par `source_participation`.

---

### 2.5 `competition`

#### `Phase`
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `division` | FK Division (CASCADE, null) | `null` = phase inter-divisions (évolution) |
| `kind` | enum | `LEAGUE`, `SEMI_FINAL`, `FINAL`, `THIRD_PLACE`, `PLAYOFF`, `BARRAGE`, `CUSTOM` |
| `name` | Char | |
| `order` | int | |
| `status` | enum `PENDING` / `IN_PROGRESS` / `COMPLETED` | |
| `config` | JSON | |

⚠️ `unique_together (division, kind, order)` (souple si `division` nul).

#### `Matchday` (journée)
| Champ | Type | Notes |
|-------|------|-------|
| `phase` | FK Phase (CASCADE) | 🔑 |
| `number` | int | |
| `name` | Char | optionnel |
| `scheduled_date` | Date null | |
| `status` | enum `PENDING` / `SCHEDULED` / `IN_PROGRESS` / `COMPLETED` | |

⚠️ `unique_together (phase, number)`.

#### `Match`
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | dénormalisé, filtrage rapide 🔑 |
| `division` | FK Division (PROTECT) | dénormalisé 🔑 |
| `phase` | FK Phase (CASCADE) | 🔑 |
| `matchday` | FK Matchday (SET_NULL, null) | `null` pour un match de bracket |
| `player1` | FK ChampionshipParticipation (PROTECT) | 🔑 |
| `player2` | FK ChampionshipParticipation (PROTECT, null) | `null` = BYE |
| `pair_key` | Char | `"{min(id)}-{max(id)}"` — anti-doublon (généré à la création) 🔑 |
| `leg` | int | 1 / 2 (aller-retour) |
| `bracket_slot` | FK BracketSlot (SET_NULL, null) | |
| `scheduled_date`, `scheduled_time` | Date / Time null | |
| `played_at` | DateTime null | date réelle |
| `status` | enum | `SCHEDULED`, `UPCOMING`, `IN_PROGRESS`, `COMPLETED`, `POSTPONED`, `CANCELLED`, `FORFEIT`, `DISPUTED` 🔑 |
| `result_status` | enum | `NONE` → `SUBMITTED` → `CONFIRMED` → `VALIDATED` ; `DISPUTED`, `REJECTED` 🔑 |
| `outcome_type` | enum | `NORMAL`, `FORFEIT_P1`, `FORFEIT_P2`, `DOUBLE_FORFEIT`, `BYE`, `NOT_PLAYED` |
| `score1`, `score2` | int null | **résultat officiel** (orientation player1/player2) |
| `winner` | FK ChampionshipParticipation (SET_NULL, null) | `null` = nul ou non joué |
| `entered_by` | FK User (SET_NULL, null) | qui a saisi |
| `entered_at` | DateTime null | |
| `validated_by` | FK User (SET_NULL, null) | |
| `validated_at` | DateTime null | |
| `referee` | FK User (SET_NULL, null) | |
| `postponed_from` | Date null | |
| `reschedule_count` | int | |
| `source` | enum `GENERATED` / `MANUAL` | |
| `notes` | Text | |
| `counts_for_standings` | bool | vrai **uniquement** si `result_status == VALIDATED` et `status != DISPUTED` |

⚠️ `CheckConstraint` : `player1_id != player2_id` (pas de match contre soi-même, §11).
⚠️ `UniqueConstraint (phase, leg, pair_key)` pour les phases `LEAGUE` → jamais deux fois la même
confrontation dans une même poule ; les matchs de bracket sont cadrés par `bracket_slot`.
🔑 Index : `(championship, division, status)`, `(matchday)`, `(player1)`, `(player2)`,
`(result_status)`, `(scheduled_date)`.

#### `ResultSubmission`  ← **anti-double-saisie (P4)**
Déclaration brute d'un résultat. Le `Match` ne porte **qu'un seul** résultat officiel ;
les submissions sont les prétentions à réconcilier.
| Champ | Type | Notes |
|-------|------|-------|
| `match` | FK Match (CASCADE) | 🔑 |
| `submitted_by` | FK User (SET_NULL, null) | |
| `submitted_by_participation` | FK ChampionshipParticipation (SET_NULL, null) | `null` si admin/arbitre |
| `score1`, `score2` | int | **toujours** ré-orientés player1/player2 du match |
| `claimed_winner` | FK ChampionshipParticipation (SET_NULL, null) | |
| `outcome_type` | enum | idem `Match` |
| `source` | enum | `PLAYER`, `OPPONENT`, `REFEREE`, `ADMIN`, `IMPORT` |
| `note` | Text | |
| `is_superseded` | bool | une nouvelle saisie du même auteur remplace l'ancienne |
| `submitted_at` | DateTime | |

⚠️ `unique_together (match, submitted_by, is_superseded=False)` via contrainte conditionnelle
→ **une** saisie active par auteur et par match. On conserve tout l'historique.

Réconciliation (`result_service`) :
1. Auteur autorisé ? (`WINNER_ONLY` : seul le vainqueur déclaré ; vérifié **côté serveur**).
2. 1 seule saisie + confirmation non requise → `CONFIRMED`.
3. 2 saisies **identiques** + `double_entry_auto_confirm` → `CONFIRMED` (puis `VALIDATED` selon config).
4. 2 saisies **divergentes** → `Match.result_status = DISPUTED`, `status = DISPUTED`,
   `counts_for_standings = False`, alerte + notifications, **le classement n'est pas touché** (§14).
5. Un admin/arbitre tranche → `VALIDATED` (audité).

#### `TieResolution`
Décision humaine sur une égalité persistante (critère `MANUAL` atteint, §20).
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | |
| `division` | FK Division (CASCADE) | |
| `phase` | FK Phase (CASCADE) | |
| `participations` | M2M ChampionshipParticipation | joueurs concernés |
| `ordered_result` | JSON | ordre décidé `[participation_id, …]` |
| `decided_by` | FK User (SET_NULL) | |
| `reason` | Text | |

Le `ranking_service` applique cette décision comme couche d'override finale. Écrit dans l'`AuditLog`.

---

### 2.6 `rankings` — cache + historique (P5)

#### `StandingSnapshot`
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | 🔑 |
| `division` | FK Division (CASCADE) | 🔑 |
| `phase` | FK Phase (CASCADE) | |
| `as_of_matchday` | FK Matchday (SET_NULL, null) | `null` = état courant |
| `is_current` | bool | un seul `True` par (division, phase) 🔑 |
| `computed_at` | DateTime | |
| `tiebreak_primary_used` | enum | pour l'affichage « Départage : … » |
| `has_unresolved_tie` | bool | |

#### `StandingRow`
| Champ | Type | Notes |
|-------|------|-------|
| `snapshot` | FK StandingSnapshot (CASCADE) | 🔑 |
| `participation` | FK ChampionshipParticipation (CASCADE) | 🔑 |
| `rank` | int | |
| `played`, `wins`, `draws`, `losses` | int | |
| `points` | int | |
| `score_for`, `score_against`, `score_diff` | int | |
| `win_rate` | Decimal | |
| `form` | JSON | ex. `["W","L","W","W","D"]` |
| `tie_group` | int null | marque un cluster d'égalité non départagé |
| `movement_zone` | enum null | `PROMOTION`, `SAFE`, `RELEGATION`, `FINALS` |
| `rank_change` | int | delta vs snapshot précédent |
| `movement_probabilities` | JSON null | `{promotion: .78, safe: .17, relegation: .05}` (posé par `prediction_service`) |

⚠️ `unique_together (snapshot, participation)`.
Le snapshot `is_current` est régénéré après chaque résultat `VALIDATED` ; un snapshot par fin de
journée alimente les graphes d'évolution. **Jamais** source de vérité : `python manage.py rebuild_standings` reconstruit tout depuis les matchs.

---

### 2.7 `finals`

#### `Bracket`
| Champ | Type | Notes |
|-------|------|-------|
| `championship` | FK Championship (CASCADE) | |
| `division` | FK Division (CASCADE, null) | |
| `phase` | FK Phase (CASCADE) | |
| `size` | int | nombre de qualifiés |
| `format` | JSON | `SEMI_1V4_2V3`, `CUSTOM`… |
| `status` | enum | |

#### `BracketSlot`
| Champ | Type | Notes |
|-------|------|-------|
| `bracket` | FK Bracket (CASCADE) | 🔑 |
| `round_index` | int | 0 = premier tour |
| `position` | int | |
| `seed` | int null | |
| `participation` | FK ChampionshipParticipation (SET_NULL, null) | rempli à la qualification |
| `source_slot_win` | FK self (SET_NULL, null) | vainqueur du slot alimente celui-ci |
| `source_slot_lose` | FK self (SET_NULL, null) | perdant → petite finale / (futur double élim.) |
| `match` | FK Match (SET_NULL, null) | |
| `is_third_place` | bool | |

Bracket générique à liens de propagation → toute taille, petite finale, extensions futures.
Pas de format codé en dur (§36).

---

### 2.8 `transitions` — génération de la saison suivante (§10)

#### `SeasonTransition`
| Champ | Type | Notes |
|-------|------|-------|
| `from_championship` | FK Championship (PROTECT) | 🔑 |
| `to_championship` | FK Championship (SET_NULL, null) | créé à la confirmation |
| `status` | enum | `PROPOSED`, `ADJUSTED`, `CONFIRMED`, `CANCELLED` |
| `created_by`, `confirmed_by` | FK User (SET_NULL) | |
| `notes` | Text | |

#### `SeasonTransitionMove`
| Champ | Type | Notes |
|-------|------|-------|
| `transition` | FK SeasonTransition (CASCADE) | 🔑 |
| `source_participation` | FK ChampionshipParticipation (PROTECT) | |
| `player` | FK Player (PROTECT) | |
| `from_carryover_key` | slug | |
| `to_carryover_key` | slug null | `null` = sortie |
| `move_type` | enum | `PROMOTED`, `RELEGATED`, `KEPT`, `MANUAL_OVERRIDE`, `NEW`, `WITHDRAWN` |
| `is_manual_override` | bool | |
| `note` | Text | |

Flux : `promotion_service` calcule la proposition depuis les classements finaux + `PromotionRelegationRule`
→ l'admin ajuste (chaque override tracé) → à la confirmation, création de la nouvelle `Championship`
(structure/settings recopiés comme gabarit) + des `ChampionshipParticipation` avec `entry_origin` et
`source_participation`. Tout est audité.

---

### 2.9 `notifications`

#### `Notification`
| Champ | Type | Notes |
|-------|------|-------|
| `recipient` | FK User (CASCADE) | 🔑 |
| `championship` | FK Championship (SET_NULL, null) | |
| `kind` | enum | `MATCH_TODAY`, `RESULT_RECORDED`, `RESULT_NEEDS_CONFIRMATION`, `RESULT_DISPUTED`, `MATCH_LATE`, `RANK_UPDATE`, `PROMOTION_ZONE`, `RELEGATION_ZONE`, `FINALS_QUALIFIED`, `RULE_CHANGED`, `GENERIC` |
| `title`, `body` | Char / Text | |
| `data` | JSON | |
| `link_url` | Char | |
| `priority` | enum `LOW` / `NORMAL` / `HIGH` | |
| `is_read`, `read_at` | bool / DateTime | |

🔑 Index `(recipient, is_read, created_at)`. Canal e-mail = `NotificationChannelLog` (évolution).

---

### 2.10 `audit`

#### `AuditLog`  (immuable — ni update ni delete applicatif)
| Champ | Type | Notes |
|-------|------|-------|
| `actor` | FK User (SET_NULL, null) | |
| `actor_label` | Char | copie du nom (survit à la suppression du compte) |
| `action` | Char | clé verbe : `RESULT_EDITED`, `RESULT_VALIDATED`, `RULE_CHANGED`, `PLAYER_PROMOTED`, `TIE_RESOLVED`, `SCHEDULE_GENERATED`… |
| `target_content_type` + `target_object_id` | GenericFK | |
| `target_repr` | Char | |
| `championship` | FK Championship (SET_NULL, null) | portée |
| `changes` | JSON | `{champ: [ancienne, nouvelle]}` |
| `reason` | Text | motif d'une modification exceptionnelle (§49) |
| `ip_address`, `user_agent` | — | |

🔑 Index `(championship, created_at)`, `(target_content_type, target_object_id)`, `(actor, created_at)`.

---

### 2.11 `analytics` — pas de modèle

- `prediction_service` : probabilités montée / maintien / relégation par **énumération de scénarios**
  (ou Monte-Carlo borné) sur les matchs restants. Méthode transparente et explicable ; résultat
  éventuellement mis en cache dans `StandingRow.movement_probabilities`. Architecture ouverte à un
  modèle plus fin plus tard.
- `simulation_service` : « et si je gagne mes 2 prochains matchs ? » → recalcul **virtuel** en mémoire,
  **aucune écriture**.
- Agrégations dashboard : `annotate` / `aggregate` + lecture des snapshots.

---

## 3. Cardinalités (synthèse)

```
CompetitionSeries 1 ──< Championship
Championship 1 ──1 ChampionshipSettings
Championship 1 ──< Division
Championship 1 ──< ChampionshipTiebreak
Championship 1 ──< PromotionRelegationRule        (source_division, target_division ─> Division)
Championship 1 ──< ChampionshipStaff >── 1 User   (M2M Division en plus)
Championship 1 ──< ChampionshipParticipation >── 1 Player
Division 1 ──< ChampionshipParticipation
ChampionshipParticipation 0..1 ──< ChampionshipParticipation   (source_participation, auto-référence)
Championship 1 ──< Phase ──< Matchday ──< Match
Division 1 ──< Phase
Match >── 1 ChampionshipParticipation (player1)
Match >── 0..1 ChampionshipParticipation (player2, BYE)
Match 1 ──< ResultSubmission
Match 0..1 ──1 BracketSlot
Phase 1 ──1 Bracket 1 ──< BracketSlot ──(auto-réf. source_slot_win / source_slot_lose)
StandingSnapshot 1 ──< StandingRow >── 1 ChampionshipParticipation
Championship 1 ──< StandingSnapshot
TieResolution >──< ChampionshipParticipation (M2M)
SeasonTransition 1 ──< SeasonTransitionMove
User 1 ──< Notification
User 1 ──< AuditLog (actor)
Player 0..1 ──1 User
```

---

## 4. Contraintes d'intégrité (récapitulatif)

| Sur | Contrainte |
|-----|-----------|
| `ChampionshipParticipation` | `unique(championship, player)` · `division ∈ championship` |
| `Division` | `unique(championship, level)` · `unique(championship, name)` · `unique(championship, carryover_key)` · `capacity_min ≤ capacity_max` |
| `ChampionshipTiebreak` | `unique(championship, position)` · `unique(championship, criterion)` |
| `PromotionRelegationRule` | valeur cohérente avec `method` · `source ≠ target` · même championship |
| `Match` | `player1 ≠ player2` · `unique(phase, leg, pair_key)` sur phases LEAGUE · `player1/2.championship == match.championship` |
| `ResultSubmission` | `unique(match, submitted_by)` parmi les non `is_superseded` |
| `StandingRow` | `unique(snapshot, participation)` |
| `StandingSnapshot` | un seul `is_current=True` par `(division, phase)` |
| `ChampionshipStaff` | `unique(championship, user, role)` |
| `on_delete` | `PROTECT` : Player, ChampionshipParticipation, Division (référencées) · `CASCADE` : enfants possédés (settings, rows, submissions…) · `SET_NULL` : acteurs (`entered_by`, `actor`, `Player.user`…) |

---

## 5. Règles métier centralisées (couche `services`)

| Service | Responsabilités |
|---------|-----------------|
| `championship_service` | création d'édition, amorçage settings + chaîne de départage + divisions, **verrou des règles** (`rules_locked_at`), modification exceptionnelle avec `reason` obligatoire → audit |
| `registration_service` | inscription / retrait, contrôle de capacité (`capacity_max`), édition inaugurale (tout le monde en division inférieure), import CSV/Excel, attribution de seed |
| `scheduling_service` | génération round-robin (méthode du cercle), `N(N-1)/2` matchs, `round_robin_legs`, nb de journées, zéro doublon, zéro auto-match, report / reprogrammation |
| `match_service` | transitions de statut, gestion forfait / abandon / annulation / non-joué, détection des matchs en retard (`late_match_threshold_days`) |
| `result_service` | autorisation de saisie **côté serveur**, réconciliation des `ResultSubmission`, cycle `SUBMITTED→CONFIRMED→VALIDATED`, `DISPUTED`, résolution admin |
| `ranking_service` | agrégation depuis les matchs `VALIDATED` uniquement ; tri `points ↓` puis chaîne `ChampionshipTiebreak` ; `HEAD_TO_HEAD` = mini-championnat entre ex æquo ; `MANUAL` → `tie_group` + alerte, **pas de classement inventé** ; application des `TieResolution` ; production du `StandingSnapshot` courant + snapshots par journée ; calcul des `movement_zone` via `PromotionRelegationRule` |
| `bracket_service` | génération et propagation du bracket (qualifiés, petite finale) |
| `promotion_service` | proposition de la saison suivante depuis les classements finaux + règles ; application des overrides ; création de l'édition + participations |
| `prediction_service` | probabilités montée/maintien/relégation (scénarios explicites) |
| `simulation_service` | recalcul virtuel « et si… », sans écriture |
| `notification_service` | génération des notifications sur événements (match du jour, résultat à confirmer, litige, zone de relégation…) |
| `audit_service` | écriture centralisée de l'`AuditLog` (helper + décorateurs sur les opérations critiques) |

**Ordre de recalcul après un résultat `VALIDATED`** : stats agrégées → classement (snapshot courant) →
zones montée/descente → probabilités → KPIs dashboard → notifications.

---

## 6. Points de conception à impact fort — justification

1. **`Division` par édition (et non globale).** Les capacités, le nombre, parfois les noms
   changent chaque année (§4-5) ; une édition passée doit rester exactement telle qu'elle était (§49).
   `carryover_key` assure la continuité inter-éditions sans coupler les structures.
2. **`ChampionshipParticipation` comme pivot.** Modéliser la division sur le `Player` casserait
   l'historique (§3). Ici, la frise « 2026 → D2 / 2027 → D1 / … » est native, la contrainte
   « une division par édition » est garantie en base, et `source_participation` donne la généalogie.
3. **Matchs liés aux participations.** Garantit par référence que les deux adversaires sont inscrits
   dans la même édition et affectés à une division — impossible de fabriquer un match incohérent.
4. **`ResultSubmission` distinct du résultat officiel.** Le cas « les deux joueurs saisissent » (§14)
   devient trivial : on compare des claims, on n'a jamais deux résultats concurrents. Le litige est
   un état, pas une anomalie de données. Traçabilité complète.
5. **Classement calculé + snapshots.** Respecte « ne rien stocker d'inutile » et « recalculable
   depuis les résultats validés » (§21, §50), tout en offrant des graphes d'évolution instantanés et
   une page publique rapide même avec des milliers de matchs (§56). Le snapshot est un cache, jamais
   une vérité : aucune dérive possible.
6. **`final_*` figés + départage par édition.** Le choix de départage 2029 ne peut pas réécrire le
   classement 2026 (§17). Les anciennes éditions portent leurs propres règles.
7. **Phases / journées / brackets = données.** Ouvre la voie aux évolutions listées au §63
   (élimination directe, barrages, best-of, équipes, Elo, compétitions simultanées) sans refonte.
8. **Rôles cadrés par édition** (`ChampionshipStaff`) + permissions Django vérifiées serveur (§39, §57)
   — cacher un bouton ne suffit jamais.
9. **Contraintes en base.** `unique`, `check`, `on_delete` explicites : l'intégrité ne dépend pas
   de la discipline applicative.

---

## 7. Suite du plan (après validation de ce document)

| Étape | Livrable |
|-------|----------|
| 6 | Scaffold projet (`config` multi-settings, `.env.example`, `requirements.txt`, `build.sh`, `Procfile`), app `core`, `User` custom, modèles + migrations de toutes les apps |
| 7 | Auth + permissions (groupes, `ChampionshipStaff`, helpers `core.permissions`) |
| 8-9 | Championnats, divisions, settings, chaîne de départage, règles promo/relégation ; inscriptions + import |
| 10-11 | `scheduling_service` (round-robin) + gestion des matchs |
| 12-14 | Soumission/validation des résultats + `ranking_service` + départages |
| 15-16 | Phases finales (bracket) + `transitions` (saison suivante) |
| 17-19 | Dashboards admin & joueur, `analytics`, simulation |
| 20-24 | Notifications, tests, `seed_demo`, optimisation, déploiement Render + Neon |

---

## 8. Décisions prises par défaut — à confirmer / ajuster

1. **`CompetitionSeries`** ajouté (regroupe les éditions d'une même compétition). Utile pour le
   palmarès et la future multi-compétition ; supprimable si tu préfères des championnats « à plat ».
2. **`Division` par édition** (pas de table globale réutilisable). Recommandé — dis-moi si tu veux
   un `DivisionTemplate` global en complément pour accélérer la création.
3. **`Match` → FK vers `ChampionshipParticipation`** (et non `Player`). Choix d'intégrité fort ;
   alternative possible = FK `Player` + `championship` (plus simple à requêter, moins sûr).
4. **Snapshots de classement persistés** (cache + historique) plutôt qu'un simple recalcul à la volée.
5. **Chaîne de départage = table ordonnée** `ChampionshipTiebreak` (et non un simple champ). Plus
   verbeux mais auditable et extensible (§20).
6. **Départage `HEAD_TO_HEAD` à ≥ 3 joueurs** = mini-championnat entre les seuls ex æquo, puis
   critère suivant de la chaîne si non résolu, puis `MANUAL`.
7. **App `matches` renommée `competition`** et `analytics` fusionne statistiques + prédictions.
