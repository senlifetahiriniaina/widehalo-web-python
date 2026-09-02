# WideHalo v3 — Planning sprints hebdomadaires (Jour-Token) — Refonte UX

Source : *WideHalo v3 — Cahier des charges (refonte UX) & Dossier d'Architecture Technique
(DAT)*, dossier fourni par le donneur d'ordre. Ce document traduit ce cahier des charges en
sprints hebdomadaires chiffrés en Jour-Token, avec une insistance délibérée sur l'UX/UI et
le raffinement de la présentation à chaque étape — pas seulement en fin de projet.

> **Révision post-Sprint 0.** Le Sprint 0 (inventaire réel du dépôt, voir
> `docs/planning/ECART_ARCHITECTURE.md`) a mesuré **218 écrans déjà livrés** sur 22 apps
> (Lot 1 + Lot 2 Madagascar), bien au-delà des ~90-110 écrans supposés par le cahier des
> charges (qui ne nommait que 9 écrans critiques + fondations). **Décision actée avec
> l'utilisateur** : la migration « strangler pattern » couvre l'intégralité de ces écrans
> en Phase 1, sans exception — aucun écran ne doit rester indéfiniment sur l'ancien design
> system. Le budget et le planning ci-dessous sont donc **révisés à la hausse** (152 JT /
> 34 sprints, au lieu des 81 JT / 19 sprints de la première version) ; §5 bis détaille le
> nouveau lot **L9 — Rattrapage du catalogue existant**.

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
périmètre** de ce planning (backlog "Could", Phase 2).

## 2. Cadence retenue

- **1 sprint = 1 semaine = 5 Jour-Token**, capacité d'un développeur solo à temps plein
  assisté par Claude Code.
- **Gabarit fixe appliqué à chaque sprint**, pour que l'UX/UI et le raffinement de la
  présentation ne soient jamais relégués à la fin :

  | Jour | Contenu |
  |---|---|
  | J1–J3 | Construction : composants/écrans du lot (specs A.8 bibliothèque de composants, A.9 écrans par verticale) |
  | J4 | Intégration + vérification des critères d'acceptation du lot (cahier des charges) |
  | **J5** | **Jour de raffinement UX** : micro-interactions, accessibilité (contraste WCAG AA, navigation clavier, ARIA), densité (confortable/compacte), dark mode, responsive/tablette (cibles tactiles ≥ 44 px), empty states / états d'erreur / de chargement, cohérence stricte avec la bibliothèque de composants et les design tokens. Mesure quand applicable (SUS, SEQ, temps par tâche, nombre de clics — A.14). |

- **Budget total révisé : 152 JT sur 34 sprints (Sprint 0 à 33, ≈ 34 semaines, ~7,8 mois)** :
  5 JT (Sprint 0, réalisé) + 142 JT (L0–L7 + L9, construction/migration) + 5 JT (recette
  finale, Sprint 33). Le détail par lot est en §5 et §5 bis ; la méthode de chiffrage de
  L9 (paye de la migration complète du catalogue existant) est explicitée en §5 bis.

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

- **J1–J2** : inventaire automatique du dépôt par introspection Django (réutilise les
  compteurs de `tests/architecture/test_budget.py`, déjà existant). Produit
  `docs/planning/ECART_ARCHITECTURE.md` confrontant le réel (254 modèles / 515 endpoints /
  218 écrans) aux budgets déclarés (180/600/90 dossier, 200/650/110 recommandation
  dossier, 290/600/240 plafonds CI réels déjà en place). Constat clé : le garde-fou CI
  anti-dérive demandé par le dossier (B.9) **existait déjà** ; le dépôt est bien plus
  avancé que supposé (Lot 2 Madagascar largement livré) — `README.md` corrigé en
  conséquence.
- **J3** : mise en place Tailwind + DaisyUI + django-cotton en coexistence avec le système
  existant (build sans preflight — voir §3).
- **J4** : portage des tokens `tokens.css` vers le thème Tailwind/DaisyUI.
- **J5 (raffinement)** : vérification visuelle du socle porté (aucune régression sur les
  écrans existants), ajustement du test CI de budget d'architecture existant pour exclure
  `templates/cotton/` du comptage des écrans (bibliothèque de composants, pas des écrans).

**Critère d'acceptation** : ✅ le socle Tailwind/DaisyUI/django-cotton compile et coexiste
avec l'UI legacy sans régression visuelle ; le fichier d'écart est produit et devient le
point de vérité qui remplace les hypothèses du cahier des charges (y compris sur le
périmètre de migration, tranché en §5 bis ci-dessous).

## 5. Sprints par lot (construction des écrans critiques du cahier des charges)

### Sprints 1–2 — L0 Fondations (8 JT)
Design system Tailwind/DaisyUI finalisé, shell applicatif (logo + app switcher type
Odoo/Fiori), launchpad par rôle (tuiles statiques + dynamiques + KPI), breadcrumb,
recherche globale (command palette Ctrl/Cmd+K — entités + actions + navigation),
notifications (cloche, compteur live), menu utilisateur (langue FR/MG/EN, dark mode). Ce
lot migre aussi les écrans racine existants (dashboard, recherche, paramètres — 18
templates à la racine de `templates/`) puisqu'il s'agit précisément du shell qu'ils
occupent déjà.

- **Critères d'acceptation** : chaque utilisateur voit un launchpad filtré par son rôle
  métier ; la recherche globale répond en < 100 ms perçu (indicateurs HTMX/skeletons) ;
  tous les écrans sont composés exclusivement à partir de la bibliothèque de composants.
- **Jour de raffinement dédié** : cohérence des tokens sur l'ensemble du shell, contraste
  WCAG AA sur la palette de marque, focus clavier visible sur l'app switcher et la command
  palette.

### Sprints 3–4 — L1 Data grid & vues (10 JT)
Moteur de vues configurables en base (`ui_view_definition`, arch JSON façon Odoo), data
grid universel (colonnes configurables, tri, pagination serveur HTMX, sélection multiple,
actions de masse, colonnes gelées), vues list/kanban, filtres et groupements sauvegardables
(`ui_saved_filter`), quick create. Moteur transverse réutilisé par tous les lots suivants
(y compris L9) — c'est lui qui rend la migration en masse du catalogue existant réaliste
en JT.

- **Critères d'acceptation** : pagination serveur systématique (jamais tout charger) ;
  changement de vue (list ↔ kanban) sans perte de filtres actifs.
- **Jour de raffinement dédié** : densité configurable (compacte pour atelier/entrepôt,
  confort en saisie), skeletons de chargement, empty states pédagogiques par écran de liste.

### Sprints 5–6 — L2 Formulaires & chatter (8 JT)
Formulaires longs par onglets avec validation inline (HTMX par champ), sauvegarde de
brouillon, chatter (messages/notes internes/activités planifiées/abonnés,
`mail_message`/`mail_activity`/`mail_follower`), notifications contextuelles avec actions.

- **Critères d'acceptation** : une saisie interrompue par une coupure réseau reste
  enregistrée localement (« sera envoyée au retour du réseau ») ; le chatter est disponible
  sur tous les objets clés du périmètre Phase 1.
- **Jour de raffinement dédié** : messages d'erreur de validation clairs et positionnés au
  bon endroit, panneau chatter latéral cohérent sur toutes les object pages.

### Sprints 7–12 — L3 Textile (28 JT : 12 JT écrans critiques + 16 JT migration)
- **Écran T1** — Fiche style avec matrice tailles×couleurs (grille éditable, génération
  automatique des variantes SKU, BOM par variante, codes-barres EAN/GTIN).
  *Critère* : créer un style 8 tailles × 6 couleurs génère 48 SKU en < 2 s.
- **Écran T2** — Ordre de fabrication + suivi atelier (kanban coupe→couture→finition),
  sous-traitance façon (CMT), First Pass Yield.
  *Critère* : déplacer une carte change l'état et journalise dans le chatter ; tablette,
  cibles ≥ 44 px, fonctionne sur réseau faible.
- **Écran T3** — Dossier d'import + CREDOC + landed cost (flux banque émettrice → banque
  notificatrice → bénéficiaire, coût de revient débarqué par SKU).
  *Critère* : statuts CREDOC conformes au flux ; alerte sur écart de change Ariary.
- **Migration du catalogue existant du domaine** (+16 JT, sprints 9–12) : les 45 écrans déjà
  livrés dans `catalog` (16), `mrp` (12) et `purchase` (17) passent au nouveau design
  system, écran par écran, en réutilisant les composants L0/L1/L2 — pas de reconstruction
  fonctionnelle, uniquement re-habillage + accessibilité + responsive.
- **Jour de raffinement dédié (par sprint)** : ergonomie de la grille éditable
  tailles×couleurs (saisie clavier rapide), lisibilité du kanban atelier sur tablette en
  conditions de réseau faible.

### Sprints 13–16 — L4 Agro (19 JT : 12 JT écrans critiques + 7 JT migration)
- **Écran A1** — Réception + lots + DLC/DLUO (liaison certificat/COA, tablette + scan).
  *Critère* : tout mouvement porte un n° de lot ; FEFO appliqué automatiquement.
- **Écran A2** — Ordre de transformation + recette (BOM process) + rendement (généalogie de
  lot, traçabilité amont/aval).
  *Critère* : rendement réel vs théorique affiché.
- **Écran A3** — Contrôle qualité HACCP + non-conformité + rappel produit.
  *Critère* : un lot suspect permet de lister en < 5 s tous les lots finis et clients
  impactés (traçabilité « one-up/one-back ») ; journal horodaté (incident, timestamp,
  initiateur, périmètre).
- **Migration du catalogue existant du domaine** (+7 JT, sprint 16) : `stocks` (3 écrans —
  déjà consolidés en pages multi-onglets, cf. `apps/stocks/views.py`) et `logistics` (17
  écrans, entrepôt/expédition) migrés vers le nouveau design system.
- **Jour de raffinement dédié (par sprint)** : clarté visuelle des statuts hold/release,
  parcours de traçabilité lisible en situation d'urgence (rappel produit).

### Sprints 17–20 — L5 Compta/Paie Madagascar (16 JT : 10 JT écrans critiques + 6 JT migration)
Abstraction du référentiel comptable (`core_accounting_framework`, `core_chart_of_accounts`,
`core_account`, `core_account_mapping` : PCG 2005 première classe, SYSCOHADA activable par
tenant/pays), paramètres réglementaires versionnés (`core_regulatory_parameter` : IRSA,
CNaPS, OSTIE, FMFP, TVA, SME — jamais en dur), saisie comptable rapide (X2), bulletin de
paie (X3).

- **Migration du catalogue existant du domaine** (+6 JT, sprint 20) : `accounting` (15
  écrans) et `payroll` (2 écrans) migrés vers le nouveau design system.
- **Critères d'acceptation** : aucun barème réglementaire en dur (lu depuis la table
  versionnée à la date d'effet) ; validation des paramètres par un expert-comptable membre
  de l'OECFM avant mise en production ; plafond social (8×SME) calculé dynamiquement.
- **Jour de raffinement dédié** : saisie comptable rapide avec contreparties suggérées,
  lisibilité des écarts PCG 2005 vs SYSCOHADA pour éviter toute confusion.

### Sprints 21–22 — L6 Personnalisation & offline (6 JT)
Personnalisation utilisateur (`user_preference` : colonnes, densité, thème, langue), PWA /
mode dégradé (service worker, cache des écrans fréquents, files de saisie hors-ligne),
dark mode natif DaisyUI. Lot transverse, sans écrans dédiés supplémentaires à migrer.

- **Critères d'acceptation** : le cœur de l'application fonctionne sans JS (progressive
  enhancement) ; un message explicite confirme une saisie mise en file d'attente hors
  connexion.
- **Jour de raffinement dédié** : cohérence du dark mode sur l'ensemble des écrans livrés
  jusqu'ici (audit rétroactif L0–L5).

### Sprints 23–24 — L7 IA gateway (8 JT : 5 JT gateway + 3 JT migration)
`widehalo-ai-gateway` (FastAPI, Ollama local par défaut, repli Mistral), function-calling
contre des endpoints django-ninja en lecture seule, explicitement whitelistés — **pas de
text-to-SQL**.

- **Migration du catalogue existant du domaine** (+3 JT) : les 7 écrans de l'app `ai`
  migrés vers le nouveau design system.
- **Critère d'acceptation** : les tools n'exposent que les données du tenant courant (RLS),
  aucun droit DDL/écriture côté rôle DB de l'IA, chaque appel journalisé.
- **Jour de raffinement dédié** : présentation des réponses/actions IA dans l'UI (feedback
  clair sur ce que l'IA a fait, jamais une boîte de dialogue opaque).

## 5 bis. Sprints 25–32 — L9 Rattrapage du catalogue existant (39 JT, nouveau lot)

**Origine** : décision utilisateur du 2026-09-02 (voir note en tête de document) — la
migration « strangler pattern » couvre l'intégralité des 218 écrans existants en Phase 1,
pas seulement les 9 écrans critiques nommés par le cahier des charges. Les apps déjà
rattachées à un lot métier (catalog/mrp/purchase → L3, stocks/logistics → L4,
accounting/payroll → L5, ai → L7) sont migrées dans ce lot-là (§5) ; L9 couvre le **reste**
du catalogue, soit 129 écrans sur 16 apps + le résidu de la racine.

**Méthode de chiffrage** : migration ≠ construction. Le backend/la logique métier existent
déjà pour ces 129 écrans ; le travail est un re-habillage (composants L0/L1/L2 déjà prêts à
ce stade du planning) + passage accessibilité/responsive + suppression du chemin legacy —
budgété à ~0,3 JT/écran en moyenne (vs ~1,2 JT/écran pour la construction neuve des lots
L3–L5), cohérent avec le gain de productivité IA du dossier (A.13) une fois les composants
communs en place. 129 × 0,3 ≈ 39 JT.

| Sprint | Apps couvertes | Écrans | JT |
|---|---|---|---|
| 25 | `projects` (gestion de projets — plus gros volume à app unique) | 23 | 5 |
| 26 | `helpdesk`, `chat` | 14 | 5 |
| 27 | `crm`, `sales` | 17 | 5 |
| 28 | `partners`, `patronage` | 15 | 5 |
| 29 | `quality`, `financing`, `risk` | 15 | 5 |
| 30 | `feasibility`, `automation`, `presence` | 15 | 5 |
| 31 | `strategy`, `reporting`, `reports` | 12 | 4 |
| 32 | Résidu racine (`templates/*.html` hors shell L0) + rattrapage | ~18 | 5 |

- **Critères d'acceptation (par sprint)** : chaque écran migré passe les mêmes critères
  qu'un écran neuf (A.5/A.10 du cahier des charges — action primaire évidente, empty
  states, tablette/responsive, WCAG AA) ; le chemin legacy correspondant est supprimé
  (pas de « deux systèmes pour toujours », B.8) ; le test CI de budget d'architecture
  (`tests/architecture/test_budget.py`) reste vert.
- **Jour de raffinement dédié (par sprint)** : audit de cohérence transverse — un écran
  migré isolément qui « détonne » visuellement à côté d'écrans encore legacy est un signal
  à corriger avant de passer au batch suivant, pas à la fin.
- **Risque assumé** : ce chiffrage (0,3 JT/écran) est une hypothèse de planning, pas une
  mesure — à recalibrer après le premier batch (Sprint 25, `projects`) si l'écart avec le
  réel dépasse ~20 %, en réajustant les sprints 26–32 en conséquence.

## 6. Sprint 33 — Raffinement global & recette UX (5 JT)

Sprint de clôture de la Phase 1, dédié entièrement à la demande d'insistance UX/UI :

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
| Durée totale | **34 sprints (Sprint 0 à 33) ≈ 34 semaines (~7,8 mois)** |
| Budget Jour-Token | **152 JT** (5 Sprint 0 + 8 L0 + 10 L1 + 8 L2 + 28 L3 + 19 L4 + 16 L5 + 6 L6 + 8 L7 + 39 L9 + 5 recette) |
| Périmètre | Phase 1 Madagascar, **intégralité des 218 écrans existants + écrans critiques neufs** (L0–L7 + L9, Must + Should) |
| Hors périmètre | L8 — activation SYSCOHADA / roadmap OHADA (Côte d'Ivoire en priorité), Phase 2 ; écrans qui seraient créés après la clôture de ce planning (nouveaux modules) |

### Risques du dossier applicables à ce planning (B.14)

| Risque | Mitigation dans ce planning |
|---|---|
| Dérive du budget d'architecture | Test CI de comptage (modèles/endpoints/écrans), déjà en place, ajusté au Sprint 0 |
| Migration écran par écran qui ne finit jamais | Périmètre complet acté (§5 bis) + étape d'élimination du legacy obligatoire **à chaque sprint** L3–L9, pas seulement en clôture |
| Chiffrage L9 optimiste (0,3 JT/écran) | Recalibrage explicite prévu après le Sprint 25 (premier batch) |
| Accessibilité incomplète (DaisyUI/Flowbite) | Jour de raffinement (J5) dédié à un budget accessibilité manuel dans **chaque** sprint, pas seulement en fin de projet |
| Confusion PCG 2005 / SYSCOHADA | Framework comptable par tenant/pays, PCG 2005 par défaut à Madagascar, garde-fou de validation (Sprints 17–20) |
| Paramètres réglementaires en dur ou périmés | Table versionnée + revue annuelle (Sprints 17–20) |
| Dépôt non audité au départ | Inventaire automatique préalable (Sprint 0, réalisé) |
