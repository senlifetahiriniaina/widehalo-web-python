# Plan — rattrapage des Phases 1 à 3, puis Phase 4

**Source de vérité pour le contenu** :
[`docs/audit/2026-09-audit-complet-phases-1-4.md`](../audit/2026-09-audit-complet-phases-1-4.md) —
203 critères confrontés au code : **94 conformes, 58 partiels, 46 absents, 3 non
vérifiables, 2 sans objet**. Ce document ne ré-audite rien ; il organise la fermeture
des écarts déjà constatés.

**Cahiers des charges** : [`docs/cdc-complet/`](../cdc-complet/README.md).

**Patron de structure** :
[`docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md`](2026-09-cahier-des-charges-v3-phase3-plan.md),
dont les 34 sprints ont tous été exécutés — même cadence, même gabarit de sprint,
mêmes sections. Ce plan-ci en est la suite directe.

**Statut** : plan **prospectif**, non encore exécuté. Chaque lot et chaque sprint
porte un objectif et une définition de fin, jamais un « livré ».

---

## 1. État des lieux

| Phase | Critères | ✅ | 🟡 | ❌ | À traiter ici |
|---|---|---|---|---|---|
| 1 | 52 | 25 | 19 | 6 | **25** écarts |
| 2 | 38 | 24 | 11 | 2 | **13** écarts |
| 3 | 59 | 44 | 12 | 1 | **13** écarts |
| 4 | 54 | 1 | 16 | 37 | **53** critères, chantier neuf |
| | 203 | 94 | 58 | 46 | **51 écarts P1–P3 + la Phase 4** |

Trois critères restent ❓ (P1/CRM-7, P1/ACC-6, P2/BI-5) et deux N/A (P3/QUA-10,
P3/PAY-12) : ils ne figurent dans aucun lot, les premiers parce qu'ils demandent une
mesure et non du code, les seconds parce qu'ils demandent la signature d'un tiers.

**Le point qui commande l'ordre du plan** : l'écart le plus lourd de l'audit n'est
dans aucune grille de critères — *rien n'ordonnance rien* (§3.1 de l'audit). Cinquante
et une commandes de gestion attendent un ordonnanceur qui n'existe pas, si bien que
l'entrepôt analytique n'est jamais rafraîchi et que **BI, Forecast et Strategy
restituent des données vides en exploitation**. Tant que ce point n'est pas fermé,
aucune recette de la Phase 2 n'a de sens, et une partie des ✅ de l'audit décrit du
code juste que personne n'exécute.

---

## 2. Décisions à acter

Sept décisions conditionnent le périmètre et l'effort. Les quatre premières sont à
trancher **avant** le premier lot ; les trois dernières sont reprises telles quelles
des cahiers et n'ont pas à être rediscutées.

| # | Décision | Recommandation | Impact |
|---|---|---|---|
| **D7** | Ordonnanceur (§3.1 de l'audit) : `Schedule` django-q2 enregistrés au démarrage **ou** service `cron` dans `docker-compose.prod.yml` | **`Schedule` django-q2**, enregistrés depuis un `apps.py::ready()` dédié. Le `qcluster` tourne déjà en production ; aucun composant nouveau, et la planification devient une donnée interrogeable plutôt qu'un fichier système hors du dépôt. | Lot L0, ~4 JT. L'autre option coûte moins cher à écrire mais sort la planification du dépôt et de sa CI. |
| **D8** | Relèvement des plafonds d'architecture. Le plafond d'écrans est atteint exactement (240/240) et au moins quatre lots ci-dessous exigent un gabarit nouveau | **Relever d'abord, mesurer ensuite** : ré-exécuter le compteur officiel, puis acter un relèvement unique couvrant toute la Vague 1 plutôt qu'un relèvement par lot. | Lot L1, ~1 JT. Sans lui, L4, L6, L9 et L11 font échouer la construction. |
| **D9** | TVA et référentiel comptable : porter les taux de TVA dans `core_regulatory_parameter` (SAL-5, ACC-9) **ou** conserver `AccTax` | **Porter dans `RegulatoryParameter`.** C'est le seul chemin qui donne la résolution à la date du document, le versionnement et le statut de validation OECFM que les critères exigent, et il aligne la comptabilité sur ce que la paie fait déjà. | Lot L3, ~6 JT au lieu de ~1 JT si l'on se contente de documenter `AccTax`. |
| **D10** | Abstraction du référentiel comptable PCG 2005 / SYSCOHADA (ACC-2, §2.1 de l'audit) | **Hors périmètre de ce plan.** Le cahier Phase 1 la demande, mais aucun tenant SYSCOHADA n'existe et le chantier dépasse le rattrapage : il touche la structure des états financiers. À rouvrir comme chantier propre, avec son ADR, au moment du « pays #2 ». Le plan ne traite ici que la partie **vérifiable** : élargir la garde CI (L2). | Évite ~25 JT de chantier structurel dans un plan de rattrapage. À acter explicitement avec le maître d'ouvrage, car c'est un critère du cahier laissé ouvert. |
| D11 | Orchestration Phase 4 | **Hub de flux interne au monolithe** (cahier Phase 4 §12.1). Plateforme d'automatisation embarquée et plateforme d'intégration en service écartées. | Reprise du cahier. |
| D12 | Encaissement mobile | **Agrégateur par défaut, raccordement direct en option de tenant**, derrière une interface unique sélectionnée par paramètre (§12.2). | Reprise du cahier. Le surcoût de conception (~½ sprint) est le prix de la réversibilité. |
| D13 | Raccordement fiscal | **Direct en cible, opérateur agréé en repli activable par paramètre** (§12.3). | Reprise du cahier. |

---

## 3. Cadence, gabarit et unités

Cadence identique au patron du dépôt : **15 Jour-Token (JT) par semaine**
(`docs/planning/2026-refonte-ux-sprints.md` §2).

| Jours | JT | Contenu |
|---|---|---|
| J1–J3 | 9 JT | Construction : service(s), modèle(s), écran(s) du lot. |
| J4 | 3 JT | Intégration et vérification des critères d'acceptation référencés. |
| J5 | 3 JT | **Durcissement** : test d'architecture si le lot en appelle un, docstrings du périmètre touché relues (règle de revue de `CONTRIBUTING.md`), non-régression sur les modules connectés. |

> **Deux unités à ne jamais additionner.** Le « Jour-Token » du dépôt (15 JT par
> semaine) et le « J-Token » des cahiers des charges (63 pour toute la Phase 4) ne
> désignent pas la même chose. La Vague 1 ci-dessous est chiffrée dans l'unité du
> dépôt ; la Vague 2 reprend **telles quelles** les colonnes du cahier Phase 4 §17.2,
> sans conversion. Les totaux des deux vagues ne se somment pas.

---

## 3 bis. État d'avancement au 2026-09-05

Trois chantiers des préalables sont livrés, ainsi que D10, que l'utilisateur a
demandé de traiter en premier alors que ce plan le mettait hors périmètre.

| Chantier | État | Écart avec le chiffrage de ce plan |
|---|---|---|
| **D10** — abstraction du référentiel comptable | ✅ livré, 6 sprints | Hors périmètre dans ce plan ; traité en premier sur décision de l'utilisateur, avec son ADR (`2026-09-adr-referentiel-comptable.md`). |
| **L1** — budgets d'architecture | ✅ livré | Relèvement à **+33 %** (415 / 800 / 320) décidé par l'utilisateur, au lieu du relèvement au plus juste envisagé ici. Passé **avant** D10 : à 240/240 écrans, le premier gabarit de D10 faisait échouer la construction. |
| **L0** — ordonnancement | ✅ livré, 5 sprints | **≈ 20 JT au lieu de 4.** Ce plan supposait neuf commandes prêtes à être planifiées. Il y en a **dix-neuf**, dont **cinq produisaient un doublon à chaque exécution** et **dix-huit interrompaient la boucle** au premier tenant en échec. Les brancher telles quelles aurait transformé « inerte » en « bruit et coût ». |
| **L2** — gardes CI manquantes | ✅ livré, 4 sprints | **≈ 7 JT au lieu de 6.** La garde du copilote exigeait d'ajouter un champ `read_only` au registre avant de pouvoir vérifier quoi que ce soit ; et l'élargissement de la garde des comptes appartenait à D10-6, pas à L2 (le retirer de sa liste d'exception produisait 55 violations tant que D10-3 n'était pas livré). |

Trois défauts réels découverts en chemin, corrigés hors chiffrage :

- **`load_mg_holidays` n'existait pas** alors que la docstring du calendrier y
  renvoyait : `ForHoliday` n'était peuplée par rien, donc `business_days_in_month`
  surestimait la capacité de production d'une dizaine de jours par an. Commande,
  fixture (avec sa réserve) et tests livrés avec L2-3.
- **Les quatre chemins de création de tenant chargeaient le PCG malgache
  inconditionnellement**, `CountryDefaultsProfile.chart_of_accounts_code` n'étant lu
  par personne. Corrigé par D10-5.
- **Les comptes par défaut se résolvaient par `.first()` sans `order_by`**, donc de
  façon non déterministe. Corrigé par D10-2.

Un écart fonctionnel signalé et **non corrigé**, hors périmètre des critères :
`sales/services/orders.py` pose `amount_tax = Decimal(0)` — le module Sales ne
calcule aucune taxe, seul le POS applique `get_default_sale_tax`. À verser au lot L5.

| **L15** — hygiène (dérive documentaire, secrets en clair) | ✅ livré | **Le plan se trompait sur un point, et il faut le dire** : il prescrivait de porter `PrjGuestAccess.token` en `EncryptedCharField`. C'était impossible — ce champ est **cherché par sa valeur** (`resolve_guest_access`) et Fernet n'est pas déterministe : le portail invité aurait cessé de fonctionner en silence. Empreinte SHA-256 à la place. Un troisième secret en clair, absent de l'audit, a été trouvé au passage (`UserEmailChangeRequest.token`) et fermé, ainsi que la classe entière par une garde. |
| **L11** — sortir `apps/quality` de l'ombre | ✅ livré | Conforme au plan, plus deux ajouts nécessaires qu'il ne nommait pas : le module devait aussi entrer dans le calcul de visibilité des menus (`context_processors._MODULE_APP_LABELS`), sans quoi sa tuile serait restée invisible à tous sauf aux superutilisateurs ; et publier ses évènements exigeait d'abord d'en **émettre**, le module n'en publiant aucun. |

Reste donc de la Vague 1 : **L3 à L10, L12 à L14, et L16**.

## 4. Vague 1 — rattrapage des Phases 1 à 3

Seize lots, 51 écarts. L0 et L1 précèdent tout le reste : le premier parce qu'il
rend la Phase 2 réellement observable, le second parce que sans lui quatre lots font
échouer la construction dès leur premier gabarit.

### 4.1 Préalables

| # | Lot | Objectif | Définition de fin | Fichiers principaux | Critères | Effort |
|---|---|---|---|---|---|---|
| **L0** | Ordonnancement (D7) | Les traitements périodiques s'exécutent réellement | Les 9 commandes opérationnelles (`run_analytics_refresh`, `run_bi_diffusions`, `run_report_schedules`, `run_expiry_alerts`, `run_quality_control_checks`, `run_purchase_reordering`, `check_quant_consistency`, `expire_stock_reservations`, `run_presence_maintenance`) sont enregistrées comme `Schedule` django-q2 au démarrage, avec fréquence et fenêtre paramétrables ; un écran ou un endpoint d'administration liste la dernière exécution et son issue ; un test vérifie qu'un ajout de commande sans planification est signalé | nouveau `apps/core/services/scheduling_registry.py`, `apps/core/apps.py::ready()`, `apps/core/tasks.py` | STK-2, QUA-9, FOR-15 ; débloque tout BI/Forecast/Strategy | 4 JT |
| **L1** | Budgets d'architecture (D8) | Le prochain gabarit ne casse plus la construction | Compteur officiel ré-exécuté et chiffre consigné ; `BUDGET_MAX_MODELS`/`ENDPOINTS`/`SCREENS` relevés d'un seul mouvement couvrant toute la Vague 1, avec le commentaire justificatif attendu par `test_budget.py` ; `ECART_ARCHITECTURE.md` mis à jour | `config/settings/base.py:412-414`, `docs/planning/ECART_ARCHITECTURE.md` | — (préalable) | 1 JT |
| **L2** | Les quatre gardes CI manquantes | Ce que le code fait déjà bien devient opposable | Quatre tests d'architecture nouveaux, bloquants : liste blanche du copilote (aucun outil d'écriture, aucun outil hors registre) ; aucun SQL ni fragment de requête en entrée d'endpoint de rapport ; aucune date fériée en dur ; aucun taux de TVA en dur. Plus l'élargissement de deux gardes existantes : `test_no_hardcoded_account_numbers.py` cesse d'exclure la structure des états financiers, `test_no_hardcoded_payroll_rates.py` détecte aussi les montants et les bornes de tranches | `tests/architecture/` (4 fichiers nouveaux + 2 modifiés) | IA-1, BI-2, FOR-5, SAL-5 (partie test), ACC-2, P3/PAY-1 | 6 JT |

### 4.2 Phase 1 — 29 écarts (25 critères, dont 4 traités en L16)

| # | Lot | Objectif | Définition de fin | Fichiers principaux | Critères | Effort |
|---|---|---|---|---|---|---|
| **L3** | Comptabilité : paramètres et verrous | Les règles comptables vivent dans la table versionnée, pas à côté | Taux de TVA résolus par `core.services.regulatory.get_parameter_with_version` **à la date du document** (D9) ; `ACTIVE_CALCULATION_PARAMETER_CODES` étendu aux codes comptables ; refus d'écriture en exercice clos porté par un **trigger PostgreSQL** et non plus par le seul service, avec test de contournement ; chargement du plan de comptes déclenché à la création d'un tenant dont le pays est Madagascar | `apps/accounting/services/taxes.py`, `apps/core/services/regulatory_governance.py`, nouvelle migration `apps/accounting/migrations/`, `apps/core/services/tenants.py` | SAL-5, ACC-1, ACC-9, ACC-10 | 10 JT |
| **L4** | CRM — les quatre manques | Le module le plus faible de la Phase 1 rejoint le niveau des autres | Kanban à glisser-déposer sur le pipeline **en réutilisant `Sortable.min.js` déjà vendorisé et le patron de `templates/mrp/kanban.html`**, transition écrite au chatter ; chatter câblé sur `CrmLead` via `chatter_guard_registry` ; fiche société affichant encours, solde comptable et trois derniers documents via `accounting.services.public` et `sales.services.public` ; conversion de piste créant société, contact et opportunité en une validation ; tuile « relances en retard » au launchpad avec seuil N paramétrable ; composant d'état vide générique dans `templates/components/`, appliqué au pipeline | `apps/crm/views.py`, `apps/crm/services/leads.py`, `templates/crm/`, `templates/partners/detail.html`, `templates/components/_empty_state.html`, `apps/core/views/dashboard.py` | CRM-1, CRM-2, CRM-3, CRM-4, CRM-5 | 14 JT |
| **L5** | Sales — brouillon et document | La saisie survit à une coupure, la facture porte ses mentions | Autosave de brouillon de devis (stockage local à l'événement de saisie, restitution au rechargement, purge à la validation) — **le seul écart de la Phase 1 explicitement reporté depuis le Sprint 3 du plan UX et jamais repris** ; test de concurrence sur la numérotation ; gabarit légal de facture avec mentions obligatoires paramétrées par tenant | `templates/sales/quotation_create.html`, `static/js/`, `templates/reports/legal/invoice.html`, `apps/sales/tests/`, `apps/core/models/tenant.py` | SAL-6, SAL-7, SAL-8 | 7 JT |
| **L6** | POS — impression et vente comptoir | La caisse produit un ticket, et sa vente atteint le stock par sa vraie nature | Gabarit d'impression de ticket (58/80 mm, `@media print`), mention « DUPLICATA » sur réimpression — le compteur `reprint_count` existe déjà et documente un gabarit qui n'existe pas ; affichage du rendu de monnaie à l'écran de vente ; `apps.pos` produit des mouvements de nature `TYPE_VENTE_COMPTOIR` (la nature existe déjà, `apps/stocks/models.py:530-536`, sans producteur) | `templates/pos/ticket.html` (nouveau), `templates/pos/sale.html`, `apps/pos/services/orders.py` | POS-1, POS-3 | 5 JT |
| **L7** | IA — traçabilité et confort | Le copilote devient vérifiable par son utilisateur | Durée d'appel persistée sur `AiDataQuery` ; test d'isolation à deux tenants propre au copilote ; réponse d'attente explicite au-delà du seuil plutôt qu'une dégradation muette ; lien de vérification joint à toute réponse chiffrée (l'outil déclare l'écran qui permet de contrôler son chiffre) ; écran de consentement à l'activation d'un fournisseur externe, énonçant les données qui sortiront, et journalisation de l'activation | `apps/ai/models.py`, `apps/ai/services/data_query_gateway.py`, `apps/core/services/data_query_tool_registry.py`, `apps/ai/tests/`, `templates/ai/` | IA-2, IA-4, IA-7, IA-8, IA-9 | 8 JT |

| **L16** | Parcours clavier et budgets de perception | Quatre critères passent de « l'écran existe » à « le parcours est tenu » | Navigation clavier intégrale sur la saisie de devis et sur la saisie d'écriture, sans souris, vérifiée par un test de parcours ; contrôle d'équilibre affiché **en continu** pendant la saisie d'écriture ; budget de taille propre au socle de simulation, distinct du budget de page générique, vérifié en CI ; mesure de la latence de recalcul d'un levier, publiée avec le seuil de 100 ms | `templates/sales/quotation_create.html`, `templates/accounting/`, `apps/simulation/services/baseline.py`, `tests/ui/test_page_budgets.py`, `tests/e2e/` | SAL-1, ACC-3, SIM-1, SIM-2 | 6 JT |

### 4.3 Phase 2 — 13 écarts

| # | Lot | Objectif | Définition de fin | Fichiers principaux | Critères | Effort |
|---|---|---|---|---|---|---|
| **L8** | Amorçage du dictionnaire d'indicateurs | Le dictionnaire cesse d'être vide sur une instance neuve | Écran et endpoint de création/modification d'indicateur ; jeu d'indicateurs de départ livré en migration de données ou fixture ; `METRIC_FACTS` cesse d'être une table de correspondance codée en dur — un indicateur du dictionnaire devient calculable sans modification de code, ou son absence de calculabilité est **signalée** au lieu d'être silencieuse ; `AnFactPaie` déclaré dans `FACT_SPECS` ; test de cohérence vérifiant que deux écrans affichant le même indicateur sur le même périmètre renvoient la même valeur ; création d'un résultat clé sans indicateur du dictionnaire refusée | `apps/analytics/views.py`, `apps/analytics/api.py`, `apps/bi/services/metric_computers.py`, `apps/analytics/services/fact_specs.py`, `apps/strategy/services/objectives.py`, `templates/analytics/` | BI-1, BI-2 (partie mesures), STR-1 | 12 JT |
| **L9** | BI et Forecast — finitions | Ce qui est calculé devient visible | État du rafraîchissement affiché **sur chaque tableau de bord** et non sur la seule page d'index ; `measure_adjustment_contribution` appelée depuis le calcul de prévision (sans quoi l'onglet qualité reste vide en exploitation) ; prévision d'encaissement ventilée par client y compris sur l'agrégat global ; publication de prévision utilisable comme scénario de référence dans `apps/simulation` ; audit du catalogue de rapports figés et arbitrage de ceux à reconstruire sur la couche sémantique | `templates/bi/`, `apps/forecast/services/adjustments.py`, `apps/forecast/services/treasury.py`, `apps/simulation/services/baseline.py`, `apps/reporting/services/` | BI-3, BI-4, FOR-7, FOR-9, FOR-10 | 12 JT |
| **L10** | WhatsApp — file, plafond, tenant | Le canal devient exploitable sans intervention manuelle | File d'envoi persistante et reprise **planifiée** (le backoff 5 min / 30 min / 2 h existe déjà mais ne se déclenche qu'à la main) ; limite de fréquence par destinataire ; test vérifiant qu'aucune voie applicative — import, action de masse, tâche planifiée — ne contourne `send_governed_template_message` ; retrait du webhook historique de `apps/core/api_notifications.py` ; routage entrant par tenant plutôt qu'un `WHATSAPP_PHONE_NUMBER_ID` global | `apps/whatsapp/services/messaging.py`, `apps/whatsapp/api.py`, `apps/core/api_notifications.py`, `config/settings/base.py` | WA-1, WA-5, WA-7, WA-10 | 9 JT |

### 4.4 Phase 3 — 13 écarts

| # | Lot | Objectif | Définition de fin | Fichiers principaux | Critères | Effort |
|---|---|---|---|---|---|---|
| **L11** | Qualité — sortir le module de l'ombre | Le HACCP livré devient atteignable par ses utilisateurs | `apps/quality` gagne `views.py`, `urls.py` et `api.py`, est monté dans `config/urls.py` et `config/api.py` ; entrées RBAC ajoutées à `rbac_policy.py` et `docs/RBAC.md` (l'omission y est documentée comme volontaire « à réviser le jour où… » — c'est ce jour) ; écran de la liste des contrôles montrant les contrôles en retard ; types d'événement qualité publiés dans `core.events.PUBLISHED_EVENT_TYPES` pour rendre les non-conformités automatisables | `apps/quality/` (3 fichiers nouveaux), `config/urls.py`, `config/api.py`, `apps/core/services/rbac_policy.py`, `apps/core/events.py`, `docs/RBAC.md` | QUA-9 | 8 JT |
| **L12** | Les égalités affirmées mais non prouvées | Cinq critères passent de « conçu pour » à « vérifié » | Fonction de rejeu de la valeur de stock à une date antérieure, et test l'égalant au solde du compte de stock comptable à l'ariary près ; test égalant le coût débarqué unitaire analytique au coût du moteur de valorisation ; test égalant le coût réel d'un ordre clôturé à la somme rejouée ; test égalant la somme des rubriques de paie au total du journal ; taux de conformité au premier passage recalculé depuis les mouvements et comparé au taux issu des déclarations ; mesure du retour visuel de scan sous 300 ms | `apps/stocks/services/valuation_replay.py` (nouveau), `apps/stocks/tests/`, `apps/mrp/tests/`, `apps/payroll/tests/`, `tests/e2e/` | STK-10, STK-12, ACH-10, PRD-6, PRD-9, P3/PAY-10 | 12 JT |
| **L13** | Inventaire à l'aveugle | Le comptage cesse d'être orienté par la quantité attendue | Mode aveugle sur `StkInventory` ; la quantité attendue n'est exposée ni par le service, ni par l'API, ni par le gabarit tant que la session est ouverte ; test d'accès direct à l'API vérifiant l'absence de fuite | `apps/stocks/models.py`, `apps/stocks/services/inventory.py`, `apps/stocks/api.py`, `templates/stocks/` | STK-6 | 5 JT |
| **L14** | Paie et kanban de production — finitions | Les deux réserves assumées sont levées ou actées | Régularisation calculée en **delta** plutôt qu'en recopie intégrale, ou décision explicite de conserver la recopie et mise à jour du critère avec le maître d'ouvrage ; vérification du kanban `mrp` sur tablette en réseau dégradé (test `tests/e2e/`) | `apps/payroll/services/regularization.py`, `tests/e2e/` | P3/PAY-9, PRD-5 | 5 JT |

### 4.5 Hygiène — à faire au fil de l'eau, pas en fin de vague

| # | Lot | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|---|
| **L15** | Dérive documentaire et secret en clair | Aucun document du dépôt n'affirme un état faux | `README.md` et `CONTRIBUTING.md` : **fait au commit de ce plan** (table d'état reprise sur l'audit, Phase 4 ajoutée, plafonds corrigés, modules manquants ajoutés). Reste à faire : les deux docstrings périmées corrigées (`apps/stocks/services/consistency.py:53`, `apps/sales/services/reports.py:112`). `LogServiceProvider.webhook_secret` et `PrjGuestAccess.token` portés en `EncryptedCharField` avec migration de reprise | `README.md`, `CONTRIBUTING.md`, `apps/stocks/services/consistency.py`, `apps/sales/services/reports.py`, `apps/logistics/models.py` | 3 JT |

### 4.6 Synthèse de la Vague 1

| Bloc | Lots | Effort |
|---|---|---|
| Préalables | L0, L1, L2 | 11 JT |
| Phase 1 | L3, L4, L5, L6, L7, L16 | 50 JT |
| Phase 2 | L8, L9, L10 | 33 JT |
| Phase 3 | L11, L12, L13, L14 | 30 JT |
| Hygiène | L15 | 3 JT |
| **Total** | **16 lots, 51 écarts** | **≈ 127 JT ≈ 8,5 semaines** à 15 JT/semaine |

**Ordre imposé** : L1 → L0 → L2, puis tout le reste en parallèle possible, à deux
exceptions près — L8 précède L9 (un tableau de bord sans dictionnaire peuplé ne se
recette pas) et L1 précède L4, L6, L9, L11 (chacun ajoute au moins un gabarit).

---

## 5. Vague 2 — Phase 4, 34 sprints

Reprise du plan du cahier Phase 4 §16.2, bornes et chiffrages inchangés. Les colonnes
d'effort sont celles du cahier (§17.2) et **ne se convertissent pas** en JT (voir §3).

| Bloc | Contenu | Sprints | J/H | J-Tok | Supervision |
|---|---|---|---|---|---|
| A | Socle de flux, registre, file, incidents, rejeu, cadrage | S1–S6 | 26 | 11 | 10 |
| B | API publique, webhooks, clés, portées, quotas, bac à sable | S7–S9 | 14 | 6 | 5 |
| C | Conformité e-facture et clearance | S10–S16 | 25 | 11 | 14 |
| D | Encaissement mobile et rapprochement | S17–S22 | 25 | 11 | 10 |
| E | Flux bancaires et trésorerie | S23–S25 | 14 | 6 | 5 |
| F | Bureautique, stockage, agenda, partage local | S26–S29 | 18 | 8 | 6 |
| G | Commerce et canaux de vente | S30–S31 | 9 | 4 | 3 |
| H | Console de flux, coûts, plafonds, messagerie | S32–S33 | 9 | 4 | 3 |
| I | Durcissement et mise en production | S34 | 5 | 2 | 2 |
| | **Total** | **34** | **145** | **63** | **58** |

**Jalon J4 — mise en production de la vague 4A** au sprint 16, à l'issue du bloc C.
**Jalon J5 — vague 4B** au sprint 34.

### 5.1 Bloc A — Socle de flux (S1–S6)

Le bloc A ne livre **rien de visible par le client** et conditionne tout le reste :
aucun connecteur ne démarre avant que le registre, la file et le rejeu ne soient
éprouvés. C'est au flux ce que le mouvement unique a été au stock en Phase 3.

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S1 | Cadrage et modèle du socle | App `apps/flows/` créée (`apps.py`, `module.py`, `services/public.py`), 8 entités modélisées : connecteur, identifiant d'accès (chiffré, table à part), liaison, correspondance, planification, déclencheur, échange (partitionné par mois dès la conception), charge utile (table séparée, rétention propre). Budgets d'architecture relevés vers les cibles du cahier (430 / 1 210 / 278 + 12 adaptateurs + 80 opérations publiques) | `apps/flows/models.py`, `config/settings/base.py` | — |
| S2 | Machine à états de l'échange | 9 états implémentés (préparé, en file, émis, accepté, rejeté, en attente de verdict, à réessayer, en échec, suspendu) avec les trois invariants du cahier : accepté et rejeté terminaux, attente de verdict sans expiration mais avec échéance de relance, suspendu pour plafond n'ouvrant pas d'incident. **Point de contrôle du cahier** : le modèle dimensionnel de la Phase 2 accueille le fait d'échange sans reprise des dimensions conformes | `apps/flows/services/exchange.py`, `apps/analytics/models.py` | FLX-2 |
| S3 | File de sortie, réessai, disjoncteur | File persistante adossée à `core/tasks.py::enqueue` (jamais d'import direct de `django_q`, garde CI existante) ; réessai espacé ; **disjoncteur par connecteur et par tenant** — la brique la plus neuve du bloc, aucun précédent dans le dépôt ; incident unique par famille d'erreur, jamais un incident par tentative. Arbitrage H26 (unité de coût de la messagerie) | `apps/flows/services/queue.py`, `apps/flows/models.py::Incident` | FLX-3 |
| S4 | Idempotence, corrélation, rejeu supervisé | Clé d'idempotence **sortante** calculée sur (pièce, liaison, rang de tentative) — extension du patron entrant de `core/idempotency.py` ; clé de corrélation reliant échange sortant, notification entrante et pièce ; rejeu créant de nouveaux échanges, ne réécrivant jamais les anciens | `apps/flows/services/idempotency.py`, `apps/core/idempotency.py` | FLX-4 |
| S5 | Correspondances, planification, déclencheurs | Éditeur de correspondance validé **à l'enregistrement** contre le schéma déclaré du tiers ; planification adossée au calendrier malgache de la Phase 2 ; déclencheurs branchés sur les transitions du moteur de workflow, en effet de bord asynchrone ne pouvant jamais faire échouer la transition métier | `apps/flows/services/mapping.py`, `apps/flows/services/triggers.py`, `apps/core/events.py` | FLX-6, FLX-2 |
| S6 | Durcissement du socle — **jalon de bloc** | Adaptateur factice couvrant les 8 opérations canoniques (OP1–OP8) ; garde CI **échouant si un adaptateur émet un appel réseau hors de l'exécuteur du hub, ou si un échange est écrit sans empreinte** (patron : `tests/architecture/test_no_direct_task_queue_usage.py`) ; rédaction des secrets à l'écriture des journaux ; test d'isolation à deux tenants sur échanges, secrets, liaisons et charges utiles ; purge de charge utile laissant l'échange intact | `tests/architecture/test_flows_boundaries.py`, `apps/flows/tests/` | FLX-1, FLX-5, FLX-7, FLX-8 |

### 5.2 Bloc B — API publique et webhooks (S7–S9)

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S7 | Clés, portées, quotas | Modèle de clé publique par tenant (portées exprimées **en opérations publiques déclarées**, jamais en modèles), débit maximal, expiration, révocation immédiate y compris pour un appel en cours d'authentification ; `apps/core/throttling.py` — écrit mais appliqué à aucun endpoint aujourd'hui — branché par clé et par tenant | `apps/flows/models.py::PublicKey`, `apps/core/throttling.py`, `config/api.py` | API-1, API-6, API-7 |
| S8 | Surface publique déclarée et documentée | Liste blanche d'opérations publiques sur le patron de `endpoint_governance.py`, plafonnée à 80, **avec garde CI** ; OpenAPI publié pour cette surface distincte de la surface interne ; guide d'intégration et politique de dépréciation écrits ; bac à sable avec jeu de données isolé (patron : `apps/core/services/sandbox.py`). Arbitrage H29 (abonnement du connecteur réglementaire) | `apps/core/services/endpoint_governance.py`, `config/api.py`, `docs/` | API-2 |
| S9 | Webhooks entrants et sortants — **jalon de bloc** | Points d'entrée par connecteur avec signature, **fenêtre d'horodatage** et déduplication (patron : `apps/logistics/services/webhooks.py`, à généraliser) ; accusé de réception sous 500 ms puis traitement en file, mesuré ; notifications **sortantes** signées avec abonnement, filtres, réessai et rejeu — aucun précédent dans le dépôt ; jeu de tests de conformité étendant `tests/contract/test_openapi_schemathesis.py`. Vérification de H30 | `apps/flows/services/webhooks.py`, `apps/flows/models.py::NotificationSubscription`, `tests/contract/` | API-3, API-4, API-5 |

### 5.3 Bloc C — Conformité e-facture (S10–S16)

Le bloc le plus incertain et le seul dont la supervision humaine (14 J/H) dépasse la
génération (11 J-Token) : établir *ce qu'il faut soumettre, dans quel format, avec
quelles mentions et quelle durée d'archivage* relève de la lecture de textes, pas du
développement. **H20 et H21 doivent être levées au sprint 10 au plus tard** ; à
défaut, bascule sur le repli « opérateur agréé » (D13).

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S10 | Levée de H20/H21 et modèle du dispositif | Habilitation et spécifications obtenues, ou repli acté. Référentiel de formats, de contrôles et de durées d'archivage porté par `core_regulatory_parameter` (versionné, daté, validable) | `apps/flows/services/einvoice/`, `apps/core/models/regulatory.py` | EFA-7 |
| S11 | Production du document structuré | Depuis une facture validée de `apps/sales`, document normalisé conforme au schéma paramétré ; contrôles de complétude préalables ; champ obligatoire manquant bloquant la soumission **et désignant le champ** | `apps/flows/services/einvoice/builder.py`, `apps/sales/services/public.py` | EFA-1 |
| S12 | Signature et certificat | Signature avec certificat fourni par le client ; alerte d'expiration à 30 jours au moins ; refus de signer avec un certificat expiré, avant soumission | `apps/flows/services/einvoice/signing.py` | EFA-8 |
| S13 | Mode d'attente et file | En l'absence de raccordement ouvert : document produit, signé, archivé, mis en file ; **aucune erreur présentée à l'utilisateur**, bandeau d'état à la place | `apps/flows/services/einvoice/`, `templates/flows/` | EFA-2 |
| S14 | Soumission, verdict, marquage | Soumission, attente, réception du verdict **conservé dans sa forme d'origine** en plus de son interprétation ; identifiant attribué et marquage vérifiable reportés sur la représentation lisible | `apps/flows/services/einvoice/submit.py`, `templates/reports/legal/invoice.html` | EFA-4 |
| S15 | Rejet, annulation, avoir | Motif de rejet **actionnable par un comptable**, reprise proposée ; la correction produit un nouvel échange, jamais une modification de l'échange rejeté ; annulation et avoir traités | `apps/flows/services/einvoice/`, `apps/accounting/services/invoices.py` | EFA-5 |
| S16 | Rejeu à l'ouverture et découplage de l'encaissement — **jalon J4, mise en production 4A** | L'ouverture d'un raccordement rejoue la file en attente dans l'ordre chronologique, sans perte ni doublon, sans autre intervention que la confirmation ; une facture peut être encaissée avant son verdict et un verdict peut arriver après l'encaissement, sans incohérence de statut ni blocage comptable | `apps/flows/services/einvoice/replay.py`, `apps/accounting/services/payments.py` | EFA-3, EFA-6 |

### 5.4 Bloc D — Encaissement mobile (S17–S22)

**H22, H23 et H24 levées au sprint 15**, donc avant le démarrage du bloc — les
enrôlements sont engagés quatre sprints en avance (cahier §16.3).

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S17 | Interface unique d'encaissement (D12) | Interface de service d'encaissement avec **deux implémentations** — agrégateur par défaut, raccordement direct en option — sélectionnée par paramètre de tenant ; bascule sans modification de code et sans reprise des intentions en cours | `apps/flows/services/payments/` | P4/PAY-1 |
| S18 | Intention de règlement | Création depuis une facture ou un ticket de caisse ; lien et code de règlement transmissibles par le canal de messagerie ou affichables au comptoir | `apps/flows/services/payments/intent.py`, `apps/pos/`, `apps/sales/` | — |
| S19 | Notification et rapprochement de premier niveau | Notification entrante rapprochée automatiquement de la pièce d'origine dans le cas nominal, avec écriture d'encaissement sans intervention comptable ; double notification produisant un seul encaissement et une seule écriture | `apps/flows/services/payments/reconcile.py`, `apps/accounting/services/payments.py` | P4/PAY-2, P4/PAY-4 |
| S20 | Cas limites | Paiement orphelin en attente d'affectation, dans un écran dédié, **sans écriture** tant qu'il n'est pas affecté ; montant partiel produisant un encaissement partiel et laissant la pièce ouverte sans lettrage forcé (le comportement existe déjà dans `apps/accounting/services/payments.py`, à raccorder) ; remboursement par contre-écriture tracée | `apps/flows/services/payments/`, `templates/flows/` | P4/PAY-3, P4/PAY-6 |
| S21 | Versement groupé et commission | Rapprochement de second niveau du versement groupé de l'agrégateur avec le lot d'encaissements qu'il couvre, **commission isolée sur son propre compte de charge** | `apps/flows/services/payments/settlement.py` | P4/PAY-5 |
| S22 | Sécurité du rejeu et indicateur — **jalon de bloc** | Le rejeu d'une intention **vérifie l'état auprès du tiers avant toute réémission** (seule protection contre le double débit là où le tiers n'assure pas l'idempotence) ; taux de rapprochement automatique calculé, publié comme indicateur gouverné du dictionnaire, consultable par période et par connecteur. Levée de H25 | `apps/flows/services/payments/replay.py`, `apps/analytics/services/dictionary.py` | P4/PAY-7, P4/PAY-8 |

### 5.5 Bloc E — Flux bancaires (S23–S25)

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S23 | Import multi-format robuste | Correspondance de colonnes paramétrable en repli ; **détection de période déjà chargée** et signalement explicite ; ligne en anomalie isolée dans un rapport de chargement sans interrompre le lot — les deux manquent aujourd'hui à `import_bank_statement` | `apps/accounting/services/bank_reconciliation.py` | BNK-1, BNK-2 |
| S24 | Moteur de règles de rapprochement | Propositions **horodatées avec un niveau de confiance** ; tolérance paramétrable sur montant, référence, tiers et date ; aucune écriture sans validation — l'interdit de la §4.4 du cahier, déjà respecté par `suggest_matches` | `apps/accounting/services/bank_reconciliation.py` | BNK-3 |
| S25 | Ordres de virement — **jalon de bloc** | Ordre exporté rattaché aux pièces qu'il règle, état de remise suivi jusqu'au rapprochement du débit ; ordre de paie n'exposant que bénéficiaire, montant et référence, **vérifié par un test sur le fichier produit** (aujourd'hui le fichier expose en plus l'identifiant salarié et le téléphone) ; alimentation de la prévision de trésorerie de la Phase 2 par le solde réel | `apps/payroll/services/mobile_money.py`, `apps/flows/services/banking/`, `apps/forecast/services/treasury.py` | BNK-4, BNK-5 |

### 5.6 Bloc F — Bureautique, stockage, agenda (S26–S29)

Premier bloc raccourcissable en cas de dérive amont (cahier §16.2).

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S26 | Raccordement par délégation | Autorisation par délégation sur un **compte individuel**, sans exiger d'annuaire d'entreprise administré ; révocation côté tiers détectée, ouvrant un incident de la famille « identifiants à renouveler », jamais un échec silencieux | `apps/flows/services/office/auth.py` | BUR-1, BUR-2 |
| S27 | Dépôt de documents et repli | Dépôt de documents et d'archives avec arborescence et nommage paramétrables ; indisponibilité du tiers basculant sur le stockage objet — `core.Document` passe déjà par l'API `Storage` abstraite précisément pour cela — avec notification et reprise ultérieure | `apps/flows/services/office/storage.py`, `apps/core/models/document.py` | BUR-4 |
| S28 | Feuille de calcul et courriel délégué | Publication d'un jeu de données en remplacement ou en **ajout différentiel n'écrasant pas les colonnes ajoutées par le client** ; envoi de courriel par délégation authentifiée depuis l'adresse du client, en complément du SMTP de la Phase 1 | `apps/flows/services/office/sheets.py`, `apps/flows/services/office/mail.py` | BUR-3 |
| S29 | Agenda, partage local, cloisonnement — **jalon de bloc** | Publication d'événements d'exploitation dans un agenda ; adaptateur de partage de fichiers local ; **aucun champ classé secret industriel ou donnée de paie sélectionnable comme source d'une liaison de cette famille, quel que soit le paramétrage** — s'appuie sur `SENSITIVE_FIELDS` (`apps/core/services/permissions.py:27`) | `apps/flows/services/office/calendar.py`, `apps/flows/services/mapping.py` | BUR-5 |

### 5.7 Bloc G — Commerce (S30–S31)

Connecteur **générique** plutôt qu'un adaptateur par plateforme.

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S30 | Publication et correspondance d'articles | Publication du catalogue et des disponibilités reflétant le **stock disponible à la vente au sens de la Phase 3, réservations déduites** (`StkReservation`), et non le stock physique ; table de correspondance entre référentiel interne et référence de boutique | `apps/flows/services/commerce/`, `apps/stocks/services/public.py` | COM-3 |
| S31 | Ingestion des commandes — **jalon de bloc** | Commande ingérée créant un document au **statut initial**, sans facture, sans mouvement de stock, sans écriture ; article sans correspondance plaçant la commande en anomalie sans bloquer l'ingestion des autres ; commande reçue en double identifiée par sa référence de boutique ne créant qu'un document ; retour du statut d'expédition | `apps/flows/services/commerce/ingest.py`, `apps/sales/services/public.py` | COM-1, COM-2, COM-4 |

### 5.8 Bloc H — Console de flux et coûts (S32–S33)

| S | Objectif | Définition de fin | Fichiers / app | Critères |
|---|---|---|---|---|
| S32 | Console, consentements, coûts | Tableau de bord des échanges ; depuis toute pièce, l'état de ses échanges en un clic et réciproquement ; consentement de sortie **immuable** exigé à l'activation, affichant catégories de données, tiers, pays et durée de conservation, journalisé avec son auteur (patron : `WaConversation.consent_*`) ; révocation coupant immédiatement, conservant les échanges passés, proposant la purge des charges utiles ; alerte à l'approche d'un plafond (généralisation de `whatsapp_cost_alert_threshold_pct`) | `apps/flows/views.py`, `apps/flows/models.py::OutboundConsent`, `templates/flows/` | CON-1, CON-2, CON-3, CON-5 |
| S33 | Rejeu, garantie de sortie, messagerie — **jalon de bloc** | Panneau de rejeu affichant volume et coût estimé **avant** confirmation, aucun rejeu de masse sans estimation ; export de garantie de sortie produisant liaisons, échanges, verdicts et rapprochements dans un format documenté relisible sans WideHalo (extension de `apps/core/services/tenant_export.py`) ; messagerie basculée sur la facturation **au message délivré**, historiques antérieurs restant lisibles dans leur unité d'origine avec date de bascule visible | `apps/flows/views.py`, `apps/core/services/tenant_export.py`, `apps/whatsapp/services/usage.py` | CON-4, CON-6, MSG-1, MSG-2 |

### 5.9 Bloc I — Durcissement et mise en production (S34)

| S | Objectif | Définition de fin | Critères |
|---|---|---|---|
| S34 | **Jalon J5** | Scénario de recette « **tout coupé** » : l'intégralité des connecteurs désactivée, les parcours des Phases 1 à 3 restent exécutables de bout en bout en mode saisie — c'est la barrière qui transforme en exigence vérifiable la règle posée en Phase 1 et reconduite deux fois. Test de charge sur les rafales entrantes. Revue de sécurité de la surface publique. Budgets d'architecture re-mesurés et comparés aux cibles ; un décompte de modèles au-delà de 70 pour le socle de flux est le signal d'alerte que le cahier désigne lui-même (§11.1) | MSG-3 (déjà tenu, à ne pas régresser) |

---

## 6. Risques

| Réf. | Risque | Prob. | Impact | Mitigation et signal d'alerte |
|---|---|---|---|---|
| R1 | **La capacité hebdomadaire continue de baisser.** 5 → 4,5 → 4 → 3,5 jours effectifs en trois phases ; le cahier Phase 4 le pose lui-même en §17.3 et note que l'arbitrage du support a été reporté deux fois | Élevée | Élevé | Trancher **avant la fin de la Vague 1**, pas au démarrage de la Phase 4 : industrialiser le support, le déléguer même à temps partiel, ou acter le passage en régime de maintenance. La Phase 4 aggrave le problème d'une nature nouvelle — un connecteur en panne est un incident urgent qui survient quand le tiers le décide. Signal : tout lot de la Vague 1 dépassant son estimation de plus de 50 %. |
| R2 | **Le calendrier fiscal n'appartient pas à l'éditeur** (H20, H21) | Moyenne | Élevé | La vague 4A livre le moteur et un mode d'attente vérifiable sans attendre la publication des spécifications ; repli « opérateur agréé » activable par paramètre (D13). Signal : sprint 10 atteint sans habilitation. |
| R3 | **Le plafond d'écrans bloque la Vague 1 dès son premier gabarit** | Certaine si L1 n'est pas fait en premier | Moyen | L1 avant tout le reste. Signal : un échec de `test_budget.py` en CI. |
| R4 | **L'ordonnanceur révèle des traitements jamais exécutés en conditions réelles.** Neuf commandes n'ont probablement jamais tourné sur un jeu de données vivant | Élevée | Moyen | L0 est un lot de 4 JT d'écriture, mais prévoir une fenêtre d'observation : première exécution sur un jeu représentatif, avant de compter les critères comme fermés. Signal : `AnRefreshRun` en échec ou durée anormale à la première exécution. |
| R5 | **Le dictionnaire d'indicateurs reste vide** parce que sa définition n'est pas un travail de développement mais de cadrage avec le client | Moyenne | Élevé | L8 livre l'écran et le jeu de départ ; la définition des indicateurs propres au client est à engager en parallèle, comme le cahier Phase 2 le prévoyait déjà (« le seul travail qui ne peut être ni délégué ni décidé par l'éditeur »). Signal : L9 prêt sans indicateur client saisi. |
| R6 | **Douze adaptateurs à maintenir pour une personne seule** (H28) | Moyenne | Élevé | Plafond d'adaptateurs vérifié en CI ; suite de contrats de test par adaptateur exécutée quotidiennement contre l'environnement d'essai du tiers ; un tiers sans environnement d'essai est écarté à ce titre. Signal : plus de deux ruptures d'interface par an et par connecteur → plafond ramené de 12 à 8. |
| R7 | **La décision D10 laisse un critère du cahier Phase 1 ouvert** (abstraction PCG/SYSCOHADA, ACC-2) | Certaine | Faible à court terme | À acter explicitement avec le maître d'ouvrage plutôt qu'à laisser passer : c'est un critère du cahier que ce plan ne ferme pas. Signal : ouverture d'un tenant hors Madagascar. |

---

## 7. Ce que ce plan ne traite pas

- **L'abstraction du référentiel comptable** (D10) — chantier propre, avec son ADR.
- **Les trois critères ❓** (P1/CRM-7, P1/ACC-6, P2/BI-5) : ils demandent une mesure de
  parcours ou de temps de chargement, pas du code. À instrumenter dans `tests/e2e/`
  si le maître d'ouvrage veut les fermer, ce qui est un lot à part.
- **Les deux critères N/A** (P3/QUA-10, P3/PAY-12) : exercice de rappel blanc validé
  par le contrôleur qualité du client, et jeu de bulletins témoins signé par un
  expert-comptable OECFM. Ce sont des actions à planifier avec le client, pas du
  développement.
- **L'isolation du copilote au niveau du rôle PostgreSQL** (§3.7 de l'audit) : relève
  de l'exploitation, à traiter avec le déploiement.
