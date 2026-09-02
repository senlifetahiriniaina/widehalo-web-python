# Écart d'architecture — Budget déclaré vs état réel du dépôt

Produit dans le cadre du **Sprint 0** de `docs/planning/2026-refonte-ux-sprints.md`,
en réponse à l'« Action requise de Claude Code en préambule » du cahier des charges
WideHalo v3 (refonte UX) : ce document remplace les hypothèses du cahier des charges
par l'état réel, mesuré, du dépôt `widehalo-web-python`.

## 0. Constat principal : le dépôt est plus avancé que ce que suppose le cahier des
   charges — et un garde-fou de budget existe déjà

Deux découvertes changent la lecture du cahier des charges :

1. **`README.md` est obsolète.** Il annonce que ce dépôt ne livre que le « Lot 1 »
   (socle transversal, *« aucun module métier complet n'est livré »*). C'est faux à ce
   jour : l'historique de décisions dans `config/settings/base.py` (commentaires
   au-dessus de `BUDGET_MAX_MODELS`/`BUDGET_MAX_SCREENS`) documente la clôture
   effective de modules métier complets — `stocks`, `presence`, `payroll`, `projects`,
   `purchase`, `helpdesk` — et le démarrage du **« Lot 2 Madagascar »**, chaque
   relèvement de plafond étant une **décision explicite actée avec l'utilisateur**.
   Le cahier des charges de refonte UX a donc été rédigé sur une image du dépôt
   antérieure à son état réel.
2. **Le garde-fou anti-dérive demandé par le cahier des charges (§B.9) existe déjà.**
   `widehalo/tests/architecture/test_budget.py` + `BUDGET_MAX_MODELS` /
   `BUDGET_MAX_ENDPOINTS` / `BUDGET_MAX_SCREENS` dans `config/settings/base.py`
   font tourner en CI (job `architecture-tests`) exactement le test que le Sprint 0
   du planning UX prévoyait de créer. **Rien à créer ici** — ce rapport documente
   l'état actuel de ce garde-fou plutôt que d'en construire un doublon.

Conséquence pour le planning des sprints suivants (L0–L7) : la migration UX
« strangler pattern » va porter sur un périmètre d'écrans existants **nettement plus
large** que ce que le cahier des charges laissait supposer (des modules entiers déjà
en production avec l'ancienne UI, pas seulement les fondations). C'est un point à
rouvrir avec l'utilisateur avant de lancer L1 — signalé en §7.

## 1. Méthode

Mesure par introspection Django directe, en réutilisant **exactement** les fonctions
de comptage de `tests/architecture/test_budget.py` (`_counted_models`,
`_counted_endpoints`, `_counted_screens`) pour que ce rapport et le test CI ne
divergent jamais sur la définition d'un « modèle », d'un « endpoint » ou d'un
« écran ».

```bash
cd widehalo
DJANGO_SETTINGS_MODULE=config.settings.test python -c "
import django; django.setup()
from tests.architecture.test_budget import _counted_models, _counted_endpoints, _counted_screens
print(len(_counted_models()), _counted_endpoints(), _counted_screens())
"
```

## 2. Résultats mesurés (2026-09-02, HEAD `madagascar1`)

| Compteur | Budget déclaré (CDC v1, historique) | Budget recommandé par le CDC refonte (§B.9) | **Plafond CI réel actuel** (`config/settings/base.py`) | **Mesure réelle actuelle** | Marge |
|---|---|---|---|---|---|
| Modèles | 180 | 200 | **290** | **254** | 36 |
| Endpoints (django-ninja) | 600 | 650 | **600** | **515** | 85 |
| Écrans (`.html`, hors `components/`/`layout/`/`_partial.html`) | 90 | 110 | **240** | **217** | 23 |

Le plafond « modèles » a déjà été relevé cinq fois (180 → 220 → 250 → 265 → 290) et
celui des « écrans » trois fois (90 → 200 → 215 → 240) au fil des modules métier
livrés, chaque relèvement documenté et justifié en commentaire — **jamais** en dérive
silencieuse. Le plafond « endpoints » n'a jamais eu besoin d'être relevé (515/600).

Répartition des modèles par app (méthodologie `_counted_models`, apps WideHalo
uniquement) :

| App | Modèles | App | Modèles |
|---|---|---|---|
| accounting | 40 | patronage | 11 |
| catalog | 20 | payroll | 11 |
| core | 28 | presence | 10 |
| mrp | 18 | projects | 11 |
| stocks | 18 | purchase | 16 |
| logistics | 17 | sales | 8 |
| helpdesk | 13 | crm | 8 |
| ai | 6 | financing | 6 |
| automation | 4 | strategy | 5 |
| chat | 3 | reporting | 5 |
| partners | 3 | feasibility | 2 |

`accounting` (40) et `core` (28) concentrent plus d'un quart du total. C'est
cohérent avec le périmètre du cahier des charges : `accounting` porte déjà
l'essentiel du référentiel comptable que le lot L5 doit finir d'abstraire
(PCG 2005/SYSCOHADA), et `core` porte une bonne partie des tables transverses
listées en B.3 — `ui_view_definition`, `mail_message`/`mail_activity`/`mail_follower`,
`core_notification`, `core_workflow_state`/`_transition`, `core_audit_log`,
`core_regulatory_parameter` — **déjà présentes** dans `apps/core/models/` sous des
noms parfois différents. Le lot L0/L2 doit les **auditer et réutiliser**, pas les
recréer (voir §4).

## 3. Endpoints — vue complémentaire (hors plafond CI)

Le plafond CI ne compte que les opérations django-ninja (515/600). Le dépôt expose
en plus des vues Django classiques (rendu de templates, fragments HTMX), non
couvertes par ce plafond :

| | Compte |
|---|---|
| Fichiers `apps/*/urls.py` | 22 |
| Motifs `path()`/`re_path()` dans ces fichiers | 338 |

Ces 338 vues classiques sont la matière des « fragments HTMX » anticipés par le
cahier des charges (B.9) sans être chiffrés — à surveiller si le lot L1 (data grid
universel, HTMX) en ajoute significativement ; elles ne comptent pas contre
`BUDGET_MAX_ENDPOINTS` aujourd'hui, ce périmètre est à trancher explicitement plutôt
que laissé implicite (recommandation §6).

## 4. Moteur de workflow (django-fsm-2) — déjà en usage

| | Compte |
|---|---|
| Champs `FSMField` | 19 |
| Fichiers référençant `FSMField` | 43 |
| Transitions déclarées (`@transition`) | 114 |

Un moteur d'états est déjà largement utilisé (19 champs, 114 transitions), avec son
propre garde-fou CI (`tests/architecture/test_attempt_transition_saves_state.py`).
Le lot L2 (« moteur de workflow/états ») du cahier des charges doit **s'appuyer**
sur cet existant plutôt que le dupliquer.

## 5. Bibliothèque de composants — déjà amorcée

`templates/components/` contient déjà des composants réutilisables cités par le
cahier des charges lui-même (`_kpi_row.html`, `_smart_table.html`,
`_side_panel.html`, `_partner_picker.html`, `_wizard_steps.html`,
`_instant_search_results.html`) plus d'autres non cités. Le lot L0 (« bibliothèque
de composants à construire ») doit les **faire évoluer vers `django-cotton`**
plutôt que partir d'une page blanche — voir la bascule de socle réalisée dans ce
même Sprint 0 (`widehalo/templates/cotton/`).

## 6. Recommandations

1. **Ne pas créer de second test de budget.** `tests/architecture/test_budget.py`
   reste la source de vérité unique ; ce rapport documente son état, il ne le
   remplace pas. Seul ajustement apporté dans ce Sprint 0 :
   `_counted_screens()` exclut désormais aussi `templates/cotton/` (au même
   titre que `components/`/`layout/`) — la bibliothèque de composants
   django-cotton introduite par ce sprint n'est pas des écrans autonomes.
   Mesure après ajustement : **254 modèles / 515 endpoints / 218 écrans**,
   toujours confortablement sous les plafonds CI (290/600/240).
2. **Mettre à jour `README.md`** pour refléter l'état réel du dépôt (Lot 2 Madagascar
   en cours, modules métier déjà livrés) — fait dans ce Sprint 0 (voir diff).
3. **Trancher le périmètre du plafond « endpoints »** : inclure ou non les 338 vues
   classiques/fragments HTMX. Proposition : les compter séparément
   (`BUDGET_MAX_HTMX_VIEWS`) plutôt que les fusionner avec le plafond django-ninja,
   pour ne pas perdre le signal actuel (515/600 est un signal utile en l'état) —
   décision à valider avec l'utilisateur avant le lot L1.
4. **Auditer `apps/core/models/`** en tout début de lot L0/L2 pour cartographier
   précisément les tables transverses déjà présentes face à celles listées en B.3
   du cahier des charges, avant d'écrire la moindre migration.

## 7. Conséquence sur `docs/planning/2026-refonte-ux-sprints.md`

Ce rapport devient, conformément au cahier des charges, **le point de vérité qui
remplace les hypothèses** du planning de sprints. Deux ajustements sont à valider
avec l'utilisateur avant de lancer le Sprint 1 (L0) :

- Le périmètre de la migration « strangler pattern » couvre davantage d'écrans
  existants (Lot 2 Madagascar déjà livré : stocks, presence, payroll, projects,
  purchase, helpdesk) que ne le suggérait le cahier des charges — l'effort de
  migration (raffinement UX par écran, pas juste construction) est probablement
  sous-estimé dans les 71 JT initiaux pour ces lots.
- Le plafond « endpoints » (§6.3) doit être tranché avant que le lot L1 (data grid
  universel HTMX) ne commence à en ajouter en nombre.

Aucun changement n'est nécessaire dans l'immédiat : les écarts modèles/endpoints
reflètent un existant riche (bon signal), pas une dérive à corriger.
