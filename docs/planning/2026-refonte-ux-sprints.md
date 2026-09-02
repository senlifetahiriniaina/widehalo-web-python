# WideHalo v3 — Planning sprints hebdomadaires (Jour-Token) — Refonte UX

Source : *WideHalo v3 — Cahier des charges (refonte UX) & Dossier d'Architecture Technique
(DAT)*, dossier fourni par le donneur d'ordre. Ce document traduit ce cahier des charges en
sprints hebdomadaires chiffrés en Jour-Token, avec une insistance délibérée sur l'UX/UI et
le raffinement de la présentation à chaque étape — pas seulement en fin de projet.

## 1. Rappel du chiffrage source

Le dossier chiffre l'effort en Jour-Homme (J/H) **et** en Jour-Token (JT — journée de
travail assistée par Claude Code, génération/refactor de composants et écrans à partir de
specs, estimée ~2,5× plus productive que le J/H pur sur du CRUD et des composants
répétitifs, avec un gain moindre sur les moteurs transverses et la logique réglementaire) :

| Lot | Contenu | J/H | JT | Priorité |
|---|---|---|---|---|
| L0 | Fondations (design system, tokens, shell/launchpad, breadcrumb, recherche globale) | 20 | 8 | Must |
| L1 | Data grid & vues (moteur de vues/metadata, list/kanban, filtres sauvegardés) | 25 | 10 | Must |
| L2 | Formulaires & chatter (validation inline, chatter, activités, notifications) | 20 | 8 | Must |
| L3 | Textile (matrice tailles×couleurs, OF/atelier, import/CREDOC/landed cost) | 30 | 12 | Must |
| L4 | Agro (lots/DLC/FEFO, transformation/rendement, HACCP/rappel) | 30 | 12 | Must |
| L5 | Compta/Paie MG (abstraction PCG 2005/SYSCOHADA, TVA/IRSA/CNaPS/OSTIE/FMFP) | 25 | 10 | Must |
| L6 | Personnalisation & offline (préférences, PWA/mode dégradé, dark mode) | 15 | 6 | Should |
| L7 | IA gateway (widehalo-ai-gateway, function-calling lecture seule) | 10 | 5 | Should |
| **Total Phase 1 (L0–L7)** | | **~175** | **~71** | |

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

- Budget total planifié : **76 JT** de construction (71 JT dossier + 5 JT Sprint 0
  d'inventaire/bascule stack, non comptés dans le chiffrage initial) **+ 5 JT** de
  raffinement global et recette en clôture = **81 JT sur 19 sprints (~19 semaines)**.

## 3. Écart de stack identifié et décision

Le dossier préconise **Tailwind + DaisyUI + django-cotton + HTMX/Alpine** comme socle de
présentation. Le dépôt `widehalo-web-python` a déjà un design system maison mature
(`widehalo/static/css/tokens.css`, `app.css` ~977 lignes, composants Django templates +
HTMX + Alpine, admin django-unfold), sans Tailwind ni django-cotton.

**Décision actée** : migrer vers le socle préconisé par le dossier (Tailwind + DaisyUI +
django-cotton), en portant les tokens de couleurs/espacements existants
(`--halo-*`, `--amber-*`, `--slate-*`) dans la configuration Tailwind, pour ne pas perdre
l'identité visuelle déjà posée. Cette migration est prise en charge par le Sprint 0.

## 4. Sprint 0 — Inventaire, écart, socle technique (5 JT)

*Hors budget des 71 JT du dossier — préalable requis avant de lancer les lots.*

Reprend l'« Action requise de Claude Code en préambule » du cahier des charges :

- **J1–J2** : inventaire automatique du dépôt — compter les modèles (`grep`/introspection
  Django), lister les routers/endpoints django-ninja, recenser les templates/écrans,
  extraire les workflows d'états (django-fsm-2). Produire `docs/planning/ECART_ARCHITECTURE.md`
  confrontant le réel aux budgets déclarés (180 modèles / 600 endpoints / 90 écrans du
  dossier B.9) et à la recommandation d'ajustement (200 / 650 / 110).
- **J3** : mise en place Tailwind + DaisyUI + django-cotton en coexistence avec le système
  existant (strangler pattern, feature flag par écran/rôle — B.8 du dossier).
- **J4** : portage des tokens `tokens.css` vers `tailwind.config` (couleurs, espacements
  base 4 px, rayons, ombres, durées d'animation).
- **J5 (raffinement)** : vérification visuelle du socle porté (aucune régression sur les
  écrans existants), mise en place du test CI de budget d'architecture (garde-fou anti-
  dérive, B.9).

**Critère d'acceptation** : le socle Tailwind/DaisyUI/django-cotton compile et coexiste
avec l'UI legacy sans régression visuelle ; le fichier d'écart est produit et devient le
point de vérité qui remplace les hypothèses du cahier des charges.

## 5. Sprints par lot

### Sprints 1–2 — L0 Fondations (8 JT)
Design system Tailwind/DaisyUI finalisé, shell applicatif (logo + app switcher type
Odoo/Fiori), launchpad par rôle (tuiles statiques + dynamiques + KPI), breadcrumb,
recherche globale (command palette Ctrl/Cmd+K — entités + actions + navigation),
notifications (cloche, compteur live), menu utilisateur (langue FR/MG/EN, dark mode).

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
(`ui_saved_filter`), quick create.

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

### Sprints 7–9 — L3 Textile (12 JT)
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
- **Jour de raffinement dédié (par sprint)** : ergonomie de la grille éditable
  tailles×couleurs (saisie clavier rapide), lisibilité du kanban atelier sur tablette en
  conditions de réseau faible.

### Sprints 10–12 — L4 Agro (12 JT)
- **Écran A1** — Réception + lots + DLC/DLUO (liaison certificat/COA, tablette + scan).
  *Critère* : tout mouvement porte un n° de lot ; FEFO appliqué automatiquement.
- **Écran A2** — Ordre de transformation + recette (BOM process) + rendement (généalogie de
  lot, traçabilité amont/aval).
  *Critère* : rendement réel vs théorique affiché.
- **Écran A3** — Contrôle qualité HACCP + non-conformité + rappel produit.
  *Critère* : un lot suspect permet de lister en < 5 s tous les lots finis et clients
  impactés (traçabilité « one-up/one-back ») ; journal horodaté (incident, timestamp,
  initiateur, périmètre).
- **Jour de raffinement dédié (par sprint)** : clarté visuelle des statuts hold/release,
  parcours de traçabilité lisible en situation d'urgence (rappel produit).

### Sprints 13–14 — L5 Compta/Paie Madagascar (10 JT)
Abstraction du référentiel comptable (`core_accounting_framework`, `core_chart_of_accounts`,
`core_account`, `core_account_mapping` : PCG 2005 première classe, SYSCOHADA activable par
tenant/pays), paramètres réglementaires versionnés (`core_regulatory_parameter` : IRSA,
CNaPS, OSTIE, FMFP, TVA, SME — jamais en dur), saisie comptable rapide (X2), bulletin de
paie (X3).

- **Critères d'acceptation** : aucun barème réglementaire en dur (lu depuis la table
  versionnée à la date d'effet) ; validation des paramètres par un expert-comptable membre
  de l'OECFM avant mise en production ; plafond social (8×SME) calculé dynamiquement.
- **Jour de raffinement dédié** : saisie comptable rapide avec contreparties suggérées,
  lisibilité des écarts PCG 2005 vs SYSCOHADA pour éviter toute confusion.

### Sprints 15–16 — L6 Personnalisation & offline (6 JT)
Personnalisation utilisateur (`user_preference` : colonnes, densité, thème, langue), PWA /
mode dégradé (service worker, cache des écrans fréquents, files de saisie hors-ligne),
dark mode natif DaisyUI.

- **Critères d'acceptation** : le cœur de l'application fonctionne sans JS (progressive
  enhancement) ; un message explicite confirme une saisie mise en file d'attente hors
  connexion.
- **Jour de raffinement dédié** : cohérence du dark mode sur l'ensemble des écrans livrés
  jusqu'ici (audit rétroactif L0–L5).

### Sprint 17 — L7 IA gateway (5 JT)
`widehalo-ai-gateway` (FastAPI, Ollama local par défaut, repli Mistral), function-calling
contre des endpoints django-ninja en lecture seule, explicitement whitelistés — **pas de
text-to-SQL**.

- **Critère d'acceptation** : les tools n'exposent que les données du tenant courant (RLS),
  aucun droit DDL/écriture côté rôle DB de l'IA, chaque appel journalisé.
- **Jour de raffinement dédié** : présentation des réponses/actions IA dans l'UI (feedback
  clair sur ce que l'IA a fait, jamais une boîte de dialogue opaque).

## 6. Sprint 18 — Raffinement global & recette UX (5 JT)

Sprint de clôture de la Phase 1, dédié entièrement à la demande d'insistance UX/UI :

- Audit visuel transverse : cohérence des tokens et composants sur tous les écrans
  livrés (L0 à L7).
- Passage accessibilité complet : navigation clavier de bout en bout, ARIA sur les
  composants custom, contrastes WCAG AA (point d'attention DaisyUI/Flowbite qui ne
  garantissent pas toute la couche ARIA).
- Mesure SUS finale (cible ≥ 80, seuil minimal acceptable 68) comparée à la baseline
  mesurée avant refonte ; temps par tâche (réduction ≥ 30 % sur les 5 tâches critiques :
  créer devis, saisir réception lot, créer OF, saisir écriture, préparer expédition FEFO) ;
  SEQ (cible ≥ 6,0).
- Nettoyage des chemins legacy validés (étape d'élimination obligatoire du strangler
  pattern — « sinon vous n'avez pas une migration, vous avez deux systèmes pour
  toujours »).
- Tests de non-régression visuelle (snapshot) sur l'ensemble du périmètre livré.

## 7. Synthèse

| | |
|---|---|
| Durée totale | 19 sprints (Sprint 0 à 18) ≈ **19 semaines** |
| Budget Jour-Token | **81 JT** (5 Sprint 0 + 71 lots L0–L7 + 5 raffinement final) |
| Périmètre | Phase 1 Madagascar (L0–L7, Must + Should) |
| Hors périmètre | L8 — activation SYSCOHADA / roadmap OHADA (Côte d'Ivoire en priorité), Phase 2 |

### Risques du dossier applicables à ce planning (B.14)

| Risque | Mitigation dans ce planning |
|---|---|
| Dérive du budget d'architecture | Test CI de comptage (modèles/endpoints/écrans) mis en place dès le Sprint 0 |
| Migration écran par écran qui ne finit jamais | Étape d'élimination du legacy obligatoire, intégrée au Sprint 18 |
| Accessibilité incomplète (DaisyUI/Flowbite) | Jour de raffinement (J5) dédié à un budget accessibilité manuel dans **chaque** sprint, pas seulement en fin de projet |
| Confusion PCG 2005 / SYSCOHADA | Framework comptable par tenant/pays, PCG 2005 par défaut à Madagascar, garde-fou de validation (Sprints 13–14) |
| Paramètres réglementaires en dur ou périmés | Table versionnée + revue annuelle (Sprints 13–14) |
| Dépôt non audité au départ | Inventaire automatique préalable (Sprint 0) |
