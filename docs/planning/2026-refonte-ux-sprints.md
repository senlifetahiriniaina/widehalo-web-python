# WideHalo v3 — Planning sprints hebdomadaires (Jour-Token) — Refonte UX

Source : *WideHalo v3 — Cahier des charges (refonte UX) & Dossier d'Architecture Technique
(DAT)*, dossier fourni par le donneur d'ordre. Ce document traduit ce cahier des charges en
sprints hebdomadaires chiffrés en Jour-Token, avec une insistance délibérée sur l'UX/UI et
le raffinement de la présentation à chaque étape — pas seulement en fin de projet.

> **Révisions après le Sprint 0.**
> 1. *Périmètre* : le Sprint 0 (inventaire réel du dépôt, voir
>    `docs/planning/ECART_ARCHITECTURE.md`) a mesuré **218 écrans déjà livrés** sur 22 apps
>    (Lot 1 + Lot 2 Madagascar), bien au-delà des ~90-110 écrans supposés par le cahier des
>    charges. **Décision actée avec l'utilisateur** : la migration « strangler pattern »
>    couvre l'intégralité de ces écrans en Phase 1, sans exception — d'où le lot **L9**
>    (§5 bis) et un total révisé à **152 JT**.
> 2. *Vitesse* : la capacité hebdomadaire est révisée de **5 à 15 Jour-Token par semaine**
>    (2ème décision actée avec l'utilisateur). À périmètre inchangé (152 JT), le planning
>    passe de 34 à **16 semaines (Sprint 0 à Sprint 15, ≈ 3,7 mois)** — voir §2 et §7.

## 1. Rappel du chiffrage source

Le dossier chiffre l'effort en Jour-Homme (J/H) **et** en Jour-Token (JT — journée de
travail assistée par Claude Code, génération/refactor de composants et écrans à partir de
specs, estimée ~2,5× plus productive que le J/H pur sur du CRUD et des composants
répétitifs, avec un gain moindre sur les moteurs transverses et la logique réglementaire) :

| Lot | Contenu | J/H (dossier) | JT (dossier) | JT révisé (§5 bis) | Priorité |
|---|---|---|---|---|---|
| L0 | Fondations (design system, tokens, shell/launchpad, breadcrumb, recherche globale) | 20 | 8 | 8 | Must |
| L1 | Data grid & vues (moteur de vues/metadata, list/kanban, filtres sauvegardés) | 25 | 10 | 10 | Must |
| L2 | Formulaires & chatter (validation inline, chatter, activités, notifications) | 20 | 8 | 8 | Must |
| L3 | Textile (matrice tailles×couleurs, OF/atelier, import/CREDOC/landed cost) | 30 | 12 | **28** | Must |
| L4 | Agro (lots/DLC/FEFO, transformation/rendement, HACCP/rappel) | 30 | 12 | **19** | Must |
| L5 | Compta/Paie MG (abstraction PCG 2005/SYSCOHADA, TVA/IRSA/CNaPS/OSTIE/FMFP) | 25 | 10 | **16** | Must |
| L6 | Personnalisation & offline (préférences, PWA/mode dégradé, dark mode) | 15 | 6 | 6 | Should |
| L7 | IA gateway (widehalo-ai-gateway, function-calling lecture seule) | 10 | 5 | **8** | Should |
| L9 | **Rattrapage du catalogue existant** (nouveau, §5 bis) | — | — | **39** | Must (décision utilisateur) |
| **Total Phase 1** | | **~175** | **~71** | **~142 (+ Sprint 0 = 147, + recette = 152)** | |

L8 (activation SYSCOHADA / roadmap OHADA, Côte d'Ivoire en priorité) reste **hors
périmètre** de ce planning (backlog "Could", Phase 2). Le total en JT (152) est identique
à la révision précédente de ce document — seule la **vitesse hebdomadaire** change (§2),
pas le contenu ni le chiffrage des lots.

## 2. Cadence retenue

- **1 sprint = 1 semaine = 15 Jour-Token** (révisé — était 5 JT/semaine). Capacité d'un
  développeur solo à temps plein, plus fortement assisté par Claude Code que l'hypothèse
  initiale du cahier des charges.
- **Gabarit fixe appliqué à chaque sprint**, pour que l'UX/UI et le raffinement de la
  présentation ne soient jamais relégués à la fin — mêmes proportions qu'avant (60 % /
  20 % / 20 %), simplement mises à l'échelle des 15 JT hebdomadaires :

  | Jours | JT | Contenu |
  |---|---|---|
  | J1–J3 | 9 JT | Construction : composants/écrans du lot (specs A.8 bibliothèque de composants, A.9 écrans par verticale) |
  | J4 | 3 JT | Intégration + vérification des critères d'acceptation du lot (cahier des charges) |
  | **J5** | **3 JT** | **Jour de raffinement UX** : micro-interactions, accessibilité (contraste WCAG AA, navigation clavier, ARIA), densité (confortable/compacte), dark mode, responsive/tablette (cibles tactiles ≥ 44 px), empty states / états d'erreur / de chargement, cohérence stricte avec la bibliothèque de composants et les design tokens. Mesure quand applicable (SUS, SEQ, temps par tâche, nombre de clics — A.14). |

  Le triplement de la capacité par jour (1 JT/jour → 3 JT/jour) donne mécaniquement
  **3× plus de temps de raffinement UX par sprint** (3 JT au lieu de 1) — cohérent avec
  l'insistance de l'utilisateur sur l'UX/UI, pas seulement un raccourcissement du planning.
- **Budget total : 152 JT sur 16 sprints (Sprint 0 à Sprint 15, ≈ 16 semaines / ~3,7
  mois)**, contre 34 semaines à l'ancienne vitesse. Le détail par lot est en §5 et §5 bis.

## 3. Écart de stack identifié et décision

Le dossier préconise **Tailwind + DaisyUI + django-cotton + HTMX/Alpine** comme socle de
présentation. Le dépôt `widehalo-web-python` avait un design system maison mature
(`widehalo/static/css/tokens.css`, `app.css`, composants Django templates + HTMX + Alpine,
admin django-unfold), sans Tailwind ni django-cotton.

**Décision actée** : migrer vers le socle préconisé par le dossier (Tailwind + DaisyUI +
django-cotton), en portant les tokens de couleurs/espacements existants
(`--halo-*`, `--amber-*`, `--slate-*`) dans la configuration Tailwind, pour ne pas perdre
l'identité visuelle déjà posée. **Réalisé** dans le Sprint 0 (PR
`claude/sprint-0-inventaire-stack`) : build Tailwind v4 + DaisyUI sans couche "preflight"
(coexistence sans régression sur les écrans non migrés), deux premiers composants
`django-cotton` (`<c-button>`, `<c-kpi-tile>`), écran de preuve `/settings/design-system/`.

## 4. Sprint 0 — Inventaire, écart, socle technique (5 JT) — RÉALISÉ

Reprend l'« Action requise de Claude Code en préambule » du cahier des charges :

- **Inventaire** : par introspection Django (réutilise les compteurs de
  `tests/architecture/test_budget.py`, déjà existant). Produit
  `docs/planning/ECART_ARCHITECTURE.md` confrontant le réel (254 modèles / 515 endpoints /
  218 écrans) aux budgets déclarés (180/600/90 dossier, 200/650/110 recommandation
  dossier, 290/600/240 plafonds CI réels déjà en place). Constat clé : le garde-fou CI
  anti-dérive demandé par le dossier (B.9) **existait déjà** ; le dépôt est bien plus
  avancé que supposé (Lot 2 Madagascar largement livré) — `README.md` corrigé en
  conséquence.
- **Socle technique** : Tailwind + DaisyUI + django-cotton en coexistence avec le système
  existant (build sans preflight — voir §3), tokens `tokens.css` portés vers le thème
  Tailwind/DaisyUI.
- **Raffinement** : vérification visuelle du socle porté (aucune régression sur les
  écrans existants), ajustement du test CI de budget d'architecture existant pour exclure
  `templates/cotton/` du comptage des écrans (bibliothèque de composants, pas des écrans).

**Critère d'acceptation** : ✅ le socle Tailwind/DaisyUI/django-cotton compile et coexiste
avec l'UI legacy sans régression visuelle ; le fichier d'écart est produit et devient le
point de vérité qui remplace les hypothèses du cahier des charges (y compris sur le
périmètre de migration, tranché en §5 bis).

## 5. Sprints par lot (construction des écrans critiques du cahier des charges)

### Sprint 1 — L0 Fondations (8 JT / 15 disponibles) — RÉALISÉ (partiellement)

Livré (commit `985c9bf`, poussé directement sur `madagascar1`) : shell applicatif
(`<c-shell>`, logo + app switcher type Odoo/Fiori), launchpad par rôle
(`/launchpad/`, tuiles de navigation + tuiles KPI, toutes deux gardées par
`visible_app_labels_for` — RBAC N1 identique à la sidebar legacy), fil d'Ariane
(`<c-breadcrumb>`), recherche globale en command palette (Ctrl/Cmd+K, réutilise
`global_search`/`/search/instant/` existants), cloche de notifications (compteur live par
polling HTMX, réutilise le modèle `Notification` existant). Coexistence strangler pattern
via bascule de session (`toggle_shell`) : `/dashboard/` redirige vers `/launchpad/` une
fois la bascule activée, jamais l'inverse automatiquement ; point d'entrée additionnel
("Essayer la nouvelle interface (bêta)") depuis le menu compte legacy.

**Reporté** (hors 8 JT engagés, à couvrir par le Jour de raffinement d'un sprint suivant
ou un correctif ciblé) : menu utilisateur langue FR/MG/EN et bascule dark mode (stubs
visuels seulement) ; migration réelle des 18 écrans racine autres que `/dashboard/`
(`search.html`, `settings.html`, etc. restent sur l'ancien shell — seul `/dashboard/`
redirige) ; favoris/tâches récentes du launchpad (emplacement vide assumé, personnalisation
réelle = lot L6).

- **Critères d'acceptation** : ✅ chaque utilisateur voit un launchpad filtré par son rôle
  métier (`tests/ui/test_shell_toggle.py::test_launchpad_shows_only_role_visible_apps`) ;
  ✅ tous les écrans du nouveau shell sont composés exclusivement à partir de la
  bibliothèque de composants cotton ; recherche globale < 100 ms perçu — non mesuré
  (nécessite un environnement avec données réelles, à faire au Sprint 15/recette).
- **Raffinement effectué** : contrôles icône-seule avec `aria-label` (app switcher, cloche,
  recherche mobile), audit accessibilité automatisé étendu à `/launchpad/`
  (`tests/ui/test_accessibility.py`), build Tailwind sans "preflight" vérifié sans
  régression sur les 219 écrans existants.

### Sprint 2 — L1 Data grid & vues (10 JT / 15 disponibles) — RÉALISÉ (partiellement)

Livré (commit `2a03da4`) : le rapport d'exploration a montré qu'un moteur SmartTable
substantiel existait déjà (pagination serveur, tri, recherche, export, `SavedTableView`),
réutilisé par 27 écrans — étendu plutôt que reconstruit. Actions de masse (`BulkAction`,
cases à cocher + colonne figée, formulaire natif sans JS) opt-in ; boucle CRUD des vues
sauvegardées fermée (sélecteur + "Enregistrer la vue actuelle", mapping tri/colonnes
masquées/recherche texte) ; preuve d'usage bout en bout ("Archiver la sélection" sur
`/documents/`, réutilisant `BaseModel.soft_delete()`).

**Reporté** : moteur de vues piloté par métadonnées en base façon Odoo
(`ui_view_definition` — n'existe pas, gros chantier séparé) ; kanban généralisé avec
drag-drop (l'unique kanban existant, `apps/projects`, reste en lecture seule) ; filtres
par champ au-delà de la recherche texte globale unique.

- **Critères d'acceptation** : ✅ pagination serveur systématique (déjà en place, non
  régressée) ; changement de vue list ↔ kanban — non traité (kanban généralisé reporté).
- **Raffinement effectué** : colonne de sélection figée (sticky), formulaire de vue
  sauvegardée cohérent avec le style SmartTable existant.

### Sprint 3 — L2 Formulaires & chatter (8 JT / 15 disponibles) — RÉALISÉ (partiellement)

Livré (commit `9a96267`) : aucun chatter Odoo-style n'existait (`apps.chat` est une
messagerie temps réel distincte, `AuditLog` un journal de conformité non pensé pour
l'affichage, `CrmActivity` spécifique au CRM) — construit réellement neuf.
`ChatterMessage` (fil générique par `GenericForeignKey`, messages + notes internes),
`<c-chatter>` (chargement HTMX paresseux, formulaire natif), première utilisation réelle
sur `/sales/orders/<id>/`. Notifications contextuelles avec action : convention
`payload.action_url`/`action_label`, premier appelant réel dans
`apps.sales.services.orders._notify_salesperson`.

**Reporté** : activités planifiées génériques (généraliser `CrmActivity` au-delà du CRM) ;
formulaires longs par onglets avec validation inline HTMX par champ (aucun `forms.py`
n'existe encore dans le dépôt — chantier plus large) ; autosave de brouillon.

- **Critères d'acceptation** : autosave hors-ligne — non traité (reporté) ; ✅ chatter
  disponible sur au moins un objet clé du périmètre (commande de vente) — généralisation
  aux autres objets à poursuivre lot par lot.
- **Raffinement effectué** : note interne visuellement distincte (fond ambre) du message
  normal, badge dédié.

### Sprints 4–5 — L3 Textile (28 JT / 30 disponibles)

**Sprint 4, écran T1 — RÉALISÉ (partiellement)** : livré (commit `63fe60b`). Le rapport
d'exploration a montré que le modèle de données était déjà quasi complet
(`ProductTemplate`/`ProductVariant`, génération cartésienne des variantes déjà
implémentée, BOM déjà variant-aware via `qty_by_size`) — seules deux vraies lacunes
comblées : grille éditable tailles×couleurs (`apps.catalog.views._variant_matrix`,
matrice 2D quand le gabarit a exactement 2 attributs générateurs) et EAN-13/GTIN par
variante (`apps.catalog.services.barcodes`, premier vrai calcul de clé de contrôle GS1
du dépôt, généré automatiquement à la création). **Critère d'acceptation T1(a) validé par
test** : 8 tailles × 6 couleurs → 48 SKU + 48 EAN-13 uniques et valides (temps de
génération non chronométré en environnement CI, mais purement en mémoire/DB locale —
risque de dépassement des 2 s jugé faible).

Livré (commit `8aaea44`) pour **T2** : `MrpWorkOrder` (exécution par étape de gamme) et
`MrpSubcontractOrder` (façon/CMT) existaient déjà pleinement fonctionnels ;
`MrpWorkcenter.TYPE_CHOICES` modélise déjà coupe/couture/broderie/impression/finition/
contrôle/emballage — aucun nouveau champ. First Pass Yield était même déjà implémenté
(`services.quality.first_pass_yield`), simplement jamais affiché. Nouveau
`services.orders.advance_work_order` : termine l'étape courante, démarre automatiquement la
suivante en attente (jamais si déjà mise en pause par un opérateur), journalise la
transition sur le chatter de l'ordre. Nouvel écran `mrp:kanban` (une colonne par poste de
charge, une carte par ordre de travail, bouton — jamais de glisser-déposer, cohérent avec
l'unique autre kanban du dépôt, `apps.projects` — cibles ≥ 44 px). Chatter câblé sur `mrp`
pour la première fois. 7 tests (`test_kanban.py`).

- **Écran T2** — Ordre de fabrication + suivi atelier (kanban coupe→couture→finition),
  sous-traitance façon (CMT), First Pass Yield.
  *Critère* : ✅ déplacer une carte change l'état et journalise dans le chatter ; ✅ cibles
  ≥ 44 px ; ⚠️ « fonctionne sur réseau faible » non mesuré (pas d'environnement de test
  réseau contraint disponible).
Livré (commit `19c6889`) pour **T3** : le workflow CREDOC (FSM linéaire `demande→ouvert→
documents_recus→paye→clos`, banques émettrice/notificatrice/bénéficiaire) et le moteur de
coût de revient débarqué (landed cost, application par SKU, déclenché par la clôture du
dossier douanier) existaient déjà pleinement fonctionnels. Seule « l'alerte sur écart de
change Ariary » manquait : nouveau champ `FinCredoc.amount_foreign` (montant en devise
d'origine, `None` si MGA), `create_credoc` exige ce champ pour toute devise ≠ MGA, nouvelle
fonction `services.credoc.credoc_fx_variance` (reconversion au taux du jour vs. montant MGA
constaté à l'ouverture, seuil de matérialité disclosed à 2 %) et `services.public.
convert_amount_to_mga` (enveloppe fine côté `accounting`, pour respecter la règle de
couplage n°1). Écrans `credoc_create`/`credoc_detail` mis à jour ; bug d'affichage
préexistant corrigé au passage (montant toujours en MGA mais étiqueté avec le code devise
brut). 5 tests (`test_credoc_fx_variance.py`).

- **Écran T3** — Dossier d'import + CREDOC + landed cost (flux banque émettrice → banque
  notificatrice → bénéficiaire, coût de revient débarqué par SKU).
  *Critère* : ✅ statuts CREDOC conformes au flux (préexistant) ; ✅ alerte sur écart de
  change Ariary (`credoc_fx_variance`, seuil 2 %).
Livré (commit `d2df8cb`) pour la **migration du catalogue existant du domaine (Sprint 5)** :
les 45 écrans déjà livrés dans `catalog` (16), `mrp` (12 — `kanban.html` exclu, écran neuf
de la semaine qui évite volontairement Tailwind) et `purchase` (17) passent au nouveau
design system, même traitement que les Sprints 7/9 (`<c-breadcrumb>` + `<c-button>`,
`variant="danger"` sur les actions destructrices/de blocage : annulation, rejet, ouverture
de litige, déclaration de rupture). `tailwind-input.css` élargi à
`templates/catalog/**/*.html`, `templates/mrp/**/*.html` et `templates/purchase/**/*.html`.

- **Critères d'acceptation** : ✅ fil d'Ariane présent sur chaque écran migré ; ⚠️ pas tous
  les écrans composés *exclusivement* de composants cotton (les tableaux
  `<table class="smart-table">` restent en l'état, `<c-table>` n'existe pas encore).
- **Raffinement renforcé (les deux sprints)** : ergonomie de la grille éditable
  tailles×couleurs (saisie clavier rapide), lisibilité du kanban atelier sur tablette en
  conditions de réseau faible.

### Sprints 6–7 — L4 Agro (19 JT / 30 disponibles) — RÉALISÉ (partiellement)

Livré (commit `5e41842`) pour **A1** : le modèle `StkLot` (DLC/DLUO/n° de lot/fournisseur)
existait déjà, mais les écrans de saisie et la suggestion FEFO n'étaient pas exposés à
l'utilisateur — corrigé cette semaine. Champs lot (nom, date de production, date de
péremption, lot fournisseur) ajoutés au formulaire de réception dans
`templates/stocks/index.html` ; en sortie/mouvement interne, un bouton HTMX
(`stocks:fefo_suggestion`, `apps/stocks/views.py::fefo_suggestion`) interroge
`apps.stocks.services.quants.select_lot_fefo` et affiche les lots par ordre de péremption
croissante (fragment `templates/stocks/_fefo_suggestion.html`) — l'utilisateur choisit
explicitement le lot proposé (FEFO reste une **suggestion**, jamais une auto-application,
conformément au docstring de `select_lot_fefo` lui-même). 4 tests dans
`tests/ui/test_stocks_lot_dlc.py`.

- **Écran A1** — Réception + lots + DLC/DLUO.
  *Critère* : ✅ tout mouvement porte un n° de lot (création/saisie possible) ;
  ⚠️ FEFO **suggéré** (bouton explicite), non « appliqué automatiquement » comme l'exigeait
  le libellé initial du dossier — écart assumé, déjà documenté dans le code existant avant
  cette session.

Livré (commit `8839f45`) pour **A2** : `MrpOrder` couvrait déjà tout le cycle de vie
draft→...→closed, mais ne créait jusque-là aucun mouvement de stock ni lot — écart déjà
documenté (`apps.stocks.services.consistency.production_consistency_report`) comme un
manque RG-STK-6 réel. Nouveau modèle `StkLotGenealogy` (lien parent/enfant entre lots) +
`apps.stocks.services.genealogy` (arbre amont/aval, garde anti-cycle) ; `stocks.services.public`
étendu (`receive_production_output`, `record_lot_genealogy`, `lot_genealogy_tree`,
`get_or_create_lot`, `list_locations`) — seule surface que `mrp` est autorisé à importer
(`test_module_boundaries`, respecté). Côté `mrp` : `services/transformation.py`
(`finish_transformation_order`, `record_component_consumption`, `order_yield`,
`order_genealogy`) et un champ `MrpOrder.output_lot_name`. Écran étendu : lot de sortie +
emplacement de réception à la clôture, saisie du lot/quantité consommée par composant,
rendement réel vs théorique et généalogie amont affichés. 100 % rétrocompatible (un ordre
sans lot de sortie renseigné se comporte exactement comme avant). 9 tests
(`test_lot_genealogy.py`, `test_transformation.py`).

- **Écran A2** — Ordre de transformation + rendement + généalogie de lot.
  *Critère* : ✅ rendement réel (`qty_produced`) vs théorique (`qty`) affiché ;
  ✅ généalogie amont/aval consultable depuis le lot de sortie.

Livré (commit `e0c0b02`) pour **A3** : `StkQualityState.STATE_EN_QUARANTAINE` existait déjà
comme classification, mais rien n'empêchait de continuer à expédier/consommer un lot pourtant
mis en quarantaine (aucun `StkMove` n'était bloqué pour cet état). `StkLot.is_held()` dérive
l'état courant du lot depuis son dernier `StkQualityState` ; `services.moves.create_move`
(RG-STK-11) refuse désormais tout mouvement d'un lot bloqué (`en_quarantaine`/
`defaut_majeur`/`rebut`) sauf vers un emplacement de quarantaine/rebut lui-même — sans
régression pour `apply_quality_decision` (déjà testé, continue de fonctionner). Nouveau
modèle `StkRecall` (journal horodaté, `ReferenceMixin`) + `services/recall.py` :
`declare_recall` calcule le périmètre impacté (lot + tous ses descendants, en réutilisant
`services.genealogy.genealogy_tree` d'A2), le fige dans le journal, place chaque lot impacté
en quarantaine et capture l'exposition client connue (`services.traceability.
lot_traceability`, A1/ST8) — aucune logique de traçabilité réinventée, uniquement composée.
Écran : bouton « Déclarer un rappel » sur l'écran de traçabilité existant + nouvel onglet
« Rappels produit » (liste + clôture) — aucun nouveau gabarit créé (le plafond de 90 écrans,
`test_budget`, est déjà quasi atteint ; extension de `stocks/index.html` comme tout le reste
du module). 5 tests (`test_recall.py`).

- **Écran A3** — Contrôle qualité + hold/release + rappel produit.
  *Critère* : ✅ un lot suspect liste ses lots finis impactés (généalogie multi-niveaux) et
  son exposition client connue ; ✅ journal horodaté (incident, timestamp, initiateur,
  périmètre) ; ⚠️ HACCP/non-conformité au sens strict (checklist `QltInspection`) non relié à
  ce flux — `QltInspection` reste un enregistrement ponctuel indépendant, non modifié cette
  session.

Livré (commit `733bea7`) pour la **migration du catalogue existant du domaine (Sprint 7)** :
`stocks` (application mono-page pilotée par `active_tab`, plafond de 90 écrans déjà quasi
atteint — aucun nouveau gabarit possible) et `logistics` (17 écrans) migrés. La barre d'onglets
legacy de `stocks/index.html` devient une barre DaisyUI (`tabs tabs-boxed`) avec l'onglet
courant surligné — plus adapté à cette architecture mono-page qu'un fil d'Ariane classique ;
les 2 écrans d'import restés en gabarit séparé reçoivent `<c-breadcrumb>`. `logistics` reçoit
le même traitement que Sprint 9 (`<c-breadcrumb>` + `<c-button>`, `variant="danger"` sur
l'action « Bloquer » une expédition).

- **Raffinement effectué** : barre d'onglets `stocks` avec état actif visuellement distinct
  (`tab-active`) — clarté de navigation directement utile au parcours de traçabilité
  d'urgence (rappel produit, A3).

**Reporté** (hors périmètre traité cette semaine) :
- **Portage de `_smart_table.html` vers `<c-table>`** : identique au report du Sprint 9, seul
  chantier de migration restant, non entamé.

### Sprints 8–9 — L5 Compta/Paie Madagascar (16 JT / 30 disponibles) — RÉALISÉ (partiellement)

Livré (commit `5e41842`) pour **X3** : le moteur de calcul du bulletin
(`apps.payroll.services.payslip.compute_payslip`) et le référentiel réglementaire versionné
existaient déjà (IRSA, CNaPS, OSTIE, plafond social) — la cotisation **FMFP** (Fonds de
Formation Professionnelle, 1 % patronal, pas de part salariale) en manquait : ajoutée via
`RegulatoryParameter` (code `payroll.fmfp_rate`), `PayrollParams.fmfp_employer_rate`, et une
nouvelle règle `FMFP_PAT` (séquence 95) dans `payroll_structure_mg.json`, intégrée à
`social_employer`. Deux écrans manquants ajoutés : détail d'un bulletin
(`payroll:payslip_detail`, KPI + détail ligne à ligne) et téléchargement PDF
(`payroll:payslip_download`), avec contrôle d'accès (RG-PAY-9 : uniquement l'employé
propriétaire ou un rôle staff, 403 sinon) — corrige au passage un lien mort dans
`templates/payroll/my_payslips.html` qui pointait vers lui-même. 5 tests dans
`apps/payroll/tests/test_x3_fmfp_and_views.py`.

- **Critères d'acceptation** : ✅ aucun barème réglementaire en dur, FMFP compris (lu depuis
  la table versionnée à la date d'effet) ; ⚠️ validation par un expert-comptable OECFM —
  non applicable dans ce contexte (pas d'expert-comptable disponible pour cette session) ;
  ✅ plafond social (8×SME) déjà calculé dynamiquement (préexistant).

Livré (commit `0a81913`) pour **X2** : aucun écran de saisie d'écriture comptable
libre/multi-lignes n'existait (uniquement des écritures générées automatiquement par
d'autres domaines) — le cycle de vie brouillon→publication (`services/moves.py` :
partie double RG-ACC-1, numérotation RG-ACC-3, périodes closes RG-ACC-4) existait déjà et
n'était simplement pas exposé à un utilisateur. Trois écrans ajoutés
(`accounting:quick_entry_list/create/detail`) suivant le patron déjà établi par les écrans
facture ; nouveau `services/quick_entry.py::suggest_counterpart_account` (heuristique de
co-occurrence — le compte le plus souvent associé à un autre sur une même écriture
historique, aucun barème en dur). 5 tests (`test_x2_quick_entry.py`).

- **Écran X2** — Saisie comptable rapide.
  *Critère* : ✅ écriture équilibrée obligatoire avant publication (le service refuse déjà
  toute écriture déséquilibrée) ; ✅ contrepartie suggérée à partir de l'historique.

Livré (commit `7e25f1a`) pour la **migration du catalogue existant du domaine (Sprint 9)** :
premier ré-habillage réel d'écrans CRUD existants vers Tailwind/DaisyUI/cotton depuis le
début du projet (les Sprints 1 et 2 documentaient déjà ce même report pour les écrans
racine/catalog/mrp/purchase — aucun n'avait encore été fait). Prérequis découvert en cours
de route : `tailwind-input.css` ne scannait (`@source`) que `templates/cotton/**` et les
fichiers `tw-*.html` — une classe Tailwind ajoutée directement dans un écran existant
n'aurait eu aucun effet sans élargir ce scan ; élargi à `templates/accounting/**/*.html` et
`templates/payroll/**/*.html`, `tailwind.css` reconstruit. Les 18 écrans `accounting`
(factures, X2, configuration, imports, rapports) et les 3 écrans `payroll` (mes bulletins,
détail bulletin, tableau de bord RH) reçoivent `<c-breadcrumb>` (fil d'Ariane, A.7) et
`<c-button>` pour les actions de formulaire.

- **Critères d'acceptation** : ✅ fil d'Ariane présent sur chaque écran migré ; ⚠️ pas tous
  les écrans composés *exclusivement* de composants cotton (les tableaux
  `<table class="smart-table">` restent en l'état, `<c-table>` n'existe pas encore).
- **Raffinement effectué** : `variant="danger"` sur les actions destructrices (annulation de
  facture, écartement de ligne d'import) pour une distinction visuelle immédiate.

**Reporté** (hors périmètre traité cette semaine) :
- **Portage de `_smart_table.html` vers un composant `<c-table>`** : chantier séparé, non
  entamé — les tableaux des écrans migrés restent donc visuellement inchangés.
- **Raffinement renforcé** : écarts PCG 2005 vs SYSCOHADA — sans objet, aucun tenant
  SYSCOHADA de test disponible pour valider visuellement la distinction.

### Sprint 10 — L6 Personnalisation & offline (6 JT / 15 disponibles)
Personnalisation utilisateur (`user_preference` : colonnes, densité, thème, langue), PWA /
mode dégradé (service worker, cache des écrans fréquents, files de saisie hors-ligne),
dark mode natif DaisyUI. Lot transverse, sans écrans dédiés supplémentaires à migrer — les
9 JT de marge financent un audit rétroactif de cohérence sur tous les écrans livrés
jusqu'ici (L0–L5).

- **Critères d'acceptation** : le cœur de l'application fonctionne sans JS (progressive
  enhancement) ; un message explicite confirme une saisie mise en file d'attente hors
  connexion.
- **Raffinement renforcé** : cohérence du dark mode sur l'ensemble des écrans livrés
  jusqu'ici (audit rétroactif L0–L5).

Livré (commit `6916d1f`) : le rapport d'exploration a montré que **colonnes**
(`SavedTableView`, moteur SmartTable) et **langue** (`User.preferred_language`, éditable
depuis `/profile/`) existaient déjà côté données — mais la langue n'était **jamais
appliquée** (aucun `translation.activate()` nulle part) : donnée morte corrigée cette
semaine, `densité`/`thème` restaient entièrement à construire.

- **Langue** : `apps.core.middleware.UserLocaleMiddleware` (nouveau, placé APRÈS
  `LocaleMiddleware`/`AuthenticationMiddleware` dans `MIDDLEWARE`) active
  `User.preferred_language` pour tout utilisateur authentifié qui en a une — un visiteur
  anonyme retombe sur `LocaleMiddleware` seul, comportement inchangé. Vue
  `set_language_view` (`POST /i18n/setlang/`, réimplémentation volontaire plutôt que
  `django.conf.urls.i18n.set_language` — persiste sur `User.preferred_language`, pas
  seulement un cookie) + `django.template.context_processors.i18n` ajouté aux
  `TEMPLATES` (`LANGUAGES`/`LANGUAGE_CODE` n'étaient pas exposés aux templates avant).
  Sélecteur `<select>` natif + `<form method="post">` (soumission au `onchange` en
  amélioration progressive, bouton `<noscript>` de secours) ajouté au menu compte de
  `templates/base.html` (shell réellement utilisé par les 216 écrans existants) **et**
  de `templates/cotton/shell.html` (comme demandé), même patron que le sélecteur de
  société déjà existant sur `profile.html`.
- **Malagasy (mg)** : ajouté à `LANGUAGES`/`PREFERRED_LANGUAGE_CHOICES` et
  `locale/mg/LC_MESSAGES/django.po` créé — catalogue **volontairement vide**, note
  d'en-tête disclosed (même discipline que `FX_VARIANCE_ALERT_THRESHOLD_PCT`, aucun
  traducteur malgache professionnel disponible dans ce dépôt) : un utilisateur qui
  choisit « Malagasy » voit l'application en français plutôt qu'une traduction
  approximative présentée comme fiable. `compilemessages` n'est déjà, pour `fr`/`en`,
  invoqué nulle part dans le build (les `.mo` sont dans `.gitignore`, absents du dépôt) —
  aucune nouvelle étape de build inventée pour `mg`, même précédent.
- **Thème (dark mode)** : champs `User.theme` (clair/sombre/système, défaut « système »)
  et `User.density` (confortable/compacte) + migration `0027`. Second thème DaisyUI
  `widehalo-dark` ajouté dans `tailwind-input.css` (mêmes tokens `--halo-*`/`--amber-*`/
  `--slate-*` que `widehalo`, surfaces inversées — aucune nouvelle palette) ;
  `tailwind.css` reconstruit (`npm run build:css`). `<html data-theme="...">` résolu
  côté serveur par `apps.core.context_processors.account` (`resolved_theme`) : « système »
  se résout en **clair** côté serveur (page correcte sans JS) ; un petit script inline
  dans `base.html`/`tw-launchpad.html`, guardé `theme_is_system`, affine ce choix côté
  client via `prefers-color-scheme` — pure amélioration progressive, jamais la source de
  vérité. Densité appliquée via `<body class="density-...">` + quelques règles CSS
  représentatives (`table.smart-table`, `.form-field`) dans `app.css` — application
  volontairement partielle, pas une réduction exhaustive de tout espacement. Une seule
  vue `set_preference_view` (`POST /settings/preferences/`) enregistre thème et/ou
  densité, mêmes formulaires HTML purs que la langue.
- **PWA / offline** : `static/manifest.json` (nom/icône — réutilise le logo SVG existant,
  aucune icône PNG dédiée n'a été fabriquée) lié depuis `base.html`/`tw-launchpad.html`.
  Service worker minimal `static/js/sw.js`, portée **volontairement étroite et
  documentée dans son propre commentaire d'en-tête** : cache-first sur les assets
  statiques (CSS/JS/police/icône) + le shell HTML de `/dashboard/` uniquement — **pas**
  une tentative de mise hors-ligne de l'ERP dynamique dans son ensemble (tout écran
  métier non déjà visité reste, à raison, inatteignable hors connexion).
- **File d'attente hors-ligne** : `static/js/offline_queue.js`, inclus globalement
  depuis `base.html` — amélioration progressive générique (branchée sur tout
  `<form method="post">` du site, pas d'intégration écran par écran) : hors connexion
  (`navigator.onLine`), intercepte la soumission, stocke méthode/action/champs dans
  `localStorage` (tableau JSON simple, pas d'IndexedDB), affiche le message demandé
  (« Enregistré hors connexion — sera envoyé automatiquement au retour du réseau. »,
  réutilise `.wh-toast-container` s'il existe sur la page, sinon repli `alert()`), puis
  rejoue la file au retour réseau (`fetch`, échecs rapportés visiblement, jamais
  silencieusement perdus). Les formulaires avec upload de fichier sont explicitement
  exclus (non sérialisables en JSON) : ils échouent alors normalement hors-ligne, comme
  sans ce script.
- **Audit rétroactif de cohérence progressive enhancement** : shell (Alpine
  `x-data`/`x-show`, palette de commandes/dropdowns) — **sans** `<noscript>`, accepté
  comme fonctionnalité JS-only (navigation, pas le cœur CRUD) ; `profile.html`/formulaires
  comptables (X2, factures) — déjà `<form method="post">` natifs avec repli
  `<noscript>` là où une soumission auto existait ; SmartTable (listes) — filtres/tri en
  liens `<a href>` classiques, fonctionnent sans JS ; chatter — non ré-audité en détail
  cette semaine (hors échantillon représentatif retenu), signalé plutôt que passé sous
  silence.

**Résultat des 2 critères d'acceptation stipulés** :
- ✅ **Cœur applicatif sans JS** : formulaires CRUD (profil, connexion, écritures
  comptables, réception de lot...) sont déjà des `<form method="post">` natifs
  (vérifié avant ce chantier) ; les nouveaux contrôles de ce sprint (langue/thème/
  densité) suivent la même règle (sélecteur natif + repli `<noscript>`). ⚠️ Seule la
  navigation (palette de commandes, dropdowns Alpine du shell) reste JS-only — écart
  assumé, la navigation n'est pas le cœur CRUD de l'application.
- ✅ **Message explicite de mise en file hors connexion** : réellement implémenté et
  testable (`offline_queue.js`), pas un stub — cf. tests manuels de rendu de
  `wh-toast-container` dans `base.html`.

19 tests (`apps/core/tests/test_personalization.py`) : activation de langue par le
middleware (utilisateur `mg` vs visiteur anonyme vs utilisateur sans préférence
explicite), persistance via `set_language_view` (langue invalide ignorée, redirection
externe rejetée, `GET` refusé), `set_preference_view` (thème/densité, valeurs invalides
ignorées, authentification requise), rendu serveur de `data-theme`/`density-*`
(clair/sombre/système→clair). Suite complète `apps/core/tests tests/architecture` :
566 passed, 1 xfailed (préexistant), 4 failed — les 4 mêmes échecs
environnement-only déjà connus avant ce chantier (`test_health_ready_reports_db_and_redis`,
`test_raw_sql_cannot_bypass_rls`, `test_raw_sql_without_tenant_setting_sees_nothing`,
`test_cross_tenant_insert_is_rejected_by_rls`), aucune régression.

### Sprint 11 — L7 IA gateway (8 JT / 15 disponibles) — ✅ livré

`widehalo-ai-gateway` (FastAPI, Ollama local par défaut, repli Mistral), function-calling
contre des endpoints django-ninja en lecture seule, explicitement whitelistés — **pas de
text-to-SQL** (5 JT). **Décision architecturale actée avant ce sprint** (documentée dans le
code, `apps/ai/services/data_query_gateway.py`) : le microservice FastAPI séparé décrit
littéralement ci-dessus a été explicitement écarté — un microservice mono-tenant ne peut
pas porter proprement l'isolation RLS multi-tenant de ce dépôt. À la place : une boucle de
tool-calling **intégrée au process Django** (chantier GW1-GW5, déjà livré avant ce sprint) —
`core.services.data_query_tool_registry` (liste blanche de tools, chacun avec un
`required_permission` filtré par `user.has_perm()` **avant** d'offrir le catalogue au LLM,
deny-by-default testé) et `ai.models.AiRequest`/`AiDataQuery` (journalisation par appel déjà
en place). `core.services.ai_assistant.OpenAICompatibleAIProvider` parle déjà le protocole
OpenAI-compatible qu'Ollama et Mistral implémentent tous deux nativement.

- ✅ **Migration du catalogue existant du domaine** (3 JT) : les 7 écrans de l'app `ai`
  (`usage_budget`, `assist`, `search`, `anomalies_list`, `insights_list`, `recommendations`,
  `data_query`) migrés vers le design system — `<c-breadcrumb>` + `<c-button variant=
  "primary">` sur chaque écran (aucune action destructrice/de blocage dans ce module, donc
  aucun `variant="danger"` requis), même traitement que les Sprints 5/7/9.
- **Critère d'acceptation** : ✅ les tools n'exposent que les données du tenant courant (RLS,
  hérité du reste du dépôt) ; ✅ chaque appel journalisé (`AiRequest`/`AiDataQuery`,
  déjà en place avant ce sprint) ; ⚠️ **« aucun droit DDL/écriture côté rôle DB de l'IA »
  non satisfait au niveau du rôle DB lui-même** — l'isolation aujourd'hui est uniquement
  applicative (liste blanche + RBAC par tool, `user.has_perm()` avant même d'offrir un tool
  au LLM). Le process qui exécute ces tools tourne sous le même rôle Postgres
  (`widehalo_app`) que le reste de l'application ; il n'existe pas de rôle Postgres dédié,
  moindre privilège, réservé au chemin IA. Provisionner un tel rôle (`CREATE ROLE` + `GRANT
  SELECT` seul, appliqué au déploiement) est un travail d'infra/ops hors périmètre d'une
  session sans accès à un cluster de production — écart assumé, documenté dans le code
  (docstring de `core.services.data_query_tool_registry`), même discipline que le FEFO
  « suggéré non appliqué automatiquement » des Sprints 6-7.
- ✅ **Raffinement renforcé** : présentation des réponses/actions IA dans l'UI —
  `templates/ai/data_query.html` affiche désormais un bloc « Sources consultées »
  listant, avec leur libellé lisible du registre (pas seulement le `code` technique), les
  tools réellement invoqués par le LLM pour composer sa réponse (`tools_called` enrichi
  côté vue via `data_query_tool_registry.get_data_query_tool()`), jamais une boîte noire.
- **Repli Mistral** : ajouté comme exemple de configuration documenté dans
  `AI_PROVIDER_CONFIG` (`config/settings/base.py`) — l'API Mistral est compatible
  OpenAI chat-completions, donc couverte par le connecteur `OpenAICompatibleAIProvider`
  existant sans nouveau code, en complément (pas en remplacement) de l'exemple
  DeepSeek/Kimi déjà présent.

## 5 bis. Sprints 12–14 — L9 Rattrapage du catalogue existant (39 JT / 45 disponibles)

**Origine** : décision utilisateur du 2026-09-02 — la migration « strangler pattern »
couvre l'intégralité des 218 écrans existants en Phase 1, pas seulement les 9 écrans
critiques nommés par le cahier des charges. Les apps déjà rattachées à un lot métier
(catalog/mrp/purchase → L3, stocks/logistics → L4, accounting/payroll → L5, ai → L7) sont
migrées dans ce lot-là (§5) ; L9 couvre le **reste** du catalogue, soit 129 écrans sur 16
apps + le résidu de la racine, regroupés en 8 batches de ~5 JT chacun (méthode de
chiffrage : ~0,3 JT/écran, re-habillage et non reconstruction — voir détail ci-dessous),
répartis sur 3 semaines à 15 JT :

| Sprint | Batches (apps couvertes, écrans, JT) | Total semaine |
|---|---|---|
| 12 | `projects` (23 écrans, 5 JT) · `helpdesk`+`chat` (14 écrans, 5 JT) · `crm`+`sales` (17 écrans, 5 JT) | 15 JT |
| 13 | `partners`+`patronage` (15 écrans, 5 JT) · `quality`+`financing`+`risk` (15 écrans, 5 JT) · `feasibility`+`automation`+`presence` (15 écrans, 5 JT) | 15 JT |
| 14 | `strategy`+`reporting`+`reports` (12 écrans, 4 JT) · résidu racine (~18 écrans, 5 JT) | 9 JT (6 JT de marge) |

- **Critères d'acceptation (par batch)** : chaque écran migré passe les mêmes critères
  qu'un écran neuf (A.5/A.10 du cahier des charges — action primaire évidente, empty
  states, tablette/responsive, WCAG AA) ; le chemin legacy correspondant est supprimé
  (pas de « deux systèmes pour toujours », B.8) ; le test CI de budget d'architecture
  (`tests/architecture/test_budget.py`) reste vert.
- **Raffinement renforcé (chaque semaine)** : audit de cohérence transverse — un écran
  migré isolément qui « détonne » visuellement à côté d'écrans encore legacy est un signal
  à corriger avant de passer au batch suivant, pas à la fin.
- **Risque assumé** : ce chiffrage (0,3 JT/écran) est une hypothèse de planning, pas une
  mesure — à recalibrer après le premier batch (Sprint 12, `projects`) si l'écart avec le
  réel dépasse ~20 %, en réajustant les batches suivants en conséquence. La marge de 6 JT
  du Sprint 14 sert de premier amortisseur si le recalibrage l'exige.

## 6. Sprint 15 — Raffinement global & recette UX (5 JT / 15 disponibles)

Sprint de clôture de la Phase 1, dédié entièrement à la demande d'insistance UX/UI. Les
10 JT de marge sur la capacité de 15 sont volontairement réservés à cette recette plutôt
que comprimés — c'est le sprint où le raffinement UX est la seule priorité :

- Audit visuel transverse : cohérence des tokens et composants sur les 218+ écrans
  livrés (L0 à L9).
- Passage accessibilité complet : navigation clavier de bout en bout, ARIA sur les
  composants custom, contrastes WCAG AA (point d'attention DaisyUI/Flowbite qui ne
  garantissent pas toute la couche ARIA).
- Mesure SUS finale (cible ≥ 80, seuil minimal acceptable 68) comparée à la baseline
  mesurée avant refonte ; temps par tâche (réduction ≥ 30 % sur les 5 tâches critiques :
  créer devis, saisir réception lot, créer OF, saisir écriture, préparer expédition FEFO) ;
  SEQ (cible ≥ 6,0).
- Confirmation qu'**aucun** chemin legacy ne subsiste (étape d'élimination obligatoire du
  strangler pattern appliquée à chaque sprint L3–L9, vérifiée ici une dernière fois).
- Tests de non-régression visuelle (snapshot) sur l'ensemble du périmètre livré.

## 7. Synthèse

| | |
|---|---|
| Durée totale | **16 sprints (Sprint 0 à 15) ≈ 16 semaines (~3,7 mois)** à 15 JT/semaine |
| Budget Jour-Token | **152 JT** (identique à la révision précédente — seule la vitesse hebdomadaire a changé) |
| Répartition | 5 (S0) + 8 (L0) + 10 (L1) + 8 (L2) + 28 (L3) + 19 (L4) + 16 (L5) + 6 (L6) + 8 (L7) + 39 (L9) + 5 (recette) = 152 |
| Périmètre | Phase 1 Madagascar, **intégralité des 218 écrans existants + écrans critiques neufs** (L0–L7 + L9, Must + Should) |
| Hors périmètre | L8 — activation SYSCOHADA / roadmap OHADA (Côte d'Ivoire en priorité), Phase 2 ; écrans qui seraient créés après la clôture de ce planning (nouveaux modules) |

### Historique des révisions

| Version | Vitesse | Durée | Budget |
|---|---|---|---|
| v1 (initiale) | 5 JT/semaine | 19 semaines | 81 JT (périmètre : écrans critiques uniquement) |
| v2 (après Sprint 0, périmètre élargi) | 5 JT/semaine | 34 semaines | 152 JT (périmètre : 218 écrans + critiques) |
| **v3 (actuelle, vitesse révisée)** | **15 JT/semaine** | **16 semaines** | **152 JT (périmètre inchangé)** |

### Risques du dossier applicables à ce planning (B.14)

| Risque | Mitigation dans ce planning |
|---|---|
| Dérive du budget d'architecture | Test CI de comptage (modèles/endpoints/écrans), déjà en place, ajusté au Sprint 0 |
| Migration écran par écran qui ne finit jamais | Périmètre complet acté (§5 bis) + étape d'élimination du legacy obligatoire **à chaque sprint** L3–L9, pas seulement en clôture |
| Chiffrage L9 optimiste (0,3 JT/écran) | Recalibrage explicite prévu après le Sprint 12 (premier batch) |
| Vitesse 15 JT/semaine trop optimiste | Marge structurelle : capacité nominale (15 JT × 16 semaines = 240 JT) largement supérieure au travail chiffré (152 JT) — ~37 % de marge absorbable avant tout retard sur la date de clôture |
| Accessibilité incomplète (DaisyUI/Flowbite) | Jour de raffinement dédié dans **chaque** sprint (désormais 3 JT/semaine, contre 1 JT à l'ancienne vitesse) |
| Confusion PCG 2005 / SYSCOHADA | Framework comptable par tenant/pays, PCG 2005 par défaut à Madagascar, garde-fou de validation (Sprints 8–9) |
| Paramètres réglementaires en dur ou périmés | Table versionnée + revue annuelle (Sprints 8–9) |
| Dépôt non audité au départ | Inventaire automatique préalable (Sprint 0, réalisé) |
