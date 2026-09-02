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

### Sprint 1 — L0 Fondations (8 JT / 15 disponibles)
Design system Tailwind/DaisyUI finalisé, shell applicatif (logo + app switcher type
Odoo/Fiori), launchpad par rôle (tuiles statiques + dynamiques + KPI), breadcrumb,
recherche globale (command palette Ctrl/Cmd+K — entités + actions + navigation),
notifications (cloche, compteur live), menu utilisateur (langue FR/MG/EN, dark mode). Ce
lot migre aussi les 18 écrans racine existants (dashboard, recherche, paramètres) qui
occupent précisément le shell reconstruit ici. Les 7 JT de marge sur la capacité de 15
sont absorbés par un raffinement UX approfondi plutôt que par de nouvelles fonctionnalités.

- **Critères d'acceptation** : chaque utilisateur voit un launchpad filtré par son rôle
  métier ; la recherche globale répond en < 100 ms perçu (indicateurs HTMX/skeletons) ;
  tous les écrans sont composés exclusivement à partir de la bibliothèque de composants.
- **Raffinement renforcé** : cohérence des tokens sur l'ensemble du shell, contraste
  WCAG AA sur la palette de marque, focus clavier visible sur l'app switcher et la command
  palette.

### Sprint 2 — L1 Data grid & vues (10 JT / 15 disponibles)
Moteur de vues configurables en base (`ui_view_definition`, arch JSON façon Odoo), data
grid universel (colonnes configurables, tri, pagination serveur HTMX, sélection multiple,
actions de masse, colonnes gelées), vues list/kanban, filtres et groupements sauvegardables
(`ui_saved_filter`), quick create. Moteur transverse réutilisé par tous les lots suivants
(y compris L9) — c'est lui qui rend la migration en masse du catalogue existant réaliste
en JT.

- **Critères d'acceptation** : pagination serveur systématique (jamais tout charger) ;
  changement de vue (list ↔ kanban) sans perte de filtres actifs.
- **Raffinement renforcé** : densité configurable (compacte pour atelier/entrepôt, confort
  en saisie), skeletons de chargement, empty states pédagogiques par écran de liste.

### Sprint 3 — L2 Formulaires & chatter (8 JT / 15 disponibles)
Formulaires longs par onglets avec validation inline (HTMX par champ), sauvegarde de
brouillon, chatter (messages/notes internes/activités planifiées/abonnés,
`mail_message`/`mail_activity`/`mail_follower`), notifications contextuelles avec actions.

- **Critères d'acceptation** : une saisie interrompue par une coupure réseau reste
  enregistrée localement (« sera envoyée au retour du réseau ») ; le chatter est disponible
  sur tous les objets clés du périmètre Phase 1.
- **Raffinement renforcé** : messages d'erreur de validation clairs et positionnés au bon
  endroit, panneau chatter latéral cohérent sur toutes les object pages.

### Sprints 4–5 — L3 Textile (28 JT / 30 disponibles)
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
  (Sprint 4 : T1–T3, 12 JT.)
- **Migration du catalogue existant du domaine** (Sprint 5, 16 JT) : les 45 écrans déjà
  livrés dans `catalog` (16), `mrp` (12) et `purchase` (17) passent au nouveau design
  system, écran par écran, en réutilisant les composants L0/L1/L2 — pas de reconstruction
  fonctionnelle, uniquement re-habillage + accessibilité + responsive.
- **Raffinement renforcé (les deux sprints)** : ergonomie de la grille éditable
  tailles×couleurs (saisie clavier rapide), lisibilité du kanban atelier sur tablette en
  conditions de réseau faible.

### Sprints 6–7 — L4 Agro (19 JT / 30 disponibles)
- **Écran A1** — Réception + lots + DLC/DLUO (liaison certificat/COA, tablette + scan).
  *Critère* : tout mouvement porte un n° de lot ; FEFO appliqué automatiquement.
- **Écran A2** — Ordre de transformation + recette (BOM process) + rendement (généalogie de
  lot, traçabilité amont/aval).
  *Critère* : rendement réel vs théorique affiché.
- **Écran A3** — Contrôle qualité HACCP + non-conformité + rappel produit.
  *Critère* : un lot suspect permet de lister en < 5 s tous les lots finis et clients
  impactés (traçabilité « one-up/one-back ») ; journal horodaté (incident, timestamp,
  initiateur, périmètre).
  (Sprint 6 : A1–A3, 12 JT.)
- **Migration du catalogue existant du domaine** (Sprint 7, 7 JT sur 15 disponibles) :
  `stocks` (3 écrans — déjà consolidés en pages multi-onglets, cf.
  `apps/stocks/views.py`) et `logistics` (17 écrans, entrepôt/expédition) migrés vers le
  nouveau design system. Marge confortable (8 JT) réinvestie en raffinement.
- **Raffinement renforcé (les deux sprints)** : clarté visuelle des statuts hold/release,
  parcours de traçabilité lisible en situation d'urgence (rappel produit).

### Sprints 8–9 — L5 Compta/Paie Madagascar (16 JT / 30 disponibles)
Abstraction du référentiel comptable (`core_accounting_framework`, `core_chart_of_accounts`,
`core_account`, `core_account_mapping` : PCG 2005 première classe, SYSCOHADA activable par
tenant/pays), paramètres réglementaires versionnés (`core_regulatory_parameter` : IRSA,
CNaPS, OSTIE, FMFP, TVA, SME — jamais en dur), saisie comptable rapide (X2), bulletin de
paie (X3). (Sprint 8 : X2–X3, 10 JT.)

- **Migration du catalogue existant du domaine** (Sprint 9, 6 JT sur 15 disponibles) :
  `accounting` (15 écrans) et `payroll` (2 écrans) migrés vers le nouveau design system.
- **Critères d'acceptation** : aucun barème réglementaire en dur (lu depuis la table
  versionnée à la date d'effet) ; validation des paramètres par un expert-comptable membre
  de l'OECFM avant mise en production ; plafond social (8×SME) calculé dynamiquement.
- **Raffinement renforcé (les deux sprints)** : saisie comptable rapide avec contreparties
  suggérées, lisibilité des écarts PCG 2005 vs SYSCOHADA pour éviter toute confusion.

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

### Sprint 11 — L7 IA gateway (8 JT / 15 disponibles)
`widehalo-ai-gateway` (FastAPI, Ollama local par défaut, repli Mistral), function-calling
contre des endpoints django-ninja en lecture seule, explicitement whitelistés — **pas de
text-to-SQL** (5 JT).

- **Migration du catalogue existant du domaine** (3 JT) : les 7 écrans de l'app `ai`
  migrés vers le nouveau design system.
- **Critère d'acceptation** : les tools n'exposent que les données du tenant courant (RLS),
  aucun droit DDL/écriture côté rôle DB de l'IA, chaque appel journalisé.
- **Raffinement renforcé** : présentation des réponses/actions IA dans l'UI (feedback clair
  sur ce que l'IA a fait, jamais une boîte de dialogue opaque).

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
