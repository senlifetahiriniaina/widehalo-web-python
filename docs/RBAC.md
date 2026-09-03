# Contrôle d'accès par rôle (RBAC) : niveaux, rôles, matrice et scoping

Ce document décrit le mécanisme RBAC réellement implémenté dans le dépôt :
les 4 niveaux de contrôle, les 11 rôles standards, la matrice complète
rôle × module, les permissions personnalisées qui affinent cette matrice,
les mécanismes de portée au niveau enregistrement (scoping N3) trouvés
module par module, et le masquage de champ (N4). Chaque affirmation ci-
dessous est dérivée du code source cité en regard — quand un point n'a pas
pu être vérifié avec certitude, il est signalé explicitement comme tel
plutôt que deviné.

## 1. Principes RBAC à 4 niveaux

Le RBAC de l'application se décompose en 4 niveaux indépendants, chacun
porté par un mécanisme distinct :

| Niveau | Nom | Question | Mécanisme | Fichier source |
|---|---|---|---|---|
| N1 | Module | L'utilisateur a-t-il accès à ce module métier du tout ? | Appartenance à un `Group` Django (= un rôle) donnant des permissions sur l'app | `apps/core/services/rbac_policy.py` (`ROLE_APP_PERMISSIONS`) |
| N2 | Objet-type | Peut-il voir/créer/modifier ce TYPE d'objet ? | Permissions Django auto-générées (`view_<model>`/`add_<model>`/`change_<model>`), vérifiées par `require_permission()` sur chaque endpoint | `apps/core/services/rbac_policy.py`, `apps/core/services/permissions.py` |
| N3 | Enregistrement | Peut-il voir/modifier CET enregistrement précis (le sien, celui de son équipe...) ? | Filtrage de queryset au cas par cas dans chaque module (`apply_scope`, `scope_*_for_user`, `user_can_manage_*`) | `apps/core/services/scoping.py` + un fichier par module métier concerné (§5) |
| N4 | Champ | Peut-il voir CE CHAMP précis d'un enregistrement qu'il peut par ailleurs consulter ? | Registre déclaratif `SENSITIVE_FIELDS` + `filter_fields_for_role()` | `apps/core/services/permissions.py` |

**Limitation architecturale explicitement documentée au N2** : la matrice
`ROLE_APP_PERMISSIONS` accorde des droits **par app entière**, jamais par
modèle individuel. Un rôle qui reçoit `{"view", "add", "change"}` sur l'app
`mrp` reçoit ces trois actions sur **tous** les modèles de `mrp` — il n'existe
aucun moyen, à ce niveau, de dire par exemple que `magasinier` peut modifier
`MrpOrderComponent` mais pas `MrpBom`. La docstring du fichier source
qualifie elle-même ce choix de « simplification assumée » : une matrice fine
par modèle demanderait une analyse métier modèle par modèle non encore faite
avec le commanditaire, et multiplierait le nombre de règles à maintenir. Ce
compromis remplace un état antérieur où « n'importe quel utilisateur
authentifié peut tout faire partout » — il reste donc un progrès net, mais
la granularité par modèle est une dette explicitement reportée. Quand une
opération précise doit échapper à cette granularité par app (dans un sens
plus restrictif ou plus large), le projet utilise `CUSTOM_PERMISSIONS`
(§4) — un mécanisme d'exception, pas un remplacement de la matrice.

**`delete` est volontairement absent partout dans `ROLE_APP_PERMISSIONS`** :
toutes les entités du projet utilisent le soft-delete applicatif
(`is_active`/`archived_at`), jamais une suppression SQL `DELETE` exposée via
l'API — donc aucun rôle, y compris `admin`, ne reçoit la permission Django
`delete_<model>` par cette matrice.

**`chat` est délibérément exclu** de `ROLE_APP_PERMISSIONS` : messagerie
interne transversale, pas une donnée métier sensible — tout utilisateur
authentifié y a accès, seule l'appartenance au canal (déjà vérifiée côté
service) protège son contenu.

**`core` n'apparaît jamais comme app entière** dans `ROLE_APP_PERMISSIONS` :
aucun rôle ne reçoit d'accès générique à tous les modèles `core`
(`Tenant`/`User`/`Document`...). Les deux seules exceptions — `RiskItem` et
les modèles qualité (`QltChecklistTemplate`/`QltInspection`), qui vivent
dans `core` mais sont rattachables à n'importe quel module via
content-type/object-id — reçoivent des permissions Django auto-générées
ajoutées au cas par cas dans `CUSTOM_PERMISSIONS` (§4), précisément pour
éviter d'ouvrir tout `core` en accordant l'app entière.

## 2. Les 12 rôles

Liste confirmée dans `widehalo/config/settings/base.py`
(`CORE_STANDARD_ROLES`), chargée en base par la commande de management
`load_roles` (`apps/core/management/commands/load_roles.py`, qui crée un
`Group`+`RoleProfile` par rôle et appelle `sync_group_permissions`). Le
test `apps/core/tests/test_rbac_default_deny.py` vérifie qu'il y en a
exactement 12.

**`caissier` est le 12e rôle**, ajouté par le chantier module POS (cahier
Phase 1 §13.5) — les 11 précédents datent tous du Lot 1/Lot 2 (« V1 acquis
du CDC »). Décision documentée ici en détail car c'est la première
extension de cette liste depuis son établissement : le cahier nomme
explicitement un persona « Caissier / vendeur » (§3) distinct du
persona « Commercial », avec un contexte d'usage entièrement différent
(« encaisse face à une file d'attente... souvent peu formé, parfois
saisonnier », vs. le commercial qui « passe la journée dans l'outil,
alterne téléphone client et saisie »). Réutiliser `commercial` aurait
mélangé deux scopes N3 sans rapport (le portefeuille CRM/ventes d'un
commercial n'a aucun sens pour « sa session de caisse ») et donné à un
caissier un accès CRM/Sales complet dont il n'a pas besoin — à la
différence des réutilisations précédentes (`magasinier`/`logistics`,
`acheteur`/département achats), aucun des 11 rôles existants n'est un
candidat plausible ici.

| Rôle | Intention métier (déduite de l'usage réel dans le code) |
|---|---|
| `admin` | Accès complet et transverse à tous les modules métier — administration technique du tenant. |
| `direction` | Pilotage/validation transverse : consultation large + capacité de faire évoluer un enregistrement (valider/annuler/approuver), jamais de création de donnée opérationnelle de premier niveau (`view`+`change`, rarement `add`) ; approbateur fréquent des `ApprovalRule` de chaque module. |
| `comptable` | Domaine cible = `accounting` (accès complet) ; également domaine cible de `financing` (dossier bancaire, plan de financement). |
| `commercial` | Gère les opportunités CRM, les partenaires et les ventes qui lui sont propres (scope N3 « own », cf. §5). |
| `resp_commercial` | Responsable de département commercial identifié (`DEPARTMENT_HEAD_ROLES` de `strategy`) : gère l'équipe commerciale (CRM/ventes en accès N2 complet, scope N3 équipe via `CrmTeam`), co-porteur de la gestion de projet, seul rôle « domaine cible » côté feasibility commercial. |
| `acheteur` | Domaine cible = `purchase` (demandes d'achat, réapprovisionnement, veille prix fournisseurs) ; retenu comme responsable de département « achats » faute d'un rôle dédié. |
| `resp_production` | Responsable de département production : domaine cible de `mrp`/`patronage`, co-porteur de la gestion de projet, domaine cible côté feasibility production. |
| `chef_atelier` | Supervision d'atelier : exécute/actualise la production (`mrp` en `view`+`change`, jamais `add` — ne crée pas de données de configuration comme les ateliers ou nomenclatures). |
| `magasinier` | Domaine cible = `stocks` (accès complet) ; hérite aussi de `logistics` (livraisons/expéditions) faute d'un rôle « logisticien » dédié parmi les 11. |
| `rh` | Domaine cible = `presence` + `payroll` (accès complet aux deux) ; responsable de département RH identifié pour `strategy`. |
| `collaborateur` | Rôle par défaut : accès en lecture aux référentiels partagés, gère ses propres objectifs/tâches/pointages/bulletins (scope N3 « own » très répandu pour ce rôle, cf. §5). |
| `caissier` | Domaine cible = `pos` (accès complet) ; persona « Caissier / vendeur » du cahier §3, distinct du `commercial` (cf. §2 pour le détail de cette décision). Scope N3 « sa session » (cf. §5) : ne gère que la session de caisse dont il est le titulaire. |

## 3. Matrice complète rôle × module (N2)

Dérivée littéralement de `ROLE_APP_PERMISSIONS` dans
`apps/core/services/rbac_policy.py`. `—` signifie : aucune entrée pour ce
rôle sur ce module (aucun accès N2, sauf mention contraire au §4).
`add` n'est listé que quand présent dans la matrice ; `delete` n'existe
jamais (§1).

### 3.1 Modules métier « classiques »

| Module | admin | direction | comptable | commercial | resp_commercial | acheteur | resp_production | chef_atelier | magasinier | rh | collaborateur | caissier |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `accounting` | v,a,c | v,c | v,a,c | — | v | — | — | — | — | — | — | — |
| `crm` | v,a,c | v,c | — | v,a,c | v,a,c | — | — | — | — | — | — | — |
| `mrp` | v,a,c | v,c | — | — | — | v,c | v,a,c | v,c | v,c | — | — | — |
| `patronage` | v,a,c | v,c | — | — | — | — | v,a,c | — | — | — | — | — |
| `partners` | v,a,c | v,c | v | v,a,c | v,a,c | v,a,c | — | — | — | — | v | v |
| `catalog` | v,a,c | v,c | v | v | v | v,a,c | v | v | v | — | v | v |
| `sales` | v,a,c | v,c | — | v,a,c | v,a,c | — | — | — | — | — | — | — |
| `pos` | v,a,c | v,c | v | — | — | — | — | — | — | — | — | v,a,c |
| `purchase` | v,a,c | v,c | — | — | — | v,a,c | — | — | — | — | — | — |
| `stocks` | v,a,c | v,c | — | — | — | — | — | — | v,a,c | — | — | — |
| `logistics` | v,a,c | v,c | — | — | — | — | — | — | v,a,c | — | — | — |
| `presence` | v,a,c | v,c | — | — | — | — | — | — | — | v,a,c | v | — |
| `payroll` | — | — | — | — | v \* | — | v \* | v \* | — | v,a,c | v \* | — |
| `strategy` | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c | v,a,c |
| `reporting` | v,a,c | v,a,c | v,a | v,a | v,a | v,a | v,a | v,a | v,a | v,a | v | v |
| `projects` | v,a,c | v,c | — | — | v,a,c | — | v,a,c | — | — | — | v,c | — |
| `financing` | v,a,c | v,c | v,a,c | — | — | — | — | — | — | — | — | — |
| `feasibility` | v,a,c | v,a,c | — | — | v,a,c | — | v,a,c | — | — | — | — | — |
| `helpdesk` | v,a,c | v,a,c | v,a | v,a | v,a | v,a | v,a | v,a | v,a | v,a | v,a | v,a |

Légende : v = view, a = add, c = change.

\* `payroll` en `view` seul pour `resp_commercial`/`resp_production`/
`chef_atelier` (les 3 rôles « manager » identifiés, cf. §4.2) donne accès à
l'existence/l'état d'un bulletin, jamais aux montants (masqués au N4,
§6) ; pour `collaborateur`, ce `view` est en outre restreint au N3 à ses
propres bulletins (§5.4).

**`accounting` : `absent` pour tous les rôles non listés** — aucun autre
rôle que `admin`/`direction`/`comptable`/`resp_commercial` (`view` seul)
n'a d'entrée `accounting` dans la matrice.

### 3.2 Modules d'infrastructure transverse (`ai`, `automation`)

Ces deux modules ne sont pas des modules métier au même titre que ceux
ci-dessus (pas de « domaine cible » parmi les 11 rôles) mais possèdent
bien une entrée RBAC dans `ROLE_APP_PERMISSIONS`, restreinte au pilotage :

| Module | admin | direction | Tous les autres rôles |
|---|---|---|---|
| `automation` | v,a,c | v,a,c | — |
| `ai` | v,a,c | v,c | — |

- **`automation`** (Studio de workflow visuel) : un flux d'automatisation
  déclenche des notifications/actions métier sans intervention humaine
  directe — mécanisme jugé « puissant », restreint explicitement à
  `admin`/`direction`, disclosé dans le code comme une restriction
  délibérée « extensible plus tard si un besoin réel apparaît pour
  d'autres rôles ».
- **`ai`** : cette entrée RBAC couvre uniquement l'**administration du
  budget de tokens/coût IA** d'un tenant (`AiUsageLimit`/`AiRequest`),
  réservée à `admin`/`direction` (pilotage de coût). Les fonctionnalités IA
  à usage large (assistant contextuel, recherche, insights,
  recommandations — citées dans le code comme AI2-AI7) sont exposées
  **sans permission de module dédiée**, avec la même posture que `chat` :
  ouvertes à tout utilisateur authentifié — c'est disclosé explicitement
  dans le commentaire du rôle `admin`.

## 4. Permissions personnalisées (N3 renforcé au niveau N2)

`CUSTOM_PERMISSIONS` (`apps/core/services/rbac_policy.py`) est un registre
`{rôle: {"app_label.codename", ...}}` de permissions Django **non
auto-générées** — déclarées explicitement dans un `Meta.permissions` de
modèle — accordées en plus (ou, pour deux entrées, en restriction ciblée)
de la matrice app-level du §3. Ces permissions ne sont **pas** un
mécanisme de scoping N3 au sens enregistrement : ce sont des permissions
N2 à granularité plus fine que « toute l'app », résolues par
`_custom_permissions_for_role` de la même façon que les permissions
auto-générées.

### 4.1 Inventaire complet par codename

| Codename | Rôles | Motif (cité du code source) |
|---|---|---|
| `accounting.validate_accmove` | admin, direction, comptable | Transition FSM de validation d'une facture, utilisée par `apps.accounting.api.validate_invoice_endpoint`. |
| `accounting.cancel_accmove` | admin, direction, comptable | Transition FSM d'annulation d'une facture, utilisée par l'écran HTMX `apps.accounting.views.invoice_detail` (action « cancel »). |
| `purchase.run_reordering` | admin, direction, acheteur | PU5 (RG-PUR-3) : déclenchement manuel du réapprovisionnement (`POST /purchase/reordering/run`) — admin/direction (pilotage transverse) et acheteur (domaine cible de `purchase`). |
| `purchase.run_price_watch_check` | admin, direction, acheteur | PRC1-3 : déclenchement manuel de la veille prix fournisseurs — mêmes rôles que `run_reordering`, même raisonnement. |
| `accounting.qualify_accimportrow` | admin, direction, comptable | RG-QUALIF : remplacer un placeholder par l'entité réelle sur une ligne d'import du journal de caisse (`POST .../rows/{id}/qualify`) — rôle « domaine cible » de `accounting` (comptable) + pilotage transverse. |
| `accounting.qualify_accinvoiceimportrow` | admin, direction, comptable | Idem, pour l'import de factures. |
| `stocks.qualify_stkimportrow` | admin, direction, magasinier | Idem, pour l'import de stock — rôle « domaine cible » de `stocks` (magasinier) + pilotage transverse. |
| `projects.bill_prjproject` | admin, direction, resp_commercial | PJ5 : garde les 4 endpoints de déclenchement de facturation (`POST /projects/{id}/bill/...`) — plus sensible que le CRUD projet/tâche déjà couvert au N2 (génère une écriture comptable engageant le tenant vis-à-vis d'un client). `resp_commercial` est seul des 2 co-porteurs de la gestion de projet à le recevoir : `resp_production` gère la production/les tâches mais n'est pas le rôle qui négocie/engage la facturation client. |
| `projects.manage_prjcustomfielddefinition` | admin, direction | PJ7 : configuration des champs personnalisés — contourne la granularité app-level qui accorderait sinon add/view/change sur ce modèle à `resp_commercial`/`resp_production` aussi. Un PARAMÉTRAGE, pas une opération courante de gestion de projet — ni `resp_commercial` ni `resp_production` ne le reçoivent (contrairement à `bill_prjproject`). |
| `projects.track_prjtimeentry` | admin, direction, resp_commercial, resp_production, collaborateur | PJ8 : contourne, dans le sens INVERSE des deux précédentes, la granularité app-level — `ROLE_APP_PERMISSIONS["projects"]` n'accorde pas `add` à `collaborateur`, or un collaborateur doit pouvoir démarrer/arrêter son propre chrono. Le scope N3 (« un utilisateur ne gère que ses propres entrées ») est porté par `apps.projects.services.time_tracking` lui-même, jamais par cette permission N2. |
| `helpdesk.manage_hlpslapolicy` | admin, direction | HD2 : configuration SLA — contourne la granularité app-level qui accorderait sinon add/view sur ce modèle aux 9 autres rôles. Un PARAMÉTRAGE/pilotage transverse, pas une opération courante de suivi de ticket. |
| `helpdesk.manage_hlpescalationrule` | admin, direction | HD2 : configuration des règles d'escalade — même raisonnement que `manage_hlpslapolicy`. |
| `helpdesk.run_helpdesk_checks` | admin, direction | HD2 : déclenchement manuel des vérifications SLA/escalade — même raisonnement. |
| `core.add_riskitem` / `core.view_riskitem` | acheteur, resp_production, resp_commercial, rh | RSK1-2 : rôles « domaine cible » plausibles pour signaler un risque sur leur périmètre — `add`+`view` seulement (pas `change` : la clôture/modification d'un risque signalé reste réservée à admin/direction ; le visionnage de LEURS PROPRES risques est filtré au niveau service, `owner=request.user`, dans `apps.core.views.risk`/`apps.core.api_risk`, pas un scope N3 complexe par entité rattachée). |
| `core.add_riskitem` / `core.view_riskitem` / `core.change_riskitem` | admin, direction | RSK1-2 : accès complet — voient/gèrent TOUS les risques, aucun scoping N3. |
| `core.add_qltchecklisttemplate` / `core.view_qltchecklisttemplate` / `core.change_qltchecklisttemplate` | admin, direction, resp_production, chef_atelier, acheteur | QLT1-2 : `resp_production`/`chef_atelier` (pilotage qualité en atelier/production) et `acheteur` (contrôle qualité à réception fournisseur) reçoivent les 3 actions — pas de scoping « owner » ici, une inspection qualité est une donnée d'équipe, pas un signalement personnel. |
| `core.add_qltinspection` / `core.view_qltinspection` / `core.change_qltinspection` | admin, direction, resp_production, chef_atelier, acheteur | Idem. |

### 4.2 Rappel : la restriction « managers ne voient aucun montant » (RG-PAY-9)

Cette règle n'est **pas** une entrée `CUSTOM_PERMISSIONS` mais mérite
d'être rattachée ici car elle est documentée juste avant ce registre dans
le code source : parmi les 11 rôles CDC, aucun n'est nommé « manager » ;
`resp_production`/`chef_atelier`/`resp_commercial` sont les 3 rôles qui
encadrent effectivement une équipe (via `presence.PrsEmployee.manager`).
Ils reçoivent `view` sur `payroll` (§3.1) — accès à l'existence/l'état
d'un bulletin — mais **jamais** aux montants, masqués au N4 par
`SENSITIVE_FIELDS` (§6). C'est une décision de conception documentée :
le CDC dit « aucun montant » sur les montants seulement, pas
« aucun accès du tout » au bulletin, qui aurait été un sur-refus non
demandé.

## 5. Scoping au niveau enregistrement (N3)

Chaque mécanisme réel trouvé par recherche (`def scope_*_for_user`,
`def user_can_manage_*`, `apply_scope`) dans `apps/*/services/*.py`. Le
hook générique existe dans `apps/core/services/scoping.py` ; les règles
métier concrètes sont, à ce jour, disséminées dans 3 modules + le hook
générique lui-même.

### 5.1 Hook générique (`apps/core/services/scoping.py`)

`apply_scope(queryset, user, scope)` où `scope` ∈
`{"global", "entity", "team", "workshop", "warehouse", "own"}` :

- `"own"` → filtre `queryset.filter(created_by=user)`.
- `"global"` → aucun filtre.
- `"entity"`/`"team"`/`"workshop"`/`"warehouse"` → **hooks non enrichis**,
  traités comme `"global"` (aucun filtre) : les modèles `Team`/
  `Workshop`/`Warehouse` génériques dont ces scopes dépendraient
  n'existent pas encore dans ce lot du dépôt — dette anticipée, disclosée
  dans la docstring du fichier lui-même comme « dette anticipée assumée,
  documentée dans le plan ». Autrement dit : appeler `apply_scope(qs,
  user, "team")` aujourd'hui ne filtre **rien** — chaque module qui a
  besoin d'un scope équipe/entité réel (ex. `crm`, `strategy`, §5.2-5.3)
  implémente sa propre fonction dédiée plutôt que de s'appuyer sur ce
  hook générique pour ces cas.

### 5.2 `apps/crm/services/scoping.py` — `scope_leads_for_user`

Portée des `CrmLead` (opportunités) :

- `admin`/`direction` (`UNRESTRICTED_ROLES`) : voient tout (`apply_scope`
  en `"global"`).
- `resp_commercial` (`TEAM_LEAD_ROLES`) : voit les leads dont l'équipe
  (`CrmTeam`) est celle qu'il dirige (`leader=user`) OU dont il est
  membre (`members=user`) — union des deux ensembles d'équipes.
- Tout autre rôle (typiquement `commercial`) : ne voit que les leads dont
  il est le vendeur assigné (`salesperson=user`) — **par vendeur assigné,
  pas par créateur**, précisément parce qu'un admin ou un import peut
  créer un lead pour un autre commercial (cité dans la docstring).

### 5.3 `apps/strategy/services/scoping.py` — `scope_objectives_for_user` / `assert_can_manage_level`

Portée des `StgObjective` :

- `admin`/`direction` (`UNRESTRICTED_ROLES`) : voient/gèrent tous les
  niveaux d'objectif (`"global"`).
- `resp_commercial`/`resp_production`/`rh`/`acheteur`
  (`DEPARTMENT_HEAD_ROLES`, « responsables de département identifiés » —
  `acheteur` retenu comme le candidat le plus proche d'un responsable
  achats faute d'un rôle dédié) : voient les objectifs de leur(s)
  département(s) géré(s) (`get_department_ids_managed_by`, via
  `presence.PrsEmployee.manager`), PLUS leurs propres objectifs
  individuels (`owner=user` ou `created_by=user`).
- Tout autre rôle (typiquement `collaborateur`) : uniquement ses propres
  objectifs, créés par lui OU dont il est `owner` (assignation par son
  responsable) — jamais ceux d'un collègue.

`assert_can_manage_level(user, level, department_id, tenant)` est une
garde d'**écriture** (lève `PermissionDenied`, distincte du filtrage de
lecture ci-dessus) :

- niveau « entreprise » : réservé à `admin`/`direction`.
- niveau « département » : réservé aux `DEPARTMENT_HEAD_ROLES`, et
  seulement pour un département qu'ils gèrent effectivement
  (`get_department_ids_managed_by`).
- niveau « individuel » : tout rôle authentifié peut créer son propre
  objectif — c'est le scoping de *lecture* ci-dessus qui reste la vraie
  barrière pour un objectif appartenant à un tiers.

### 5.4 `apps/presence/api.py` et `apps/payroll/api.py` — scope « own » RG-PRS-9 / RG-PAY-9

Même patron dans les deux modules, implémenté directement dans la couche
API (pas dans un fichier `services/scoping.py` dédié) :

- **`presence`** : `_STAFF_ROLES = {"rh", "admin", "direction"}` ;
  `_can_see_all(request)` teste l'appartenance à ce jeu de rôles. Un
  `collaborateur` (ou tout rôle hors `_STAFF_ROLES`) ne voit que ses
  propres pointages/absences ; RH/admin/direction voient tout.
- **`payroll`** : même `_STAFF_ROLES = {"rh", "admin", "direction"}`. Un
  `collaborateur` ne voit que ses propres bulletins (résolu via
  `presence.services.public.get_employee_id_for_user`/
  `_own_employee_id`). L'endpoint `GET
  /payroll/payslips/{payslip_id}/pdf` applique cette règle avec un soin
  particulier : un utilisateur hors `_STAFF_ROLES` qui n'est pas
  l'employé du bulletin reçoit un **403 explicite**, jamais un 404 — un
  404 laisserait deviner l'existence d'un bulletin d'autrui par
  énumération d'UUID (cité du code, test d'acceptance §5.10.10 n°5).

### 5.5 `apps/helpdesk/services/tickets.py` — `user_can_manage_ticket`

Scope N3 appliqué **au niveau enregistrement** (pas au niveau queryset —
le code note explicitement que HD1 n'a pas encore d'écran « mes tickets »
filtré) : un utilisateur sans la permission N2 `helpdesk.change_hlpticket`
peut néanmoins transitionner/commenter un ticket dont il est `requester`
OU `assignee` — jamais celui d'un tiers. Vérifié explicitement dans
`apps.helpdesk.api` à chaque endpoint de mutation/transition/commentaire.
Concrètement, pour les rôles non « domaine cible » du module (tous sauf
admin/direction, qui reçoivent le CRUD complet côté N2, §3.1) : la
matrice N2 leur donne `view`+`add` sur `helpdesk`, et ce scope N3 leur
permet en plus d'agir sur leurs propres tickets.

### 5.5bis `apps/pos/services/scoping.py` — `assert_can_manage_session` (chantier module POS)

Scope N3 appliqué au niveau **service**, pas queryset (même choix que
`user_can_manage_ticket` de `helpdesk` ci-dessus) : `open_session`
détermine déjà le titulaire de la session sans ambiguïté (le paramètre
`cashier` est toujours `request.auth` côté API, aucun endpoint n'expose
de champ permettant d'ouvrir une session au nom d'un tiers), mais
`add_cash_movement`/`close_session`/`create_draft_order` (donc
transitivement toute vente créée sous une session) sont bornés à SON
PROPRE titulaire — un `caissier` qui a la permission N2 `pos.change_
possession`/`pos.add_posorder` sur TOUT le module (§3.1, domaine cible)
ne peut néanmoins gérer/vendre que sous la session dont il est
`cashier`. `admin`/`direction`/un superutilisateur voient/gèrent toute
session, sans exception (pilotage transverse, même discipline que le
reste de ce registre) — cohérent avec `comptable`, qui lui n'a que
`view` au N2 (§3.1) et n'a donc jamais besoin de ce scope.

### 5.6 `projects` (PJ1) — scope N3 explicitement **non câblé**, à documenter comme tel

Contrairement aux 4 mécanismes ci-dessus, la docstring du rôle
`collaborateur` dans `rbac_policy.py` documente explicitement l'**absence**
d'un scope N3 « own » pour `projects` à ce stade (PJ1) : le droit N2
`{"view", "change"}` accordé à `collaborateur` sur `projects` est, en
l'état du code lu, un droit large sur **tout** le module — aucun
endpoint/vue de `projects` ne filtre encore par `assignee=request.user`
ou `owner=request.user`. Ce scoping « own » (candidat naturel : un filtre
équivalent à `scope_objectives_for_user`) est explicitement reporté à une
étape ultérieure (PJ8/suivi du temps, ou une étape RBAC dédiée) — ce
n'est **pas** un oubli de cette synthèse mais un état du code disclosé
dans le code source lui-même. Seule l'action de facturation
(`projects.bill_prjproject`, §4.1) et le suivi du temps
(`projects.track_prjtimeentry`, dont le scope « own » est bien porté par
`apps.projects.services.time_tracking`, §4.1) échappent à cette
limitation.

### 5.7 Récapitulatif des mécanismes N3 trouvés

| Module | Fonction | Fichier | Règle en une phrase |
|---|---|---|---|
| générique | `apply_scope` | `apps/core/services/scoping.py` | `own`=créateur, `global`=aucun filtre, `entity`/`team`/`workshop`/`warehouse`=hooks non enrichis (= `global` en pratique). |
| `crm` | `scope_leads_for_user` | `apps/crm/services/scoping.py` | commercial = ses leads assignés ; resp_commercial = ceux de son équipe ; direction/admin = tout. |
| `strategy` | `scope_objectives_for_user`, `assert_can_manage_level` | `apps/strategy/services/scoping.py` | collaborateur = ses objectifs (owner/créateur) ; responsable de département = + ceux de son département ; direction/admin = tout. |
| `presence` | `_can_see_all`/`_own_employee_id` (API, pas un fichier `scoping.py` dédié) | `apps/presence/api.py` | collaborateur = ses pointages/absences ; rh/admin/direction = tout. |
| `payroll` | idem (API) | `apps/payroll/api.py` | collaborateur = ses bulletins (403 explicite sur PDF d'autrui, jamais 404) ; rh/admin/direction = tout. |
| `helpdesk` | `user_can_manage_ticket` | `apps/helpdesk/services/tickets.py` | tout rôle peut transitionner/commenter un ticket dont il est requester OU assignee, en plus de ce que donne `helpdesk.change_hlpticket`. |
| `pos` | `assert_can_manage_session` | `apps/pos/services/scoping.py` | caissier = sa propre session (mouvements, clôture, ventes) ; admin/direction = tout. |
| `projects` | — (non câblé pour PJ1) | — | limitation N3 « collaborateur » explicitement reportée, cf. §5.6. |

## 6. Masquage de champ (N4)

`SENSITIVE_FIELDS` (`apps/core/services/permissions.py`) est un registre
déclaratif `{model_label: {field: {rôles autorisés}}}`, consommé par
`filter_fields_for_role(model_label, role_codes, data)` qui retire du
dict de sortie tout champ sensible pour lequel aucun rôle de l'utilisateur
n'est dans l'ensemble autorisé. Deux populations réelles trouvées dans le
dépôt (`grep -rn "SENSITIVE_FIELDS\["` sur `apps/`) :

| Modèle | Champs masqués | Rôles autorisés à les voir | Motif |
|---|---|---|---|
| `sales.SalesOrderLine` | `margin_pct`, `cost_estimate_mga` | `direction`, `admin`, `resp_commercial` | RG-SAL-5 : `commercial` est explicitement exclu — il ne doit pas voir la marge sur les lignes qu'il chiffre au client, seulement le prix. `cost_estimate_mga` est masqué avec `margin_pct` car un coût de revient permet de reconstituer la marge par simple soustraction du prix de vente (déjà visible du commercial) — masquer seulement la marge aurait laissé une fuite triviale de la même information. |
| `sales.SalesQuotationLine` | `margin_pct`, `cost_estimate_mga` | `direction`, `admin`, `resp_commercial` | Même raisonnement que `SalesOrderLine` — le CDC ne mentionnait que `SalesOrderLine` en exemple, mais `SalesQuotationLine` porte la même information sensible sur les devis. |
| `payroll.PayPayslip` | `gross`, `taxable_base`, `irsa`, `social_employee`, `social_employer`, `net_to_pay` | `rh`, `direction`, `admin`, `collaborateur` | RG-PAY-9 : « managers ne voient aucun montant » — `resp_production`/`chef_atelier`/`resp_commercial` reçoivent `view` sur `payroll` au N2 (§3.1/§4.2) mais restent exclus ici, donc masqués sur tout champ monétaire. `collaborateur` est inclus : un employé doit voir SES PROPRES montants (combiné au scope N3 « own », §5.4) — seul le regard d'un manager sur l'équipe est concerné par la restriction du CDC. |
| `payroll.PayPayslipLine` | `base`, `rate`, `amount` | `rh`, `direction`, `admin`, `collaborateur` | Même raisonnement que `PayPayslip`. |

**Aucune autre entrée n'existe dans `SENSITIVE_FIELDS` à ce jour** — la
recherche `grep -rn "SENSITIVE_FIELDS\[" apps/` ne retourne que les 4
lignes ci-dessus. Le registre est vide par défaut (`SENSITIVE_FIELDS:
dict[...] = {}` déclaré en tête de fichier) : tout futur module qui
introduit un champ sensible doit y ajouter sa propre entrée — rien
n'est masqué par défaut.

## 7. Portails/accès hors RBAC classique

**`apps.projects.services.guest_portal`** (PJ14) est un cas particulier
qui échappe entièrement au RBAC interne décrit ci-dessus : il donne accès
à une vue **lecture seule** d'un projet à un tiers externe (client,
partenaire) qui n'a et n'aura **jamais** de compte `core.User`, de
session Django, ni de JWT. L'unique credential est la possession d'un
`token` opaque (modèle `PrjGuestAccess`), pas un rôle parmi les 11.
Points notables documentés dans le code source :

- Le token porte lui-même l'identification du tenant (dérogation RLS
  `RLS_FORCE_FOR_OWNER = False`, propre à ce seul modèle) — nécessaire
  car un visiteur invité n'a, par construction, ni tenant actif ni
  session pour en déduire un.
- Les 3 cas d'échec (token inconnu, révoqué, expiré) sont **indiscernables
  côté réponse HTTP** — toujours un 404 générique, jamais une exception
  qui permettrait de distinguer un cas de l'autre.
- **Aucun montant sensible de marge/coût interne n'est exposé** : la vue
  invité ne calcule jamais l'EVM (`services/evm.py`) ni ne lit
  `PrjBudgetLine` ; le seul indicateur d'avancement fourni est un
  pourcentage de tâche (donnée de planning), jamais un montant — décision
  produit disclosée explicitement dans la docstring du service.

Ce portail doit être traité comme un **canal d'accès séparé**, pas comme
une extension des 11 rôles RBAC — aucune ligne de `ROLE_APP_PERMISSIONS`
ni de `CUSTOM_PERMISSIONS` ne s'applique à un visiteur invité.

## 8. Réserve méthodologique

Ce document est une **synthèse de lecture**, pas la source de vérité :
la source de vérité reste et restera toujours le code, en premier lieu
`apps/core/services/rbac_policy.py` (`ROLE_APP_PERMISSIONS`,
`CUSTOM_PERMISSIONS`) pour les niveaux N1/N2, `apps/core/services/
permissions.py` (`SENSITIVE_FIELDS`) pour le N4, et les fichiers de
scoping listés au §5.7 pour le N3. Ce document doit être mis à jour
**à chaque nouveau module ou nouvelle permission ajoutée** à ces
registres — en particulier :

- toute nouvelle entrée dans `ROLE_APP_PERMISSIONS` (nouveau module ou
  nouveau rôle sur un module existant) → mettre à jour la matrice du §3 ;
- toute nouvelle entrée dans `CUSTOM_PERMISSIONS` → ajouter une ligne au
  tableau du §4.1 ;
- toute nouvelle fonction `scope_*_for_user`/`user_can_manage_*` dans un
  module métier → ajouter une entrée au §5.7 ;
- toute nouvelle entrée dans `SENSITIVE_FIELDS` → ajouter une ligne au
  tableau du §6.

Ce document couvre l'état du dépôt au moment de sa rédaction (18 modules
métier réels sous `apps/`, hors `core`/`chat`/`automation`/`ai` ; ces 2
derniers traités séparément au §3.2 comme infrastructure transverse
disposant néanmoins d'une entrée RBAC). Le décompte exact des modules
métier au moment de la rédaction : `accounting`, `catalog`, `crm`,
`feasibility`, `financing`, `helpdesk`, `logistics`, `mrp`, `partners`,
`patronage`, `payroll`, `presence`, `projects`, `purchase`, `reporting`,
`sales`, `stocks`, `strategy` — soit 18, pas 19 ; si un module
supplémentaire existe dans une version ultérieure du dépôt, ce compte et
la matrice du §3 doivent être révisés en conséquence.
