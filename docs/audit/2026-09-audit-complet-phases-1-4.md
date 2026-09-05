# Audit complet — WideHalo v3, les 203 critères des cahiers des charges Phases 1 à 4

**Date** : 2026-09-05
**Périmètre** : dépôt `widehalo-web-python`, branche `claude/tender-ride-nqgodi`
au commit `c6b2cce` (état identique à `madagascar1`), confronté aux quatre cahiers
des charges officiels désormais versionnés dans
[`docs/cdc-complet/`](../cdc-complet/README.md) — 52 + 38 + 59 + 54 = **203 critères
d'acceptation**.

**Ce document remplace** [`2026-09-cahier-des-charges-v3-audit.md`](2026-09-cahier-des-charges-v3-audit.md)
(Phases 1+2, 2026-09-03) et [`2026-09-cahier-des-charges-v3-phase3-audit.md`](2026-09-cahier-des-charges-v3-phase3-audit.md)
(Phase 3, 2026-09-04) comme référence courante. Ceux-ci restent en place comme
documents historiques : 50 commits les séparent de cet audit, dont les 34 sprints du
plan Phase 3, et leurs verdicts ne sont plus vrais.

---

## Résumé exécutif

**Sur les 203 critères : 94 conformes (46 %), 58 partiels (29 %), 46 absents (23 %),
3 non vérifiables, 2 sans objet.**

| Phase | Critères | ✅ | 🟡 | ❌ | ❓ | N/A | Lecture |
|---|---|---|---|---|---|---|---|
| **1** — CRM, Sales, Accounting, IA, POS, Simulation | 52 | 25 | 19 | 6 | 2 | 0 | Les deux modules jadis absents (POS, Simulation) sont aujourd'hui les mieux tenus de la phase. Le CRM est le point faible : 4 de ses 7 critères sont absents. |
| **2** — BI, Forecast, Strategy, WhatsApp | 38 | 24 | 11 | 2 | 1 | 0 | Mécanique bâtie et testée, mais trois fils d'amorçage non branchés — dictionnaire vide, 4 indicateurs calculables, aucun ordonnanceur. |
| **3** — Stock, Achats, Production, Qualité, Paie, Forecast | 59 | 44 | 12 | 1 | 0 | 2 | **Le chantier le plus abouti.** Les 34 sprints du plan de fermeture ont tous été livrés ; les deux violations structurelles de l'audit précédent sont refermées. |
| **4** — Connectivité et intégrations | 54 | 1 | 16 | 37 | 0 | 0 | Jamais engagée. Les 16 partiels sont des briques antérieures réutilisables, pas des travaux commencés. |

**Trois lectures qui comptent plus que le total.**

1. **La Phase 3 a été retournée.** L'audit du 2026-09-04 comptait 8 conformes sur 59
   (14 %) ; il y en a **44** aujourd'hui (75 %). Les 34 sprints du plan ont tous été
   exécutés — chaque identifiant (P1–P7, A1–A6, B1–B5, C1–C6, D1–D5, E1–E9, F1–F4,
   T1–T4) est retrouvable dans le journal git — et les deux violations structurelles
   alors dénoncées, la double comptabilité de quantité et le portail salarié interdit,
   sont refermées. Le `README.md` et le plan lui-même affichent pourtant encore
   l'ancien verdict (§3.3).

2. **Le plus gros écart transverse n'est dans aucune grille de critères : rien
   n'ordonnance rien.** Cinquante et une commandes de gestion — rafraîchissement de
   l'entrepôt, diffusions BI, rapports planifiés, alertes de péremption, contrôles
   qualité en retard, réapprovisionnement, cohérence des quants — attendent un
   ordonnanceur qui n'existe pas : ni cron, ni service dans
   `docker-compose.prod.yml`, ni `Schedule` django-q2 enregistré (§3.1). En
   exploitation, l'entrepôt analytique n'est jamais rafraîchi, donc **BI, Forecast et
   Strategy travaillent sur des données vides** — quel que soit le nombre de ✅ qu'ils
   collectent ci-dessus.

3. **Une constante traverse les trois phases livrées : le mécanisme est écrit, la
   barrière qui devait le garantir ne l'est pas.** Sept critères exigent nommément un
   test d'intégration continue ; dans presque tous les cas le comportement est correct
   et le test manque — pas de garde sur la liste blanche du copilote (IA-1), sur le
   SQL en entrée de rapport (BI-2), sur les dates fériées en dur (FOR-5), sur les taux
   de TVA en dur (SAL-5) ; et là où la garde existe, sa portée est plus étroite que le
   critère (ACC-2 ignore la structure des états financiers, P3/PAY-1 ne détecte pas
   les montants ni les bornes de tranches). C'est la même classe d'écart que le
   dictionnaire d'indicateurs non peuplé ou la mesure `measure_adjustment_contribution`
   jamais appelée : **du code juste que rien ne met en service.**

---

## 1. Méthode

Reconduite à l'identique des deux audits précédents, pour rester comparable.

- **Introspection directe du code** : modèles, services, vues, API, migrations,
  gabarits, tests, intégration continue. Aucun verdict n'est repris des audits
  antérieurs — chaque critère est re-confronté au code d'aujourd'hui. Les audits
  antérieurs ne servent qu'à signaler une régression.
- **Chaque verdict est sourcé par un chemin de fichier**, et par une fonction ou une
  ligne quand c'est utile.
- Un point qui n'a pas pu être établi avec un niveau de confiance suffisant dans le
  temps imparti est marqué **❓ Non vérifié** plutôt que deviné.

| Verdict | Sens |
|---|---|
| ✅ | Conforme — le critère est tenu, et la preuve est dans le code |
| 🟡 | Partiel — la mécanique existe mais le critère n'est pas tenu en entier |
| ❌ | Absent — rien dans le code ne répond au critère |
| ❓ | Non vérifié — ni confirmé ni infirmé ici |
| N/A | Sans objet — non couvrable par du code |

**Deux pièges de référencement**, rappelés parce qu'ils faussent toute lecture
rapide (voir [`docs/cdc-complet/README.md`](../cdc-complet/README.md)) :

1. `PAY-1` à `PAY-8` désignent la **paie** en Phase 3 et l'**encaissement mobile** en
   Phase 4. Toutes les références de ce document sont donc préfixées : `P3/PAY-1`,
   `P4/PAY-1`.
2. Le dépôt cite abondamment des références de la forme `RG-CRM-5`, `RG-POS-5`,
   `RG-STK-6` : ce sont des **règles de gestion internes** héritées de la
   spécification de l'ancien WideHalo, dont la numérotation **entre en collision**
   avec celle des cahiers sans avoir le même contenu. Une citation `RG-CRM-5` dans le
   code ne prouve rien sur le critère `P1/CRM-5`. Cet audit ne retient que les
   citations sans préfixe `RG-`, et vérifie leur contenu plutôt que leur existence.

---

## 2. Table de conformité

### 2.1 Phase 1 — CRM, Sales, Accounting, IA, POS, Simulation financière (52 critères)

#### CRM — 7 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| CRM-1 | Glisser-déposer d'étape depuis le pipeline, transition au chatter et au journal d'audit, sans rechargement | ❌ | `apps/crm/views.py:73` (`action == "move_stage"`), `templates/crm/detail.html` | Aucun kanban ni glisser-déposer dans `apps/crm` ni `templates/crm` : le changement d'étape est un `<select>` + POST depuis la **fiche**, pas depuis le pipeline. `Sortable.min.js` est pourtant vendorisé et utilisé par `mrp` (`templates/mrp/kanban.html`) et `projects`. Le chatter n'est câblé sur aucun objet CRM (uniquement `templates/sales/order_detail.html:120` et `templates/mrp/detail.html:396`). Le journal d'audit, lui, est automatique (`apps/core/audit_signals.py::_on_save`). |
| CRM-2 | Fiche société : encours, solde comptable et 3 derniers documents de vente sans navigation | ❌ | `templates/partners/detail.html`, `apps/partners/views.py` | Aucune occurrence d'encours, de solde ni de derniers documents dans la fiche partenaire ni dans `templates/crm/`. |
| CRM-3 | Conversion d'une piste : société + contact + opportunité en une validation, sans ressaisie | ❌ | `apps/crm/views.py` (`lead_list`, `lead_detail`, `lead_create`) | Aucune fonction de conversion : `CrmLead` porte un `partner_id` nu, il n'existe ni service ni vue créant société, contact et opportunité en une passe. |
| CRM-4 | Opportunité sans activité depuis N jours (N paramétrable) dans la tuile « relances en retard » du launchpad | 🟡 | `apps/crm/services/ai_advisor_registration.py:34`, `apps/core/views/dashboard.py:28` | La matière existe — le conseiller IA propose « opportunité(s) sans activité récente — envisagez une relance ». Mais ce n'est pas une **tuile de launchpad**, et le seuil N n'est pas un paramètre : le tableau de bord n'expose qu'une tuile « Opportunités CRM ouvertes » via `crm.services.public.count_open_opportunities`. |
| CRM-5 | Pipeline vide : état vide pédagogique proposant création et import, jamais un tableau vide | ❌ | `templates/crm/list.html`, `templates/components/` | Aucune occurrence d'état vide dans `templates/crm/`, et aucun composant d'état vide générique dans `templates/components/` (8 composants, aucun `_empty_state`). |
| CRM-6 | Un commercial ne voit que son portefeuille ; restriction vérifiée côté serveur, y compris sur l'endpoint de fragment | ✅ | `apps/crm/services/scoping.py::scope_leads_for_user`, `apps/crm/tests/test_api.py` | Portée par vendeur assigné (et non par créateur), équipe pour `resp_commercial`, global pour `direction`/`admin`, au-dessus de `core.services.scoping.apply_scope`. Appliquée dans la vue **et** dans l'API. |
| CRM-7 | Parcours UC1 en moins de 90 secondes et 12 clics | ❓ | — | Non couvrable par introspection de code : exige une mesure sur parcours réel. Aucun test de parcours chronométré dans `tests/e2e/`. |

#### Sales — 8 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| SAL-1 | Devis de 5 lignes entièrement au clavier, sans souris, en moins de 2 minutes (UC2) | 🟡 | `templates/sales/quotation_create.html:13` (composant Alpine `lineItems()`) | L'écran de saisie multi-lignes existe ; ni la navigation clavier exhaustive ni le chronomètre ne sont vérifiés par un test. |
| SAL-2 | Devis accepté → commande → facture sans ressaisie de ligne, prix ni conditions | ✅ | `apps/sales/services/quotations.py`, `orders.py`, `invoicing.py:157` → `accounting.services.public.create_customer_invoice_from_source` | Chaîne réellement câblée de bout en bout. |
| SAL-3 | Validation de facture : écriture équilibrée, journal des ventes, comptes PCG paramétrés, facture non modifiable | ✅ | `apps/sales/services/invoicing.py:157`, `apps/accounting/migrations/0003_move_balance_and_immutability.py` | L'équilibre et l'immutabilité sont garantis par trigger PostgreSQL, pas seulement par le service. |
| SAL-4 | Modification ou suppression d'une facture validée refusée côté serveur, y compris par appel direct de l'API | ✅ | `apps/accounting/migrations/0005_move_immutability_field_aware.py`, `tests/migrations/test_accounting_immutability_triggers.py` | Le refus est au niveau base : contourner l'API ne suffit pas. |
| SAL-5 | Taux de TVA issu de la table de paramètres à la date du document ; test interdisant tout taux en dur dans le module | 🟡 | `apps/accounting/services/taxes.py::applicable_taxes`, `apps/accounting/models.py::AccTax` | Le taux vient bien d'une **table** (`AccTax` par tenant) et non du code, mais ce n'est pas la table de **paramètres réglementaires versionnés** (`core_regulatory_parameter`) : aucune résolution « à la date du document », aucun versionnement, aucun statut de validation. Et la garde CI correspondante n'existe pas : `tests/architecture/test_no_hardcoded_payroll_rates.py` ne couvre que `apps/payroll`, `test_no_hardcoded_account_numbers.py` que les numéros de compte. |
| SAL-6 | Numérotation des factures continue même en créations simultanées (test de concurrence) | 🟡 | `apps/accounting/migrations/0005_*` (numérotation par trigger DB) | La continuité est garantie par la base ; le **test de concurrence** exigé par le critère n'a pas été trouvé. |
| SAL-7 | Une interruption réseau pendant la saisie d'un devis ne fait perdre aucune ligne après rechargement | ❌ | `static/js/offline_queue.js`, `templates/sales/quotation_create.html` | Aucun autosave : ni `autosave`, ni `beforeunload`, ni sauvegarde périodique dans `templates/sales/`. La file générique `offline_queue.js` n'intercepte un formulaire **que si `navigator.onLine` est déjà faux** et rejoue une soumission — ce n'est pas une sauvegarde continue de brouillon, et elle ignore les formulaires multipart. |
| SAL-8 | PDF avec toutes les mentions obligatoires du tenant et montants en Ariary selon la règle unique | 🟡 | `apps/accounting/services/reports.py:1409::invoice_pdf`, `templates/reports/legal/` | Le PDF de facture est produit. Les gabarits légaux présents sont `quotation.html`, `order_confirmation.html`, `delivery_note.html` : le paramétrage par tenant des mentions obligatoires n'a pas été retrouvé comme tel. |

#### Accounting — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| ACC-1 | Tenant Madagascar : référentiel actif PCG 2005 et plan de comptes chargé **automatiquement** | 🟡 | `apps/accounting/services/chart_of_accounts.py:66::load_pcg2005`, `apps/accounting/fixtures/pcg2005_mg.json` (54 comptes), `apps/core/migrations/0011_seed_country_defaults_madagascar.py` | Le plan existe et se charge, mais **par commande de gestion** (`load_pcg2005`, `seed_accounting`) : aucun appel automatique à la création d'un tenant. `CountryDefaultsProfile.chart_of_accounts_code = "PCG2005"` est, de l'aveu de sa propre docstring, « une simple métadonnée informative ». |
| ACC-2 | Test interdisant tout numéro de compte **et toute structure d'état financier** en dur | 🟡 | `tests/architecture/test_no_hardcoded_account_numbers.py` | Le test existe et est bloquant en CI. Mais il ne couvre que les **numéros de compte** de `apps/accounting`, avec 3 fichiers en liste d'exception dont `services/reports.py` — c'est-à-dire précisément le fichier qui porte la **structure des états financiers**. Sa propre docstring le reconnaît : « l'abstraction complète reste un chantier plus large que cette correction ponctuelle — ce test ne prétend PAS le résoudre ». |
| ACC-3 | Écriture de 4 lignes entièrement au clavier, avec proposition de contrepartie et contrôle d'équilibre en continu | 🟡 | `apps/accounting/services/quick_entry.py:18::suggest_counterpart_account` | La proposition de contrepartie existe et est fondée sur la fréquence réelle des appariements. Le parcours clavier intégral et l'affichage de l'équilibre en continu n'ont pas été vérifiés côté gabarit. |
| ACC-4 | Écriture déséquilibrée refusée **par la base de données**, même en contournant l'interface | ✅ | `apps/accounting/migrations/0003_move_balance_and_immutability.py`, `tests/migrations/test_accounting_immutability_triggers.py` | Trigger PostgreSQL, testé. |
| ACC-5 | Lettrage automatique sur montant identique et référence commune, le reste laissé au manuel sans le traiter à tort | ✅ | `apps/accounting/services/bank_reconciliation.py` — `_amount_matches:107`, `_reference_matches:121`, `_partner_matches:136`, `suggest_matches:159`, `confirm_reconciliation:204`, `manual_match:226` | Le moteur **propose** et ne poste rien : `unmatched_or_suggested_lines` laisse explicitement les cas non appariés au traitement manuel. |
| ACC-6 | Déclaration de TVA rapprochée à l'ariary près des écritures de la période, avec justificatif ligne à ligne | ❓ | `apps/accounting/services/tax_returns.py` | Le service de déclaration existe ; le rapprochement à l'ariary près et l'état justificatif ligne à ligne n'ont pas été vérifiés dans le temps imparti. |
| ACC-7 | Bilan et compte de résultat au format PCG 2005, exportables | ✅ | `apps/accounting/services/reports.py`, `apps/reporting/` (moteur d'export PDF/XLSX/CSV/JSON) | Produits et exportables. La **forme** PCG est en dur dans `reports.py` — c'est le revers de ACC-2. |
| ACC-8 | Toute modification d'un paramètre réglementaire crée une version, conserve la précédente, apparaît au journal d'audit | ✅ | `apps/core/models/regulatory.py:58` (`version` auto-numérotée par lignée dans `save()`), `apps/core/migrations/0009_regulatory_parameter_no_overlap.py` (contrainte d'exclusion `btree_gist`), `apps/core/audit_signals.py::_on_regulatory_parameter_save` | Une correction crée une ligne, ne modifie jamais l'ancienne ; le chevauchement de périodes est interdit par la base ; la journalisation est branchée séparément parce que le modèle n'hérite pas de `BaseModel`. |
| ACC-9 | Le déploiement échoue si un paramètre utilisé par un calcul actif porte le statut `NON_VALIDE` | 🟡 | `apps/core/services/regulatory_governance.py` (`ACTIVE_CALCULATION_PARAMETER_CODES`, `unvalidated_active_parameters()`), `apps/core/management/commands/check_regulatory_validation.py` (sortie en code 1), `apps/payroll/services/batches.py:130` | Le verrou existe et sort en erreur. Deux réserves : la liste des paramètres « de calcul actif » ne contient que **10 codes, tous `payroll.*`** — aucun paramètre comptable n'y figure ; et le verrou est une **commande à lancer au déploiement** (`docs/DEPLOYMENT_HETZNER.md`), pas un job d'intégration continue. |
| ACC-10 | Exercice clos : toute écriture refusée, y compris par appel direct de l'API et pour un administrateur | 🟡 | `apps/accounting/services/moves.py:87-91` (`Période close : publication refusée.`) | Le refus est au niveau **service** — donc effectif pour l'API, qui passe par lui. Contrairement à l'équilibre (ACC-4) et à l'immutabilité (SAL-4), il n'est pas garanti par la base ; l'exemption ou non d'un administrateur n'a pas été vérifiée. |

#### IA — 9 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| IA-1 | Test de CI échouant si un endpoint accessible au gateway autorise une écriture ou sort de la liste blanche | 🟡 | `apps/core/services/data_query_tool_registry.py`, `apps/ai/tests/test_data_query_gateway.py::test_tool_never_offered_without_permission` | Le confinement est **plus strict que demandé** : le modèle n'atteint aucun endpoint, seulement 8 outils déclarés en liste blanche, tous en lecture — aucun outil d'écriture n'existe. Mais la **garde CI** exigée n'existe pas : `tests/architecture/` contient 7 tests, aucun ne porte sur le registre d'outils. La protection repose sur des tests unitaires du module, pas sur une barrière d'architecture. |
| IA-2 | Tout appel d'outil journalisé avec utilisateur, tenant, outil, paramètres et durée | 🟡 | `apps/ai/models.py::AiDataQuery` (`tools_called` = liste ordonnée de `{code, args}`), `apps/core/audit_signals.py::_on_save` | Utilisateur, tenant, outil et paramètres sont journalisés — et, `AiDataQuery` héritant de `BaseModel`, le journal d'audit central l'enregistre automatiquement. **La durée n'est stockée nulle part** : `AiRequest` porte des estimations de tokens, pas une latence. |
| IA-3 | Aucune donnée que le rôle de l'utilisateur ne permettrait de consulter dans l'interface | ✅ | `apps/ai/services/data_query_gateway.py` (catalogue filtré par `user.has_perm(required_permission)` **avant** présentation au modèle), `apps/ai/tests/test_data_query_gateway.py::test_tool_never_offered_without_permission` | Refus par défaut. Le masquage de champs sensibles est en outre propagé : `sales.margin_report` transmet `role_codes` (`apps/sales/services/ai_data_query_registration.py:55`). |
| IA-4 | Aucune donnée d'un autre tenant, même nommée explicitement (test à deux tenants) | 🟡 | `apps/core/middleware.py::TenantMiddleware` (`SET LOCAL app.tenant_id`), `apps/core/management/commands/apply_rls.py` | L'isolation est réelle et défendue par la sécurité au niveau des lignes de PostgreSQL. Le **test d'isolation à deux tenants spécifique au copilote** exigé par le critère n'a pas été trouvé dans `apps/ai/tests/`. |
| IA-5 | Instruction hostile dans un champ de données : aucun appel hors liste blanche, aucune écriture | ✅ | `apps/ai/services/data_query_gateway.py` (boucle bornée `_MAX_TOOL_ROUND_TRIPS = 3`, arguments validés contre un schéma avant exécution, outil inconnu ignoré et journalisé), `apps/ai/tests/test_data_query_gateway.py::test_invalid_arguments_skip_the_tool_call_without_raising`, `::test_bounded_loop_terminates_even_if_the_llm_keeps_calling_tools` | Une écriture est structurellement impossible : aucun outil d'écriture n'est déclaré. |
| IA-6 | Gateway arrêté : ERP intégralement fonctionnel, message d'indisponibilité clair, sans erreur technique | ✅ | `apps/core/services/ai_assistant.py:124-129` (`StubAIProvider` tant que `AI_PROVIDER_CONFIG` est vide — **c'est le défaut**), `apps/ai/tests/test_data_query_gateway.py::test_provider_error_degrades_cleanly_never_raises` | Dégradation testée, jamais d'exception remontée. |
| IA-7 | Délai de réponse borné ; au-delà du seuil, réponse d'attente explicite plutôt qu'une page bloquée | 🟡 | `apps/core/services/ai_assistant.py:186,244` (`timeout=_DEFAULT_TIMEOUT_SECONDS`) | Le délai est borné côté client HTTP. La **réponse d'attente explicite** à l'utilisateur au-delà du seuil n'a pas été retrouvée : le dépassement produit une dégradation, pas un écran d'attente. |
| IA-8 | Chaque réponse chiffrée fournit le lien vers l'écran ou l'état qui permet de vérifier le chiffre | ❌ | `apps/ai/services/data_query_gateway.py`, `apps/ai/models.py::AiDataQuery` | Aucune notion de lien de vérification : ni champ, ni construction d'URL, ni renvoi vers un écran dans la réponse. |
| IA-9 | Repli cloud désactivé par défaut ; son activation affiche les données qui sortiront et est journalisée | 🟡 | `apps/core/services/ai_assistant.py:272-279` (`AI_PROVIDER_CONFIG` vide par défaut, connecteur actif seulement si `base_url` **et** `api_key` sont fournis) | La désactivation par défaut est acquise et vérifiée. L'**affichage explicite des données qui sortiront du serveur** au moment de l'activation n'existe pas : l'activation est un réglage d'environnement, sans écran de consentement ni journalisation dédiée. |

#### POS — 9 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| POS-1 | Vente de 3 articles en espèces avec **rendu de monnaie** en moins de 30 s, tactile ou clavier (UC6) | 🟡 | `templates/pos/sale.html` (catalogue, moyens de paiement et taux embarqués par `json_script`, panier Alpine), `apps/pos/services/orders.py:243` | L'écran de vente existe et fonctionne sans appel réseau après chargement. Mais **aucun calcul ni affichage de rendu de monnaie** dans `apps/pos/` ni `templates/pos/` (la seule occurrence est un libellé de test, `apps/pos/tests/test_sessions.py:141`), et le chronomètre n'est pas mesuré. |
| POS-2 | Toute vente hors session de caisse ouverte refusée côté serveur | ✅ | `apps/pos/services/sessions.py:43`, `apps/pos/services/orders.py:40`, `apps/pos/tests/test_sessions.py` | |
| POS-3 | Réseau coupé : vente aboutie, ticket produit, synchronisation sans perte ni double comptabilisation | 🟡 | `apps/pos/services/orders.py:378::sync_order`, `apps/pos/models.py::PosSyncLog`, `apps/pos/tests/test_offline_sync.py`, `static/js/offline_queue.js`, `static/js/sw.js` | La vente hors ligne et la reprise idempotente sont réelles et testées (`client_uuid` comme clé). Le **ticket produit** ne l'est qu'à l'écran : il n'existe aucun gabarit d'impression (voir POS-6 ci-dessous et §3). |
| POS-4 | Numérotation des tickets continue par caisse, sans trou ni doublon, y compris après une période hors ligne et en concurrence | ✅ | `apps/pos/models.py:89` (`local_sequence`, préfixe de caisse), `apps/pos/services/orders.py:396-402`, `apps/pos/tests/test_offline_sync.py` | « Ni trou, ni doublon » est explicitement l'invariant testé. |
| POS-5 | Paiement mixte espèces + mobile money accepté ; référence de transaction obligatoire et conservée | ✅ | `apps/pos/services/orders.py:214`, `apps/pos/models.py::PosPaymentMethod.requires_reference`, `apps/pos/tests/test_orders.py` | |
| POS-6 | Clôture imposant un comptage ; tout écart enregistré avec motif, visible au journal d'audit et à l'écran de contrôle | ✅ | `apps/pos/services/sessions.py:183::close_session` (écart non nul → `ValidationError` si `variance_reason` vide), `apps/core/audit_signals.py::_on_save` (journalisation automatique de tout `BaseModel`), `apps/pos/views.py::session_detail` | Le comptage physique est obligatoire et porte l'écriture ; l'écart n'est jamais absorbé silencieusement. |
| POS-7 | Clôture générant une écriture équilibrée sur les comptes PCG paramétrés pour chaque moyen de paiement | ✅ | `apps/accounting/services/public.py:572-606::create_pos_session_closing_entry_from_source`, `apps/pos/tests/test_sessions.py` | Une ligne par moyen de paiement, plus une ligne d'écart absorbant le déséquilibre structurel. |
| POS-8 | Prestation de service facturée sans article physique ni référence de stock, avec acompte et solde | ✅ | `apps/pos/services/orders.py:102` (`line_type=SERVICE` ne référence jamais de variante ni de mouvement), `is_deposit` (`apps/pos/models.py`, `schemas.py:95`, `api.py:156`) | |
| POS-9 | Session close refusant toute modification, y compris par appel direct de l'API et pour un administrateur | ✅ | `apps/pos/services/sessions.py:191-194`, `apps/pos/services/orders.py:302`, `apps/pos/tests/test_sessions.py:155` | Le refus est porté par le service qu'empruntent l'écran **et** l'API. |

#### Simulation financière — 9 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| SIM-1 | Modification d'un levier : tous les indicateurs à jour en moins de 100 ms sur réseau dégradé | 🟡 | `static/js/simulation_engine.js` (miroir du moteur Python), `templates/simulation/workbench.html:52` (`<input type="range" @input="recompute()">`, aucun bouton « calculer ») | Le calcul est local, donc sans aller-retour réseau — la conception rend le seuil atteignable. Mais **aucune mesure de latence** n'est faite dans les tests : les 100 ms sont une intention, pas un résultat vérifié. |
| SIM-2 | Socle chargé en un seul appel et sous le budget de taille fixé pour le réseau cible | 🟡 | `apps/simulation/services/baseline.py:68::build_baseline`, `tests/ui/test_page_budgets.py` (200 Ko gzip par page, 30 Ko par fragment) | Le socle est bien chargé en un appel. Un budget de poids de page existe et est bloquant, mais il est **générique** : aucun budget de taille propre au socle de simulation. |
| SIM-3 | Scénario enregistré conservant date d'extraction, périmètre et version des paramètres réglementaires | ✅ | `apps/simulation/models.py:29` (`SimBaseline.as_of_date`, `regulatory_param_version:57`), `:74` (`SimScenario.baseline_regulatory_param_version`), `apps/simulation/services/baseline.py:135` (`get_parameter_with_version`) | Le socle est recopié par valeur dans le scénario : un scénario reste lisible même si le socle change. |
| SIM-4 | Recalcul serveur redonnant les mêmes valeurs qu'en local à l'ariary près ; toute divergence bloque l'enregistrement | ✅ | `apps/simulation/services/scenarios.py:88::_assert_client_matches_server`, `apps/simulation/tests/test_engine_js_parity.py` | La parité JS/Python est vérifiée en exécutant réellement le JavaScript via Node et en comparant. Réserve : le test se saute proprement si `node` est absent, et aucune étape `setup-node` n'apparaît dans `.github/workflows/ci.yml` — la parité pourrait donc n'être jamais vérifiée en CI (voir §3). |
| SIM-5 | Aucune écriture comptable ni document métier créé ou modifié par le module | ✅ | `apps/simulation/tests/test_engine.py`, `templates/simulation/workbench.html:69`, `apps/core/services/rbac_policy.py` | Le module ne produit aucune écriture ; c'est un invariant testé, pas seulement documenté. |
| SIM-6 | Deux à quatre scénarios comparables côte à côte, avec écart en valeur et en pourcentage | ✅ | `apps/simulation/services/scenarios.py`, `templates/simulation/compare.html`, `apps/simulation/tests/test_compare.py` | |
| SIM-7 | Projection de trésorerie à 13 semaines intégrant encours client, échéances fournisseurs et leviers de délai (UC7) | ✅ | `apps/simulation/services/engine.py:150::compute_treasury_projection` (`TREASURY_WEEKS = 13`, re-découpage des lignes ouvertes par les leviers de délai, `dip_week`, `couverture_jours`), `apps/simulation/tests/test_engine.py` | |
| SIM-8 | Scénario proposé par le copilote exécuté par le moteur déterministe, journal reliant la demande en langage naturel aux leviers appliqués | ✅ | `apps/simulation/models.py:121-122` (`ai_generated`, `ai_request_text`), `apps/simulation/api.py` (`POST /simulation/ai/apply`), `apps/simulation/services/ai_data_query_registration.py` | Le copilote propose des leviers ; c'est `engine.py` qui calcule. |
| SIM-9 | Un utilisateur ne simule que sur le périmètre que son rôle l'autorise à consulter (deux rôles, deux tenants) | ✅ | `apps/simulation/services/scoping.py`, `apps/simulation/tests/test_scenarios.py`, `apps/simulation/tests/test_views.py` | |

### 2.2 Phase 2 — Business Intelligence, Forecast, Strategy, WhatsApp (38 critères)

**Constat d'ensemble, avant le détail** : la mécanique de la Phase 2 est bâtie et
testée, mais **trois fils d'amorçage ne sont pas branchés** — le dictionnaire
d'indicateurs n'est peuplé nulle part hors tests, quatre indicateurs seulement sont
réellement calculables, et aucun ordonnanceur ne déclenche le rafraîchissement de
l'entrepôt (§3.1). Plusieurs verdicts ✅ ci-dessous portent donc sur du code correct
qui, en exploitation, travaillerait sur des données vides.

#### Business Intelligence — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| BI-1 | Définition, formule, propriétaire et version par indicateur ; test de cohérence entre deux écrans | 🟡 | `apps/analytics/models.py:583::AnMetricDefinition` (`formule`, `proprietaire`, `version`, `statut`, `date_effet`, `is_current`, unicité partielle `(tenant, code) WHERE is_current`), `apps/bi/tests/test_query.py` | Le registre porte les quatre attributs exigés. Mais **la formule n'est pas exécutable** : le calcul passe par deux tables de correspondance codées en dur (`apps/bi/services/metric_computers.py::METRIC_FACTS`, 4 codes seulement ; `apps/analytics/services/fact_specs.py::FACT_SPECS`, 7 faits, `AnFactPaie` absent). Un indicateur du dictionnaire absent de `METRIC_FACTS` est **silencieusement exclu** des rapports (`apps/bi/services/query.py::run_report`). Le test de cohérence entre deux écrans n'a pas été trouvé. |
| BI-2 | Le constructeur n'accepte que mesures et dimensions déclarées ; test de CI interdisant tout SQL en entrée | 🟡 | `apps/bi/services/query.py::run_report` (mesure inconnue ignorée — `test_run_report_ignores_unknown_metric_code`), `apps/bi/models.py::BiReport.definition` (JSON `{metric_codes, dimensions, filters, chart_type}`) | Le fond est tenu : rien d'autre que des codes déclarés n'entre dans l'agrégation, et aucun `raw()`/`RawSQL`/`extra()` n'existe dans `apps/bi` ni `apps/analytics`. Mais **la garde CI exigée n'existe pas** : aucun des 7 tests de `tests/architecture/` ne porte sur l'absence de SQL en entrée d'endpoint. |
| BI-3 | Rapports retenus après rationalisation reconstruits sur la couche sémantique et rapprochés à l'ariary près | ❌ | — | Aucune trace de rationalisation du catalogue de rapports, ni de rapprochement des rapports reconstruits avec leur version d'origine. Les ~85 rapports figés restent enregistrés dans `reporting` (`register_report`), indépendants de la couche sémantique de `bi`. |
| BI-4 | État du rafraîchissement (dernière exécution, durée, volume, échec) visible sur chaque tableau de bord | 🟡 | `templates/bi/index.html:38-42` (`refresh_summary` : statut, durée, lignes traitées, message d'erreur), `apps/analytics/models.py::AnRefreshRun` | Toute l'information exigée est affichée, sans passer par un écran d'administration — mais **sur la page d'index de BI**, pas sur chaque tableau de bord. |
| BI-5 | Tableau de bord de six tuiles en moins de 3 s sur réseau dégradé, sur trois exercices ; une tuile lente dégrade seule | ❓ | `tests/ui/test_page_budgets.py` (200 Ko gzip par page, 30 Ko par fragment) | Un budget de poids de page existe, mais aucune mesure de temps de chargement ni de dégradation indépendante par tuile. Non vérifiable ici. |
| BI-6 | Un utilisateur ne voit que ce que son rôle autorise, y compris en agrégé (test par rôle et par maille) | ✅ | `apps/bi/services/query.py::run_report` (droits appliqués **avant** agrégation, `scope_notes` explicatives), `apps/bi/tests/test_query.py::test_run_report_excludes_metric_unauthorized_for_role_before_aggregation`, `::test_run_report_caps_dimension_at_maille_minimale` | Les deux dimensions du critère — le rôle et la maille — sont testées séparément. |
| BI-7 | Diffusion planifiée journalisée avec destinataire, périmètre, canal et statut | ✅ | `apps/bi/models.py::BiDiffusionLog` (destinataire, canal, `scope_summary`, statut), `apps/bi/services/diffusion.py`, `apps/bi/tests/test_diffusion.py` | Le rapport est **recalculé pour chaque destinataire** selon son rôle, ce que `reporting` ne fait pas. |
| BI-8 | Export au-delà du seuil traité en asynchrone, téléchargement différé, interface jamais bloquée | ✅ | `apps/bi/services/export.py` (délégué à `reporting` via le rapport générique `bi.dynamic_report`), `apps/reporting/services/engine.py:224` (`enqueue` au-delà de `REPORTING_ASYNC_THRESHOLD_SECONDS`), `apps/bi/tests/test_export.py` | Aucun modèle de tâche dupliqué : `bi` réutilise `RptJob`. |
| BI-9 | Modification de définition : version créée, précédente conservée, rapports impactés listés, journal d'audit | ✅ | `apps/analytics/services/dictionary.py::register_metric` (versionne **par insertion**, jamais d'`UPDATE` en place), `list_metric_history`, `apps/bi/views.py::metric_history`, `templates/bi/_metric_history.html` (liste des rapports impactés), `apps/core/audit_signals.py::_on_save` | |
| BI-10 | Depuis toute valeur agrégée, atteindre en un clic les lignes qui la composent ; blocage expliqué | ✅ | `apps/bi/services/query.py::drill_down` (renvoie `{"blocked": True, "reason": ...}` plutôt qu'un résultat tronqué), `apps/bi/tests/test_query.py::test_drill_down_returns_underlying_rows`, `::test_drill_down_is_blocked_when_maille_minimale_set` | |

#### Forecast — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| FOR-1 | Référence naïve saisonnière toujours calculée et affichée ; modèle qui ne la bat pas signalé | ✅ | `apps/forecast/services/engine.py::select_model` (`reference_naive_beats_selected`), onglet qualité de `apps/forecast/views.py` | |
| FOR-2 | Erreur absolue moyenne, pondérée et biais, mesurées par rétrotest glissant et non par ajustement sur l'historique complet | ✅ | `apps/forecast/models.py::ForSeriesForecast` (`error_mae_pct`, `error_weighted_pct`, `error_bias_pct`, `test_window_start/end`), `apps/forecast/services/engine.py::backtest` (marche avant) | |
| FOR-3 | Sélection automatique reproductible et motivée (modèle retenu, score, fenêtre, modèles écartés) | ✅ | `apps/forecast/services/engine.py::select_model`, champs `rejected_models`, `selected_model_score`, `test_window_start/end` | `insufficient_history_for_seasonality` explicite aussi pourquoi un modèle saisonnier a été écarté sous 24 mois. |
| FOR-4 | Points exceptionnels exclus de l'apprentissage sans disparaître de l'historique affiché | ✅ | `apps/forecast/models.py::ForExceptionalPoint`, `apps/forecast/services/engine.py` | |
| FOR-5 | Calendrier appliquant jours ouvrés et fériés malgaches lus en table ; test interdisant toute date fériée en dur | 🟡 | `apps/forecast/services/calendar.py:5-31` (« QUE via une ligne `ForHoliday` », aucune date en dur), `apps/forecast/models.py::ForHoliday` | La lecture en table est acquise et documentée comme telle. Le **test** exigé par le critère n'existe pas : aucun test d'architecture ne porte sur les dates fériées. |
| FOR-6 | Ajustement humain tracé (auteur, date, avant/après, motif) et réversible ; prévision statistique consultable en parallèle | ✅ | `apps/forecast/services/adjustments.py` (motif obligatoire, réversible), `apps/forecast/views.py` | |
| FOR-7 | Apport de l'ajustement humain mesuré : erreur ajustée vs statistique sur les périodes échues | 🟡 | `apps/forecast/services/adjustments.py:61-77::measure_adjustment_contribution`, `apps/forecast/views.py:38-40` | La mesure est **écrite et correcte** (`statistical_error_pct` / `adjustment_error_pct` contre le réalisé) mais **n'est appelée que depuis `apps/forecast/tests/test_adjustments.py`** — aucun appel dans une vue, une API ou une commande. Or l'onglet qualité filtre sur `statistical_error_pct__isnull=False` : en exploitation, il restera **vide**. |
| FOR-8 | Prévision de ventes intégrant les ventes POS au même titre que les facturées, sans double comptage | ✅ | `apps/analytics/services/public.py:187-203::get_sales_value_series` | Fusionne `AnFactVente` et `AnFactTicketPos`, avec la justification de l'absence de double comptage (flux documentaires disjoints, un ticket POS n'est jamais converti en `SalesOrder`) et une ventilation par canal. |
| FOR-9 | Prévision d'encaissement dérivée du comportement de règlement observé **par client**, non d'un délai théorique unique | 🟡 | `apps/forecast/services/treasury.py:5,34-35` | Le principe est tenu — le délai vient de l'observation, pas d'un paramètre. Mais la docstring précise que, faute de ventilation par client dans la série « canal », **le délai retenu est la moyenne tous clients confondus** sur l'agrégat global : le « par client » n'est donc pas systématique. |
| FOR-10 | Prévision publiée disponible comme scénario de référence dans la simulation financière de la Phase 1, avec version et date | ❌ | `apps/simulation/services/baseline.py:29,110` (`get_treasury_forecast_summary` → `accounting.services.reports.treasury_forecast`) | Le socle de simulation se nourrit de la trésorerie **comptable**, pas d'une `ForPublication`. Aucun chemin ne fait entrer une prévision publiée dans `apps/simulation`. Le raccordement existe en revanche vers `strategy` (initialisation d'un budget depuis une publication, STR-4). |

#### Strategy — 8 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| STR-1 | Objectif sans indicateur du dictionnaire refusé ; avancement calculé depuis l'indicateur, jamais saisi | 🟡 | `apps/strategy/services/objectives.py:84-97` (`metric_code` fourni → doit référencer un indicateur **publié** du dictionnaire), `refresh_key_result_from_dictionary` → `bi.services.public.get_metric_current_value` | Le contrôle n'est appliqué que **si** `metric_code` est fourni : un résultat clé reste créable sans lui, via l'ancien couple `kpi_source_module`/`kpi_source_function` conservé en compatibilité ascendante. La création n'est donc pas refusée comme l'exige le critère. |
| STR-2 | Cascade affichant la contribution de chaque niveau et consolidant sans double comptage | ✅ | `apps/strategy/services/objectives.py::compute_cascade_contribution`, `recompute_objective_status` (statut calculé depuis la progression agrégée, jamais déclaré) | |
| STR-3 | Budget verrouillé refusant toute modification y compris par l'API ; révision versionnée, ancienne consultable | ✅ | `apps/strategy/migrations/0004_budget_and_review_pack_immutability.py` (trigger PostgreSQL), `apps/strategy/models.py::StgBudget.previous_version` | Le refus est au niveau base : l'API ne peut pas le contourner. |
| STR-4 | Budget initialisable depuis un scénario de simulation ou une prévision publiée, source et version conservées | ✅ | `apps/strategy/services/` (initialisation depuis `SimScenario` ou `ForPublication` avec conservation de la référence et de la version) | |
| STR-5 | Écart budget/réel calculé sur la même définition d'indicateur que le réel ; test vérifiant l'identité des définitions | ✅ | `apps/strategy/services/` `compute_variance` (appelle **exactement** la même fonction que BI), `apps/strategy/tests/` | |
| STR-6 | Écart au-delà du seuil empêchant la clôture de la revue sans commentaire de gestion sur la ligne | ✅ | `apps/strategy/services/` `can_close_review` | |
| STR-7 | Pack de revue réouvert un mois plus tard affichant exactement les mêmes valeurs, définitions et commentaires | ✅ | `apps/strategy/models.py::StgReviewPack` (figé et horodaté), `apps/strategy/migrations/0004_budget_and_review_pack_immutability.py` (trigger d'immutabilité) | |
| STR-8 | Cartographie des risques : probabilité, impact, mesure de maîtrise, propriétaire, date de réévaluation ; réévaluation au journal d'audit | ✅ | `apps/strategy/models.py::StgRisk` (probabilité × impact, réévaluation tracée), `apps/core/audit_signals.py::_on_save` | |

#### WhatsApp — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| WA-1 | Aucun envoi sans consentement enregistré et non révoqué ; contrôle à l'envoi ; test qu'aucune voie applicative ne le contourne | 🟡 | `apps/whatsapp/models.py::WaConversation` (`consent_granted_at`/`consent_revoked_at`/`consent_source`/`consent_granted_by`), `apps/whatsapp/services/messaging.py::send_governed_template_message` (contrôle **à l'envoi**, pas seulement à l'affichage) | Le contrôle à l'envoi est acquis. Le test exigé — qu'aucune voie applicative (import, action de masse, tâche planifiée) ne contourne le point d'envoi gouverné — n'a pas été trouvé, et un **second webhook plus ancien subsiste** dans `apps/core/api_notifications.py`. |
| WA-2 | Révocation effective immédiatement, déclenchable par un seul message du destinataire, journalisée | ✅ | `apps/whatsapp/models.py` (`consent_revoked_at`), `apps/whatsapp/services/inbound.py`, `apps/core/audit_signals.py::_on_save` | |
| WA-3 | Hors fenêtre de service, seul un modèle approuvé est envoyé ; tout envoi libre refusé côté serveur | ✅ | `apps/whatsapp/models.py::WaConversation.is_service_window_open` (24 h), `WaMessageTemplate` (machine à états draft → pending_review → approved/rejected vérifiée à l'envoi), `apps/whatsapp/services/messaging.py` | |
| WA-4 | Envoi journalisé avec modèle, variables, destinataire, statut de livraison, catégorie et coût imputé | ✅ | `apps/core/models/*::WhatsAppMessage` (`cost_ariary`, statut, `retry_count`), `apps/whatsapp/models.py::WaMessageTemplate` (catégories Meta, `estimated_cost_ariary`) | Réserve reportée en WA-10 : le coût est l'**estimation** du modèle, jamais le coût réellement facturé. |
| WA-5 | Plafond mensuel par tenant arrêtant les envois non critiques et alertant avant d'être atteint ; limite de fréquence par destinataire | 🟡 | `apps/whatsapp/services/usage.py`, `apps/core/models/tenant.py` (`whatsapp_monthly_cost_cap_ariary`, `whatsapp_cost_cap_hard_stop`, `whatsapp_cost_alert_threshold_pct`) | Le plafond mensuel et le seuil d'alerte existent et fonctionnent. La **limite de fréquence par destinataire** (anti-boucle) n'a pas été trouvée. |
| WA-6 | Messages entrants et sortants dans le chatter de l'objet concerné, sans action manuelle | ✅ | `apps/whatsapp/services/inbound.py` (canal chatter ouvert automatiquement), `apps/core/services/chatter.py` | |
| WA-7 | Canal indisponible : ERP intégralement fonctionnel, envois en file avec état visible et **repris automatiquement** | 🟡 | `apps/core/services/whatsapp.py::get_whatsapp_client` (`StubWhatsAppClient` tant que `WHATSAPP_ENABLED` est faux — c'est le défaut), `apps/whatsapp/services/messaging.py::retry_failed_messages` (backoff 5 min / 30 min / 2 h, `MAX_RETRY_ATTEMPTS = 3`) | L'ERP reste fonctionnel et la reprise existe avec un état visible. Mais **l'envoi est synchrone (aucune file) et la reprise ne se déclenche qu'à la main** — bouton `/whatsapp/messages/retry/` ou `POST /whatsapp/messages/retry` : aucune commande de gestion, aucune tâche planifiée. « Repris automatiquement » n'est pas tenu. |
| WA-8 | Parcours entrant borné à un menu d'intentions déclarées ; aucune génération libre ; test le vérifiant | ✅ | `apps/whatsapp/services/inbound.py` (menu borné à 3 choix, aucun NLU), `apps/whatsapp/tests/` | |
| WA-9 | Tout chiffre communiqué provient d'un outil en lecture seule du gateway, avec les mêmes restrictions de rôle et de tenant | ✅ | `apps/whatsapp/services/ai_data_query_registration.py:27` (outil déclaré avec `required_permission=whatsapp.view_waconversation`), `apps/ai/services/data_query_gateway.py` (filtrage par permission avant présentation) | |
| WA-10 | Écran de configuration énonçant quelles données personnelles sortent et vers qui ; activation journalisée ; aucune règle tarifaire dans le code | 🟡 | `templates/whatsapp/config.html`, `apps/whatsapp/models.py::WaMessageTemplate.estimated_cost_ariary` | L'écran de configuration existe. Deux réserves : le **coût réellement facturé par Meta n'est jamais récupéré** (l'estimation est portée par le modèle de message, donc une grille tarifaire vit bien en base et non dans le code — ce point est tenu) ; et la limitation multi-tenant est structurelle — un seul `WHATSAPP_PHONE_NUMBER_ID` global pour tout le déploiement, « un vrai routage par tenant resterait à construire » (docstring), ce qui affaiblit l'énoncé « vers qui » sortent les données. |

### 2.3 Phase 3 — Stock, Achats/Import, Production, Qualité, Paie, extension Forecast (59 critères)

**Ce qui a changé depuis l'audit du 2026-09-04.** Ce cahier avait alors 8 critères
conformes sur 59, et deux violations structurelles. Les **34 sprints du plan de
fermeture** (`docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md`) ont depuis
tous été livrés — P1–P7, A1–A6, B1–B5, C1–C6, D1–D5, E1–E9, F1–F4, T1–T4, chacun
retrouvé dans le journal git. **Les deux violations sont refermées** : la réception
d'achat crée désormais un mouvement de stock (`apps/purchase/services/receiving.py:41`
importe `receive_purchase_line` depuis `stocks.services.public`), et le portail
salarié a été retiré (`apps/payroll/urls.py` ne porte plus que 3 routes). Le plan,
lui, se déclare toujours « prospectif, non encore exécuté » — voir §3.

#### Stock et entrepôt — 12 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| STK-1 | Mouvement rendant le stock négatif refusé ; sous dérogation, accepté avec motif obligatoire et journal d'audit | ✅ | `apps/stocks/models.py::StkNegativeStockException`, `apps/stocks/services/moves.py`, `apps/core/audit_signals.py::_on_save` | |
| STK-2 | Somme des mouvements recalculée depuis zéro strictement égale à l'agrégat affiché ; contrôle nocturne détectant une divergence | 🟡 | `apps/stocks/services/consistency.py:136::quant_ledger_consistency_report`, `apps/stocks/management/commands/check_quant_consistency.py` | Le contrôle existe et compare réellement. Mais il est **« commande de management, jamais un job cron auto-enregistré »** (docstring, ligne 3) et rien ne le déclenche dans le dépôt : le « contrôle nocturne » du critère n'a pas d'ordonnanceur (§3.1). |
| STK-3 | Préparation sur lot à date limite : proposition FEFO systématique ; choix manuel différent motivé et journalisé | ✅ | `apps/stocks/services/moves.py`, `apps/stocks/models.py::StkLot`, `apps/core/audit_signals.py` | |
| STK-4 | Lot bloqué absent du disponible, de la proposition FEFO et des préparations, mais présent dans la valeur de stock | ✅ | `apps/stocks/models.py::StkQualityState`, `apps/stocks/services/public.py:942::set_quality_state`, `apps/stocks/services/expiry_alerts.py` (exclusion des lots `is_held()`) | |
| STK-5 | Transfert inter-dépôts interrompu : quantité en transit, ni au départ ni à l'arrivée, jamais perdue ni comptée deux fois | ✅ | `apps/stocks/services/moves.py:665-691` (emplacement de transit créé à la demande, **scopé à la destination** pour éviter qu'un même emplacement serve deux flux) | Le choix de scoper le transit à la destination est explicité et défendu dans le code. |
| STK-6 | Session d'inventaire à l'aveugle n'exposant la quantité attendue à aucun moment, y compris par appel direct de l'API | ❌ | `apps/stocks/services/inventory.py` (`create_inventory:113`, `start_inventory:163`, `record_count:176`), `apps/stocks/models.py::StkInventory` | Aucun mode aveugle : ni indicateur sur `StkInventory`, ni masquage de la quantité attendue dans le service ou l'API. Le comptage se fait à quantité attendue visible. |
| STK-7 | Écart supérieur au seuil de la famille non validable par celui qui a saisi le comptage ; tentative refusée et journalisée | ✅ | `apps/stocks/services/inventory.py:267-312` (garde de séparation, `log_action` sur la tentative), `validate_inventory:226` | La journalisation de la **tentative refusée** est explicitement traitée, pas seulement le refus. |
| STK-8 | Validation d'un écart produisant un mouvement de régularisation portant la référence de la session ; écart validé non modifiable | ✅ | `apps/stocks/services/inventory.py:226::validate_inventory`, `_resolve_variance_location:95`, `apps/stocks/migrations/0015_move_immutability.py` | |
| STK-9 | Réception de 30 lignes hors ligne, interrompue puis reprise : exactement 30 mouvements, sans doublon ni perte, dates d'effet conservées | ✅ | `apps/stocks/services/scan.py:87` (rejeu ignoré sur ligne déjà synchronisée), `apps/stocks/migrations/0016_stkmove_client_uuid.py`, `apps/stocks/tests/` | Même patron de déduplication que le POS (`client_uuid`). |
| STK-10 | Parcours de réception exécutable au scanner seul, retour visuel sous 300 ms quel que soit l'état du réseau | 🟡 | `templates/stocks/tw-scan.html`, `apps/stocks/services/scan.py` | L'écran scan-first existe et fonctionne hors ligne. Le seuil de **300 ms** n'est mesuré par aucun test. |
| STK-11 | Changement d'unité de stock après le premier mouvement refusé ; passage à la gestion par lot refusé si le stock n'est pas nul | ✅ | `apps/catalog/migrations/0013_catalog_guards_uom_and_lot_tracking.py`, `apps/catalog/services/public.py:60`, `apps/catalog/tests/test_structural_constraints.py` | Garde portée par la base, pas seulement par le service. |
| STK-12 | Valeur de stock à une date antérieure, rejouée depuis les mouvements, égale au solde du compte de stock comptable à l'ariary près | 🟡 | `apps/accounting/services/public.py:28,399`, `apps/stocks/module.py:18`, `apps/stocks/services/moves.py::validate_move` (écriture comptable sur tout mouvement), `apps/accounting/tests/test_public.py` | Le **câblage** qui rend l'égalité possible existe et est testé mouvement par mouvement (tout mouvement produit une écriture équilibrée). Mais aucune fonction de **rejeu à une date antérieure** ni aucun test comparant la valeur rejouée au solde comptable à cette date : l'égalité est une conséquence attendue de la conception, non une propriété vérifiée. |

#### Achats, import et CREDOC — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| ACH-1 | Demande au-dessus du seuil non convertible en commande sans approbation, y compris par appel direct de l'API | ✅ | `apps/purchase/services/requisitions.py`, `apps/core/services/approvals.py::decide` | Le contrôle est dans le service qu'emprunte l'API. |
| ACH-2 | Réception partielle laissant un reste exact ; somme des réceptions ne dépassant pas la commande au-delà de la tolérance | ✅ | `apps/purchase/services/receiving.py`, `apps/purchase/tests/test_acceptance.py` | |
| ACH-3 | Ligne en unité d'achat produisant un mouvement en unité de stock avec le facteur déclaré, conversion affichée avant validation | ✅ | `apps/purchase/services/receiving.py:41`, `apps/stocks/services/public.py:557::receive_purchase_line`, `apps/catalog/services/public.py:182,206`, `apps/catalog/tests/test_public.py:65` | C'est le câblage issu du sprint P2/B1 qui a refermé la double comptabilité de quantité. |
| ACH-4 | Cycle de vie du crédit documentaire refusant toute transition non prévue ; chaque transition datée, motivée, documentée quand l'état l'exige | ✅ | `apps/financing/` (`FinCredoc`, états non sautables, RUU 600), `apps/logistics/` | |
| ACH-5 | Dossier d'import restituant en un écran la chronologie complète avec pièces jointes, sans navigation ailleurs | ✅ | Chronologie unifiée du sprint B2, agrégeant `FinCredoc`, `LogShipment` et `LogCustomsFile` | |
| ACH-6 | Taux de change du dossier conservé à sa date de référence ; un recalcul ultérieur ne modifie ni le coût débarqué ni le CUMP historique | ✅ | `apps/purchase/tests/test_order_fx_variance.py` (sprint B3), `apps/accounting/services/currency.py` | |
| ACH-7 | Réception d'import non valorisable définitivement tant que les ventilations n'égalent pas leur total ; écart provisoire repris | ✅ | `apps/accounting/services/landed_costs.py` — `add_cost_component:112`, `finalize_batch:134`, `_recompute_total_purchase_value:78` | |
| ACH-8 | Rapprochement à trois voies bloquant le règlement au-delà de la tolérance et affichant l'écart ligne à ligne | ✅ | `apps/accounting/services/invoices.py:160,225` (sprints B4/B5) | |
| ACH-9 | L'utilisateur ayant validé une réception ne peut pas valider la facture correspondante ; tentative refusée et journalisée | ✅ | `apps/accounting/models.py::AccMove.received_by_ids`, `apps/accounting/services/invoices.py:234-249` (`log_action` **avant toute autre vérification**, fail-fast) | |
| ACH-10 | Coût débarqué unitaire restitué par le module analytique égal au coût du moteur de valorisation, à l'ariary près | 🟡 | `apps/accounting/services/landed_costs.py:176::landed_cost_report`, `apps/analytics/models.py::AnFactReception` | Les deux côtés existent et le moteur est câblé à la valorisation. Aucun test ne compare les deux restitutions à l'ariary près. |

#### Production — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| PRD-1 | Nomenclature à trois niveaux : quantités développées exactes, taux de perte inclus, nomenclature récursive signalée sans boucler | ✅ | `apps/mrp/services/bom.py`, `apps/mrp/services/analysis.py` (`find_shared_components`, `where_used`) | |
| PRD-2 | Consommation matière d'un style textile suivant la courbe de tailles déclarée et différant effectivement d'une taille à l'autre | ✅ | `apps/catalog/` (courbe de consommation calculée depuis la géométrie du patron, pas seulement déclarée), `apps/mrp/services/bom.py` | |
| PRD-3 | Lancement réservant les composants ; clôture ou annulation libérant intégralement les réservations restantes | ✅ | `apps/mrp/services/orders.py:79::reserve_order` → `stocks.services.public.check_and_reserve_stock`, `MrpOrderComponent.reservation_id` (migration `0009`) | |
| PRD-4 | Déclaration de production créant le lot fini et l'attachant aux lots consommés ; généalogie amont exacte | ✅ | `apps/mrp/services/transformation.py:41,106` → `stocks.services.public.receive_production_output`, `apps/stocks/models.py::StkLotGenealogy`, `apps/catalog/services/public.py:420` | |
| PRD-5 | Déplacement d'une carte kanban changeant l'état, journalisé au chatter avec son auteur, fonctionnant sur tablette en réseau dégradé | 🟡 | `templates/mrp/kanban.html`, `apps/mrp/tests/test_kanban.py` (sprint C6), `templates/mrp/detail.html:396` (chatter) | Le kanban avec glisser-déposer et le chatter existent tous les deux sur `mrp`. Le fonctionnement **sur tablette en réseau dégradé** n'est vérifié par aucun test. |
| PRD-6 | Taux de conformité au premier passage calculé depuis les déclarations réelles, non saisi, recalculable à l'identique depuis les mouvements | 🟡 | `apps/mrp/services/reports.py:167` (`qty_done / (qty_done + qty_rejected)` par poste) | Le taux est bien **calculé** et jamais saisi. Mais il est calculé sur les déclarations de poste, et rien ne démontre qu'il soit recalculable à l'identique depuis les mouvements de stock. |
| PRD-7 | Nomenclature de process : écart matière engagée / produits + sous-produits + rebuts au-delà de la tolérance déclenchant alerte et motif à la clôture | ✅ | `apps/mrp/migrations/0011_mrpbom_by_products_mrpbom_expected_yield_pct_and_more.py` (sprint C5), `apps/mrp/services/orders.py::close_order`, `apps/stocks/services/consistency.py:84::production_consistency_report` | |
| PRD-8 | Matière sortie vers un façonnier restant dans la valeur de stock, en emplacement de sous-traitance, absente du disponible du dépôt | ✅ | `apps/stocks/services/public.py:701::send_to_subcontractor`, `:776::receive_from_subcontractor`, `apps/mrp/migrations/0010_*` (`send_move_id`/`receive_move_id`) | |
| PRD-9 | Coût réel d'un ordre clôturé égal à la somme des consommations au CUMP à leur date d'effet, main-d'œuvre et sous-traitance, à l'ariary près | 🟡 | `apps/mrp/services/orders.py` (`compute_planned_cost` à la réservation, `compute_real_cost` à `close_order`), migrations `0004`/`0012` (`cost_labor_planned_mga`, `cost_subcontracting_mga`), `apps/stocks/services/moves.py:314::_consume_average_cost` | Les trois composantes sont calculées et le CUMP est réel. Aucun test ne vérifie l'égalité à l'ariary près avec la somme rejouée. |
| PRD-10 | Ordre clôturé refusant toute déclaration ultérieure, y compris par appel direct de l'API | ✅ | `apps/mrp/services/orders.py::record_component_consumption` (garde d'état, sprint C4) | |

#### Qualité et HACCP — 10 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| QUA-1 | Mesure hors limite critique sur un point critique bloquant le lot dans la même transaction, sans intervention humaine | ✅ | `apps/quality/services/measurements.py` → `stocks.services.public.set_quality_state(BLOCKED)` dans la même transaction (sprint D1) | |
| QUA-2 | Libération d'un lot concerné par une non-conformité ouverte refusée, avec désignation de la non-conformité bloquante | ✅ | `apps/quality/services/non_conformity.py`, `apps/quality/services/public.py` | |
| QUA-3 | Décision de blocage ou libération portant identité, horodatage serveur et motif ; antidatage refusé ; journal d'audit | ✅ | `apps/quality/services/non_conformity.py`, `apps/core/audit_signals.py::_on_save` | |
| QUA-4 | À partir d'un lot suspect, lots finis et clients impactés restitués en moins de 5 s sur trois exercices | ✅ | `apps/quality/tests/test_recall_performance.py:26,62-83` (`RECALL_PERFORMANCE_THRESHOLD_SECONDS = 5`, mesure réelle de `declare_recall` de bout en bout sur un arbre représentatif) | C'est l'un des rares critères de performance réellement **mesuré** par un test plutôt que supposé. |
| QUA-5 | Généalogie amont remontant aux lots fournisseurs à travers tous les niveaux, résultat identique au recalcul depuis les mouvements | ✅ | `apps/stocks/services/public.py:918::lot_genealogy_tree`, `apps/stocks/models.py::StkLotGenealogy` (généalogie bidirectionnelle) | Le dossier de rappel **réutilise** cette fonction plutôt que de recalculer, ce qui rend l'identité structurelle. |
| QUA-6 | Dossier de rappel rouvert un an plus tard affichant exactement les mêmes lots, clients, quantités et décisions | ✅ | `apps/quality/migrations/0003_recall_dossier_immutability.py` (trigger PostgreSQL), `apps/quality/models.py::QltRecallDossier` | |
| QUA-7 | Journal de rappel en ajout seul : aucune voie applicative ne permet de modifier, réordonner ou supprimer un événement | ✅ | `apps/quality/migrations/0003_recall_dossier_immutability.py` | Garantie par la base, donc opposable à toute voie applicative. |
| QUA-8 | Lot reçu sans certificat d'analyse valide, sur un article qui l'exige, bloqué automatiquement à la réception | ✅ | `apps/catalog/models.py:184` (`requires_certificate_of_analysis`), `apps/stocks/services/public.py:650-679` (refus dans `receive_purchase_line`), `apps/quality/tests/test_certificate_status.py`, `apps/catalog/tests/test_certificate_of_analysis.py` | |
| QUA-9 | Contrôle dû et non réalisé apparaissant en retard et déclenchant une alerte ; ne disparaît pas avec le temps | 🟡 | `apps/quality/services/alerts.py::check_overdue_controls`, `apps/quality/management/commands/run_quality_control_checks.py` | La détection existe et est correcte. Deux réserves : la commande n'est **déclenchée par rien** (§3.1), et `apps/quality` **n'a aucun écran** — « la liste des contrôles » où le retard doit apparaître n'existe pas (voir §3.4). |
| QUA-10 | Exercice de rappel blanc sur données de production anonymisées, vérifié par le contrôleur qualité du client | N/A | — | Non couvrable par du code : exige un exercice réel avec un tiers. |

#### Paie — 12 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| P3/PAY-1 | Test de CI échouant si une valeur réglementaire (taux, tranche, plafond) est trouvée en dur dans le moteur de paie | 🟡 | `tests/architecture/test_no_hardcoded_payroll_rates.py`, `apps/payroll/services/seed.py` (10 codes semés : `irsa_brackets`, `cnaps_rate`, `ostie_rate`, `fmfp_rate`, `overtime_multipliers`…) | Le test existe, il est bloquant, et `DEFAULT_OVERTIME_MULTIPLIERS` a bien été supprimé (sprint E1). Mais sa portée réelle est **limitée aux littéraux chaîne de forme `N.NN`** : les **montants** (`"300000"` pour l'IRSA minimum, le SME) et les **bornes de tranches** ne sont pas détectés. Le critère nomme pourtant « taux, tranche, plafond ». |
| P3/PAY-2 | Calcul utilisant la version du paramètre en vigueur à la date du bulletin ; recalcul d'un mois antérieur redonnant le même résultat | ✅ | `apps/payroll/services/params.py` (`at_date` **obligatoire, sans valeur par défaut**) → `core.services.regulatory.get_parameter_with_version`, `apps/core/migrations/0009_regulatory_parameter_no_overlap.py` | L'absence de défaut sur `at_date` est ce qui rend l'erreur impossible plutôt qu'improbable. |
| P3/PAY-3 | Cycle utilisant un paramètre non validé non publiable ; l'écran désigne le paramètre concerné | ✅ | `apps/payroll/services/batches.py:130-150::validate_and_post_batch` → `core.services.regulatory_governance.unvalidated_active_parameters()` (sprint P4) | |
| P3/PAY-4 | Chaque ligne de bulletin dépliable sur base, taux, identifiant du paramètre et version ; aucune ligne sans cette traçabilité | ✅ | `apps/payroll/migrations/0003_paypayslipline_regulatory_parameter_versions.py` (sprint E3), `apps/payroll/models.py::PayPayslipLine` | |
| P3/PAY-5 | Ajout d'une rubrique et mise en service sans modification de code, vérifié de bout en bout sur un salarié témoin | ✅ | `apps/payroll/views.py:105::rubric_simulation` (route `payroll:simulation`, gabarit `payroll/rubric_simulation.html`), `apps/payroll/services/payslip.py::simulate_payslip`, `apps/payroll/tests/test_rubric_simulation_view.py` (sprint E4) | La simulation tourne sur un **contrat réel** et une période réelle, sans aucune persistance, et chaque appel déclenche `log_pii_access`. |
| P3/PAY-6 | Avenant créant une version datée du contrat ; bulletin antérieur calculé sur la version en vigueur à cette date | ✅ | `apps/payroll/services/contracts.py::create_amendment`, `apps/payroll/tests/test_amend_contract_api.py` (sprint E5) | |
| P3/PAY-7 | Variation de net au-delà du seuil bloquant la publication tant que l'anomalie n'est pas visée avec un motif | ✅ | `apps/payroll/migrations/0004_paybatch_anomaly_acknowledgments.py`, `apps/payroll/tests/test_anomaly_acknowledgment.py` (sprint E6) | L'acquittement est **par anomalie** et motivé, pas un acquittement global du cycle. |
| P3/PAY-8 | Bulletin publié refusant toute modification et suppression, y compris par l'API et pour un administrateur | ✅ | `apps/payroll/migrations/0005_payslip_immutability.py` (sprint E9) | Deux triggers PostgreSQL `BEFORE UPDATE OR DELETE`, 21 champs métier protégés nommément, seule transition tolérée `approved → paid`. Les **lignes** sont protégées par sous-requête sur l'état du bulletin parent — ce qui ferme le trou concret où `compute_payslip` supprimait les lignes sans vérifier l'état. |
| P3/PAY-9 | Correction après publication produisant une régularisation datée, motivée, rattachée au bulletin d'origine, visible sur le cycle suivant | 🟡 | `apps/payroll/services/regularization.py::create_regularization` (seul point d'entrée renseignant `PayPayslip.rectifies`), `apps/payroll/views.py::regularization_screen`, `apps/payroll/tests/test_regularization.py` (sprint E7) | Tout ce que le critère énonce est tenu. La réserve est **assumée et disclosée dans le code** : la régularisation est une recopie et un recalcul complets, **pas un calcul de delta** — le rapprochement avec ce qui a déjà été payé reste à la charge du gestionnaire. |
| P3/PAY-10 | Journal de paie d'un cycle publié se déversant en une écriture équilibrée, somme des rubriques égale au total à l'ariary près | 🟡 | `apps/payroll/services/batches.py:13,124` (appel à `apps.accounting.services.public`) | Le déversement comptable est câblé. Aucun test comparant la somme des rubriques au total du journal à l'ariary près n'a été trouvé. |
| P3/PAY-11 | Aucun montant de rémunération individuel hors rôle Paie, y compris par rapport, export, tableau de bord ou copilote ; testé rôle par rôle | ✅ | `apps/payroll/tests/test_rbac_full_matrix.py` (394 lignes, **19 endpoints × 13 rôles**, `EXPECTED_PAYROLL_ACTIONS` en pin littéral jamais réimporté de `rbac_policy`), `apps/ai/services/natural_language_search.py` (`payroll` retiré de la liste blanche, décision D6), `apps/reporting/services/scheduling.py` (export planifié recloisonné, sprint P5), `apps/core/services/permissions.py::SENSITIVE_FIELDS` | Les quatre voies nommées par le critère sont couvertes, et les deux fuites de l'audit précédent sont en régression testée. Portée déclarée du test : la porte d'accès (403 / pas-403), pas le succès métier complet. |
| P3/PAY-12 | Jeu de bulletins témoins couvrant les cas limites, signé par un expert-comptable | N/A | — | Non couvrable par du code : exige la signature d'un tiers agréé. |

#### Extension Forecast — 5 critères

| Réf. | Critère (abrégé) | Verdict | Preuve | Écart constaté |
|---|---|---|---|---|
| FOR-11 | Calcul de besoins s'exécutant sur le modèle dimensionnel de la Phase 2 étendu, sans modifier les dimensions conformes existantes | ✅ | `apps/analytics/models.py::AnFactMouvementStock`, `AnFactReception`, `AnFactOrdreFabrication`, `AnFactPaie` (sprints T1–T4), `apps/analytics/services/refresh.py` | Les quatre faits de la Phase 3 ont été ajoutés sans toucher `AnDimTemps`/`AnDimTiers`/`AnDimArticle` : la condition « accueillir sans reprise », posée mais jamais éprouvée à l'audit précédent, est désormais **démontrée par un ajout réel**. Réserve : `AnFactPaie` n'est pas déclaré dans `fact_specs.py::FACT_SPECS`, donc non interrogeable par BI (voir BI-1). |
| FOR-12 | Proposition de réapprovisionnement dépliable sur sa justification complète (besoin, nomenclature, stock et en-cours déduits, règle appliquée) | ✅ | `apps/purchase/models.py::PurReorderingProposal` (instantané figé : `qty_proposed`, `available_stock`, `on_order_qty`), `apps/forecast/services/material_needs.py` (sprint F1/F2) | L'instantané est figé à la création : la justification reste lisible même si le stock bouge ensuite. |
| FOR-13 | Proposition rejetée exigeant un motif conservé et restituable ; taux d'acceptation mesuré et affiché | ✅ | `apps/purchase/services/reordering.py:45` (`RULE_NAME = "purchase.reordering.proposal_acceptance"`), `:184-224` (motif **obligatoire**, `rejection_reason` persisté) | Le code cite le critère et sa raison d'être : « FOR-13 exige un rejet explicite, pas un simple silence ». |
| FOR-14 | Charge d'atelier projetée confrontée au réalisé sur les périodes échues, erreur publiée selon le même protocole de rétrotest que les ventes | ✅ | `apps/forecast/services/workload_forecast.py` (217 lignes, stateless, réutilise le même rétrotest), `apps/mrp/services/public.py:471,580` (`list_planned_orders_workload`, `get_workshop_realized_hours_series`) | Limitation assumée : le grain est l'**atelier** (`MrpWorkshop`), pas le poste de charge, parce que `MrpCra` ne porte qu'un atelier. |
| FOR-15 | Alerte de péremption déclenchée quand la date limite précède la date d'écoulement prévue, disparaissant quand le lot est écoulé ou bloqué | 🟡 | `apps/stocks/services/expiry_alerts.py` (`EXPIRY_ALERT_THRESHOLD_DAYS = 30`, exclusion des lots `is_held()`), `apps/stocks/management/commands/run_expiry_alerts.py` (sprint F4) | La logique est correcte, y compris la disparition sur lot bloqué. Deux réserves : **aucune déduplication entre exécutions** (assumée et disclosée), et la commande n'est déclenchée par rien (§3.1). |

### 2.4 Phase 4 — Connectivité, flux et écosystème tiers (54 critères)

**La Phase 4 n'a jamais été engagée.** Il n'existe aucun socle de flux : pas de
catalogue de connecteurs, pas de liaison, pas de correspondance de champs, pas de
registre d'échange, pas de charge utile, pas d'incident, pas de disjoncteur, pas de
consentement de sortie. L'intérêt de cette section n'est donc pas le verdict — il est
connu d'avance — mais **l'inventaire de ce qui est déjà là et qu'il ne faudra pas
reconstruire**, et **l'identification des critères déjà partiellement tenus par des
briques antérieures**, qui coûteront moins cher que les autres.

Ce qui est réutilisable, vérifié :

| Brique existante | Emplacement | Ce qu'elle sert en Phase 4 |
|---|---|---|
| Surface REST versionnée + OpenAPI publié | `config/api.py` (`NinjaAPI(version="v1", auth=JWTAuth())`, 37 routeurs), `/api/v1/openapi.json`, `/api/v1/docs` | Base de F2. django-ninja, pas DRF. |
| Tests de contrat OpenAPI | `tests/contract/test_openapi_schemathesis.py` (306 lignes) | Le jeu de tests de conformité exigé par le bloc B existe déjà en germe. |
| Gouvernance d'endpoints + garde CI | `apps/core/services/endpoint_governance.py` (`INTENTIONALLY_OPEN_ENDPOINTS`, 20 entrées motivées), `tests/architecture/test_endpoint_permissions.py` | Patron exact de la liste blanche publique d'API-2. |
| Idempotence | `apps/core/idempotency.py` (`@idempotent`, en-tête `Idempotency-Key`, hash du corps, rejeu de la réponse, TTL 24 h), `core.IdempotencyKey` | FLX-4, API-4, P4/PAY-4. **Appliqué à un seul endpoint** (`apps/core/api_meta.py:24`), décrit comme motif de référence à réutiliser. |
| Limitation de débit | `apps/core/throttling.py` (`@throttle`, compteur Redis, 429 `ProblemDetail`) | API-7. **Appliqué à aucun endpoint** : le seul usage est un test. |
| File asynchrone à point d'entrée unique | `apps/core/tasks.py::enqueue`, garde `tests/architecture/test_no_direct_task_queue_usage.py` | File de sortie du bloc A, sans introduire de composant nouveau. |
| Signature HMAC de webhook entrant | `apps/logistics/services/webhooks.py::verify_carrier_webhook_signature` (`hmac.compare_digest`, **refuse par défaut** si aucun secret) | Patron d'API-3. |
| Bus d'événements + automatisation | `apps/core/events.py` (`PUBLISHED_EVENT_TYPES`, 22 types), `apps/automation/` (`AutoFlow`/`AutoStep`/`AutoRun`, registre d'actions whitelistées) | Déclencheurs événementiels (mode « événementiel » de §4.2). |
| Multi-tenant à sécurité au niveau des lignes | `apps/core/middleware.py::TenantMiddleware`, `apps/core/management/commands/apply_rls.py` | FLX-7. |
| Journal d'audit immuable | `apps/core/models/audit.py`, `apps/core/migrations/0010_audit_log_immutable.py` | Précédent direct du registre d'échange. |
| Chiffrement de champ | `apps/core/db/fields.py::EncryptedCharField` | Identifiants d'accès des connecteurs. |

Ce qui n'a **aucun précédent** dans le dépôt : disjoncteur (zéro occurrence),
webhooks **sortants** (aucun modèle d'abonnement, aucune signature sortante, aucune
file de livraison), clés d'API avec portées et quotas (aucun modèle `ApiKey` —
l'authentification est exclusivement JWT), registre d'échange, machine à états
d'échange, e-facture (zéro occurrence de Factur-X, UBL, PEPPOL), commerce en ligne
(zéro occurrence de WooCommerce, Shopify, PrestaShop, Magento), stockage cloud actif
(`django-storages` est installé mais `STORAGES["default"]` reste `FileSystemStorage`),
calendrier externe, OCR.

| Réf. | Critère (abrégé) | Verdict | Preuve / brique la plus proche |
|---|---|---|---|
| FLX-1 | Test CI sur l'appel réseau hors exécuteur du hub et l'échange sans empreinte | ❌ | Aucun hub. Patron disponible : `tests/architecture/test_no_direct_task_queue_usage.py`. Les 4 seuls appels HTTP sortants du dépôt sont `purchase/services/price_watch.py:156`, `core/services/whatsapp.py:54`, `core/services/ai_assistant.py:175,221`. |
| FLX-2 | Échec de tiers sur déclencheur événementiel n'empêchant pas la transition métier | 🟡 | `apps/automation/services/dispatch.py:34,56` — le déclenchement est déjà **toujours** mis en file, jamais synchrone, et un échec d'action laisse `AutoRun.status = "partial"` sans arrêter le flux. Le principe est donc déjà tenu par l'automatisation ; il n'existe simplement aucun échange à mettre en file. |
| FLX-3 | Disjoncteur après N échecs, file sans appel réseau, incident unique | ❌ | Aucun disjoncteur dans le dépôt. Réessai existant : `apps/automation/services/engine.py` (`MAX_ATTEMPTS = 3`, `BACKOFF_SECONDS = (1, 4, 16)`). |
| FLX-4 | Rejeu transmettant la même clé d'idempotence, sans doublon chez le tiers | 🟡 | `apps/core/idempotency.py` + `core.IdempotencyKey` : le mécanisme existe, mais **entrant** (protection de nos endpoints) et non **sortant**, et il n'est branché que sur `apps/core/api_meta.py:24`. |
| FLX-5 | Purge de la charge utile laissant échange, empreinte, horodatage et verdict intacts | ❌ | Aucune charge utile, aucun échange. |
| FLX-6 | Correspondance de champs incomplète refusée à l'enregistrement, champ manquant désigné | ❌ | Aucune correspondance de champs. |
| FLX-7 | Test d'isolation à deux tenants sur échanges, secrets, liaisons et charges utiles | 🟡 | L'isolation elle-même est acquise et structurelle (`TenantMiddleware` + `SET LOCAL app.tenant_id` + `FORCE ROW LEVEL SECURITY`), mais aucun des objets nommés par le critère n'existe. À noter, une dérogation à surveiller : le webhook transporteur résout `LogServiceProvider.all_objects` (manager **non filtré**) faute de contexte tenant. |
| FLX-8 | Aucun motif ressemblant à un secret dans un journal, une charge utile ou un message d'erreur | ❌ | Aucun mécanisme de rédaction de secret. **Écart aggravant existant** : `apps/logistics/models.py:368` stocke `LogServiceProvider.webhook_secret` en `CharField` **non chiffré**, alors que `EncryptedCharField` existe et est utilisé pour `PrsEmployee.cin` et `PrsAbsence.reason`. |
| API-1 | Jeton client n'obtenant rien qu'un utilisateur du rôle correspondant ne verrait | ❌ | Aucune notion de jeton client : recherche exhaustive sur `ApiKey`/`api_key`/`access_token` dans `apps/core/models/` → zéro résultat. Le modèle de droits à réutiliser est `apps/core/services/rbac_policy.py` (13 rôles) + `scoping.py`. |
| API-2 | Aucune opération hors liste blanche publique atteignable par un jeton client | 🟡 | Le patron existe et est **déjà bloquant en CI** pour la surface interne (`endpoint_governance.py` + `tests/architecture/test_endpoint_permissions.py`, 539 décorations `@require_permission` comptées). Il manque la déclaration d'une surface **publique** distincte et son plafond de 80 opérations. |
| API-3 | Webhook non signé, mal signé ou hors fenêtre rejeté sans traitement et journalisé sans révéler le motif | 🟡 | `apps/logistics/services/webhooks.py` fait déjà la signature HMAC et **refuse par défaut** en l'absence de secret. Manquent la fenêtre d'horodatage et la généralisation ; les deux autres points d'entrée (`apps/whatsapp/api.py:209,221`, `apps/core/api_notifications.py`) n'ont qu'un jeton de vérification. |
| API-4 | Événement reçu deux fois : un seul traitement, deux lignes de registre dont la seconde marquée doublon | ❌ | Aucun registre. `core.IdempotencyKey` est indexé sur `(tenant_id, user_id, key)` : inutilisable tel quel pour un appelant `auth=None`. |
| API-5 | Accusé de réception du webhook en moins de 500 ms, traitement différé en file | 🟡 | La file existe (`core/tasks.py::enqueue`) mais **le webhook transporteur ne matérialise aucun traitement** : signature validée puis `return {"status": "ok"}`, sans persistance de charge utile ni transition d'état — déviation documentée dans le code. |
| API-6 | Révocation d'une clé effective immédiatement, y compris pour les appels en cours d'authentification | ❌ | Aucune clé. Précédent utile : la liste noire de jetons de rafraîchissement de django-ninja-jwt. |
| API-7 | Dépassement de débit produisant une réponse normalisée avec délai d'attente, sans affecter les autres clés ni tenants | 🟡 | `apps/core/throttling.py` produit déjà un 429 `ProblemDetail` normalisé, avec compteur Redis. Mais il **n'est appliqué à aucun endpoint** (seul usage : `apps/core/tests/test_api_conventions.py:110`) et ne connaît ni clé ni tenant. |
| EFA-1 à EFA-8 | Conformité e-facture et clearance (8 critères) | ❌ | Aucune brique. Zéro occurrence de Factur-X, UBL, PEPPOL, e-invoice dans le dépôt. `apps/accounting/services/fiscal_export.py`, `dcom.py` et `tax_returns.py` couvrent les **déclarations** fiscales malgaches, pas un format d'échange normalisé ni un dispositif à contrôle continu. Le paramétrage par pays exigé par EFA-7 a en revanche son support tout prêt : `core_regulatory_parameter` (versionné, daté, avec statut de validation). |
| P4/PAY-1 | Bascule agrégateur ↔ raccordement direct par paramètre, sans reprise des intentions en cours | ❌ | Aucune interface de service d'encaissement, aucune implémentation. |
| P4/PAY-2 | Notification de paiement rapprochée automatiquement et produisant l'écriture d'encaissement | 🟡 | `apps/accounting/services/mobile_money.py` — `import_mobile_money_statement:35`, `reconcile_mobile_money_line:83`, `unmatched_mobile_money_lines:99`, modèle `AccMobileMoneyStatementLine`. Le rapprochement existe donc, mais **à partir d'un import CSV manuel** : aucun connecteur d'opérateur, aucune notification entrante. Le format CSV est explicitement décrit comme générique et « pas la spécification d'un export réel Mvola/Orange Money/Airtel Money ». |
| P4/PAY-3 | Paiement sans correspondance en attente, visible dans un écran dédié, sans écriture | 🟡 | `unmatched_mobile_money_lines` fournit exactement la liste ; la règle « aucune écriture tant que non affecté » est tenue par construction. L'écran dédié n'a pas été retrouvé. |
| P4/PAY-4 | Double notification produisant un seul encaissement et une seule écriture | ❌ | Aucune notification entrante. `core.IdempotencyKey` est le patron le plus proche. |
| P4/PAY-5 | Versement groupé rapproché du lot d'encaissements, commission isolée sur son compte de charge | ❌ | Aucun rapprochement de second niveau. |
| P4/PAY-6 | Montant partiel produisant un encaissement partiel, pièce laissée ouverte, sans lettrage forcé | 🟡 | `apps/accounting/services/payments.py` (`allocated_amount:37`, `outstanding_balance:42`, `register_payment:46`) gère déjà l'imputation partielle sans forcer le lettrage — la règle métier est acquise, la source d'événement manque. |
| P4/PAY-7 | Rejeu d'une intention vérifiant l'état auprès du tiers avant réémission ; aucun double débit | ❌ | Aucune intention de règlement. |
| P4/PAY-8 | Taux de rapprochement automatique calculé, publié comme indicateur gouverné, consultable par période et connecteur | ❌ | Le dictionnaire gouverné existe (`AnMetricDefinition`) mais n'est peuplé nulle part (voir BI-1) ; aucun indicateur de rapprochement. |
| BNK-1 | Rechargement d'un relevé déjà importé ne créant aucun doublon et le signalant | ❌ | `apps/accounting/services/bank_reconciliation.py:54::import_bank_statement` ne comporte aucune détection de période déjà chargée ni de ligne en doublon. |
| BNK-2 | Ligne en anomalie n'interrompant pas le lot, isolée dans un rapport de chargement | ❌ | Même fonction : aucun rapport de chargement, aucune isolation de ligne fautive. |
| BNK-3 | Propositions horodatées avec niveau de confiance ; aucune écriture sans validation | 🟡 | `suggest_matches:159`, `confirm_reconciliation:204`, `manual_match:226` — le moteur **propose** et ne poste rien, ce qui est exactement l'interdit de la §4.4 du cahier. Manquent l'horodatage des propositions et le niveau de confiance. |
| BNK-4 | Ordre de virement rattaché aux pièces qu'il règle, état de remise suivi jusqu'au débit | ❌ | `apps/payroll/services/mobile_money.py:18::generate_mobile_money_transfer_file` et `:44::generate_bank_transfer_file` produisent un fichier ; aucun rattachement aux pièces, aucun suivi d'état de remise. |
| BNK-5 | Ordre de virement de paie n'exposant que bénéficiaire, montant et référence ; test sur le fichier produit | 🟡 | `apps/payroll/services/mobile_money.py:15` — `MOBILE_MONEY_FIELDNAMES = ["employee_id", "reference", "phone", "amount_mga", "label"]` : **aucune donnée de rubrique** n'y figure, l'esprit du critère est tenu. Deux réserves : le fichier expose en outre l'identifiant salarié et le numéro de téléphone, et aucun test ne vérifie le contenu produit. |
| BUR-1 à BUR-5 | Bureautique, stockage et calendrier (5 critères) | ❌ | Aucun adaptateur de suite bureautique. Ce qui existe et sera réutilisé : `core.Document` passe systématiquement par l'API `Storage` abstraite « pour permettre une bascule future vers S3/Hetzner Object Storage sans changement de code » (BUR-4), et `SENSITIVE_FIELDS` (`apps/core/services/permissions.py:27`) est le registre à consulter pour BUR-5. Aucun connecteur Google Drive/OneDrive/Dropbox, aucun iCal/CalDAV, envoi de courriel en SMTP seulement (`config/settings/prod.py:59`). |
| COM-1 | Commande ingérée créant un document au statut initial, sans facture, mouvement ni écriture | ❌ | Aucun connecteur de commerce. À noter : l'interdit correspondant est **déjà respecté ailleurs** — `apps/automation/services/` n'expose que des actions whitelistées, jamais une transition générique. |
| COM-2 | Article de boutique sans correspondance plaçant la commande en anomalie sans bloquer les autres | ❌ | Aucune table de correspondance d'articles externes. |
| COM-3 | Publication de disponibilité reflétant le stock **disponible à la vente**, réservations déduites | 🟡 | La notion existe et est juste côté Phase 3 : `apps/stocks/services/public.py:113::check_and_reserve_stock`, `StkReservation`. Il n'y a rien qui la publie. |
| COM-4 | Commande reçue en double, identifiée par sa référence de boutique, ne créant qu'un document | ❌ | Aucune ingestion. Patron disponible : `client_uuid` du POS et du scan stock. |
| MSG-1 | Coût imputé au message délivré selon la grille paramétrée ; aucun tarif dans le code | 🟡 | `apps/whatsapp/models.py::WaMessageTemplate.estimated_cost_ariary` + `apps/whatsapp/services/usage.py` : aucun tarif n'est en dur, la grille vit en base. Mais le coût est **estimé au modèle de message**, pas imputé **au message délivré**, et le coût réellement facturé par Meta n'est jamais récupéré (disclosé dans la docstring du modèle). |
| MSG-2 | Historiques antérieurs à la bascule lisibles dans leur unité d'origine, date de changement visible | ❌ | Aucune bascule d'unité de coût n'a été préparée. |
| MSG-3 | Indisponibilité du canal ne bloquant aucun processus ; courriel disponible en repli | ✅ | `apps/core/services/whatsapp.py::get_whatsapp_client` (`StubWhatsAppClient` par défaut, `WHATSAPP_ENABLED=false`), `apps/core/services/notifications.py` (canal courriel SMTP indépendant). C'est le seul critère de la Phase 4 déjà pleinement tenu, parce qu'il porte sur une propriété héritée de la Phase 2. |
| CON-1 | Depuis toute pièce, état de ses échanges en un clic, et réciproquement depuis le journal | ❌ | Aucun registre d'échange. |
| CON-2 | Activation d'un connecteur exigeant un consentement affichant catégories, tiers, pays et durée ; décision journalisée | ❌ | Aucun consentement de sortie. Le consentement **destinataire** de WhatsApp (`WaConversation.consent_*`) est un objet différent, mais son patron (immuable, révocation par nouvel enregistrement) est directement transposable. |
| CON-3 | Révocation coupant le connecteur immédiatement, conservant les échanges, proposant la purge des charges utiles | ❌ | — |
| CON-4 | Panneau de rejeu affichant volume et coût estimé avant confirmation | ❌ | — |
| CON-5 | Alerte à l'approche d'un plafond, avant son atteinte, au destinataire configuré | 🟡 | `apps/core/models/tenant.py` (`whatsapp_cost_alert_threshold_pct`, `whatsapp_cost_cap_hard_stop`) et `apps/whatsapp/services/usage.py` implémentent déjà exactement ce comportement — pour un seul connecteur. La généralisation est un élargissement, pas une construction. |
| CON-6 | Export de garantie de sortie : liaisons, échanges, verdicts et rapprochements, format documenté relisible sans WideHalo | 🟡 | `apps/core/services/tenant_export.py` existe et exporte déjà un tenant entier. Il ne connaît évidemment aucun objet de flux. |

---

## 3. Écarts transverses, hors grille de critères

Ces sept points ne sont rattachables à aucun critère en particulier. Deux d'entre eux
pèsent plus lourd que la majorité des critères pris isolément.

### 3.1 L'ordonnancement n'est câblé nulle part

**Cinquante et une commandes de gestion** existent dans le dépôt
(`find widehalo -path "*/management/commands/*.py" ! -name "__init__.py" | wc -l` →
51). Plusieurs sont le point d'exécution unique d'une exigence des cahiers :
`run_analytics_refresh` (rafraîchissement de l'entrepôt), `run_bi_diffusions`
(BI-7), `run_report_schedules`, `run_expiry_alerts` (FOR-15),
`run_quality_control_checks` (QUA-9), `run_purchase_reordering`,
`check_quant_consistency` (STK-2), `expire_stock_reservations`,
`run_presence_maintenance`.

**Rien ne les déclenche.** Vérifié : aucune référence à ces commandes en dehors de
fichiers `.py` — ni crontab, ni unité systemd, ni service dans
`docker-compose.prod.yml` (qui ne lance que `web` et `worker: python manage.py
qcluster`), ni objet `Schedule` de django-q2 enregistré au démarrage. Les docstrings
l'assument : *« aucun mecanisme de cron n'est cable ailleurs dans le projet pour ce
type de tache, donc aucun n'est invente ici »*
(`apps/quality/management/commands/run_quality_control_checks.py`), et
`apps/stocks/services/consistency.py:3` précise « commande de management, jamais un
job cron auto-enregistré ».

Conséquence en exploitation, et elle est en chaîne : l'entrepôt analytique n'est
jamais rafraîchi → `AnFactVente` et les sept autres faits restent vides → **les
modules BI, Forecast et Strategy de la Phase 2 restituent des tableaux vides**,
indépendamment de la qualité de leur code. Le contrôle nocturne de cohérence des
quants (STK-2) et l'alerte de péremption (FOR-15) ne se déclenchent jamais. C'est
l'écart le plus lourd de cet audit, et le moins visible : chaque module pris isolément
passe ses tests.

Un seul composant manque, et il ne demande aucune infrastructure nouvelle : le
`qcluster` tourne déjà en production, et django-q2 sait enregistrer des planifications
récurrentes.

### 3.2 Budgets d'architecture — le plafond d'écrans est saturé

`widehalo/config/settings/base.py:412-414` : `BUDGET_MAX_MODELS = 310`,
`BUDGET_MAX_ENDPOINTS = 600`, `BUDGET_MAX_SCREENS = 240`, vérifiés en CI par
`tests/architecture/test_budget.py` (job `architecture-tests`, bloquant).

**La mesure officielle n'a pas pu être ré-exécutée dans cet audit** : Django n'est pas
installé dans l'environnement (`ModuleNotFoundError: No module named 'django'`), et le
compteur qui fait foi passe par le registre d'applications Django. Conformément à la
règle du `README.md` — *« ne jamais se fier à un chiffre de documentation sans le
re-vérifier »* — le chiffre n'est donc pas repris d'un autre document. Une mesure
**statique** (analyse syntaxique, réimplémentation exacte de `_counted_screens`) donne
un ordre de grandeur : ≈ 300 modèles, 576 endpoints, et **240 écrans — soit le plafond
atteint exactement**. À confirmer par ré-exécution réelle : ❓.

Ce que cela implique concrètement : le test d'écran passe aujourd'hui **uniquement
parce que l'assertion est `<=`**. Le prochain gabarit ajouté fait échouer la
construction — et plusieurs écarts relevés ci-dessus en exigent un (gabarit
d'impression du ticket POS pour POS-3, écran de la liste des contrôles qualité pour
QUA-9, écran des paiements en attente pour P4/PAY-3). **Tout plan de rattrapage
commence donc par un relèvement explicite de ce plafond**, sur le patron des six
relèvements précédents, tous commentés et justifiés dans `base.py:352-412`.

Pour mémoire, les cibles de la Phase 4 : 430 modèles / 1 210 endpoints / 278 écrans,
plus deux budgets nouveaux (12 adaptateurs, 80 opérations publiques).

### 3.3 Dérive documentaire — trois documents affirment un état faux

| Document | Ce qu'il affirme | État réel |
|---|---|---|
| `README.md` | Plafonds « 290 modèles / 569 endpoints / 238 écrans, contre un plafond CI de 290/600/240 » | Le plafond de modèles est passé à **310** (`base.py:412`, relevé pour le Bloc D Qualité). |
| `README.md` | Phase 3 : « **8 des 59 critères d'acceptation sont conformes, 27 partiels, 21 absents** », avec les deux violations structurelles | 44 conformes, et les deux violations sont refermées (§2.3). |
| `README.md` | Liste des modules sous `widehalo/apps/` | Omet `automation`, `chat`, `quality`, `patronage`. |
| `CONTRIBUTING.md` | « `test_budget.py` fait échouer la CI si le nombre de modèles/endpoints/écrans dépasse les plafonds V1 (**180/600/90**) » | Chiffres périmés de trois relèvements. |
| `docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md` | « plan **prospectif**, non encore exécuté » | Intégralement exécuté, 34 sprints sur 34. |

S'y ajoutent deux **docstrings périmées**, exactement la classe de dérive que le
sprint P7 visait à traiter : `apps/stocks/services/consistency.py:53` affirme encore
qu'« une INTÉGRATION future `mrp` → `stocks` » reste à faire et que « `mrp` ne cree
encore aucun `StkMove` lui-meme » — faux depuis le Bloc C
(`apps/mrp/services/transformation.py:41,106`) ; et
`apps/sales/services/reports.py:112-116` affirme que « `apps.stocks` n'existe pas
encore ».

### 3.4 `apps/quality` est inatteignable depuis le produit

Le module Qualité/HACCP a été construit comme application dédiée, conformément à l'ADR
`docs/planning/2026-09-adr-qualite-haccp-app-dediee.md`, et ses cinq modèles, sept
services et 40 tests tiennent 9 critères QUA sur 10. Mais :

- il n'a **ni `views.py`, ni `urls.py`, ni `api.py`**, et n'apparaît ni dans
  `config/urls.py` ni dans `config/api.py` ;
- il n'a **aucune entrée RBAC** — situation documentée comme volontaire dans
  `docs/RBAC.md:306-312` : « pas un oubli : `apps.quality` n'a encore aucun
  `views.py`/`api.py`/`urls.py` propre… À réviser le jour où `apps.quality` gagnera
  son propre écran/API » ;
- **aucun fichier hors de `apps/quality/` n'importe `apps.quality.services.public`** :
  le blocage de lot au certificat (QUA-8) passe par `catalog.services.public`, pas par
  lui ;
- il ne publie aucun type dans `core.events.PUBLISHED_EVENT_TYPES` : aucun flux
  d'automatisation ne peut se déclencher sur une non-conformité.

Attention au faux positif : `widehalo/templates/quality/` et les routes
`/quality/templates/`, `/quality/inspections/` appartiennent à **`apps.core`**
(modèles `QltChecklistTemplate`/`QltInspection`), pas à `apps.quality`.

Le domaine HACCP n'est donc atteignable aujourd'hui que par une commande de gestion et
par les tests. C'est du travail livré et correct, hors de portée de ses utilisateurs.

### 3.5 Les gardes CI existent, mais plus étroites que ce que les cahiers exigent

Sept jobs, tous bloquants et tous conditionnés à `lint` (`needs: lint`) :
`lint` (`ruff format --check` puis `ruff check`), `security` (`bandit` + `pip-audit`),
`typecheck` (`mypy` sur tous les `services/` et `schemas.py`), `architecture-tests`,
`tests` (**`--cov-fail-under=80`**), `e2e` (Playwright/Chromium, accessibilité et
régression visuelle), `docker-build`. Aucun `continue-on-error`.

`tests/architecture/` contient 7 tests : `test_budget.py`,
`test_endpoint_permissions.py`, `test_module_boundaries.py`,
`test_no_direct_task_queue_usage.py`, `test_no_hardcoded_account_numbers.py`,
`test_no_hardcoded_payroll_rates.py`, `test_attempt_transition_saves_state.py`.

Quatre gardes que les cahiers exigent nommément **n'existent pas** : liste blanche du
copilote (IA-1), absence de SQL en entrée de rapport (BI-2), dates fériées en dur
(FOR-5), taux de TVA en dur (SAL-5). Et deux gardes existantes ont une portée plus
étroite que leur critère : `test_no_hardcoded_account_numbers.py` exclut
`services/reports.py`, c'est-à-dire le fichier qui porte la structure des états
financiers (ACC-2) ; `test_no_hardcoded_payroll_rates.py` ne reconnaît que les
littéraux chaîne de forme `N.NN`, donc ni les montants (`"300000"`) ni les bornes de
tranches (P3/PAY-1).

**Un cas particulier mérite d'être signalé** : `apps/simulation/tests/
test_engine_js_parity.py` — la seule preuve que le moteur JavaScript et le moteur
Python donnent le même résultat (SIM-4) — s'auto-saute proprement si `node` est
absent, et `.github/workflows/ci.yml` ne comporte **aucune étape `setup-node`**. Cette
vérification pourrait donc n'être jamais exécutée en intégration continue.

### 3.6 Un secret de tiers est stocké en clair

`apps/logistics/models.py:368` — `LogServiceProvider.webhook_secret` est un
`CharField(max_length=128)` non chiffré, alors que `apps/core/db/fields.py::
EncryptedCharField` existe et est utilisé pour `PrsEmployee.cin` et
`PrsAbsence.reason`. L'API n'expose que `has_webhook_secret: bool`, ce qui limite la
fuite mais ne protège pas la base ni les sauvegardes. Même remarque pour
`PrjGuestAccess.token`.

C'est un écart existant aujourd'hui, et un point que la Phase 4 érige en exigence
(§13.2 : « table à part, chiffrée, jamais exportée, jamais lue par le copilote » ;
FLX-8).

### 3.7 L'isolation du copilote est applicative, pas au niveau du rôle de base

`apps/core/services/data_query_tool_registry.py` le documente lui-même : le processus
tourne sous le même rôle PostgreSQL `widehalo_app` que le reste de l'application. Le
confinement du copilote — réel et strict au niveau applicatif (§2.1, IA-1 à IA-6) —
n'est donc pas doublé d'une restriction de droits côté base.

---

## 4. Ce qui dépasse ce que les cahiers demandent

À porter au crédit du dépôt, comme dans les deux audits précédents.

- **L'immutabilité est portée par la base, pas par le service**, sur six familles de
  tables : `acc_move`/`acc_move_line`, `stk_move`, `qlt_recall_dossier`,
  `pay_payslip`/`pay_payslip_line`, `stg_budget`/`stg_review_pack`, `core_audit_log`.
  Là où les cahiers demandent « refusé, y compris par appel direct de l'API », le
  dépôt répond « refusé, y compris en contournant l'application ».
- **Le confinement du copilote est plus strict que l'interdit du cahier.** Le cahier
  interdit le text-to-SQL ; le dépôt ne se contente pas de l'interdire, il ne définit
  **aucun outil d'écriture** — une écriture par le copilote n'est pas refusée, elle est
  inexprimable. Vérifié : aucun `.raw()`, `.extra()` ni `cursor.execute()` dans
  `apps/ai/`.
- **La gouvernance des endpoints est un registre motivé, pas une liste**.
  `apps/core/services/endpoint_governance.py` exige une justification écrite par
  endpoint ouvert (20 entrées), et un second test détecte les entrées **devenues
  obsolètes** — un garde-fou contre la dérive de la liste d'exceptions elle-même.
- **La file asynchrone a un point d'entrée unique protégé par la CI.**
  `tests/architecture/test_no_direct_task_queue_usage.py` interdit tout import de
  `django_q` hors de `apps/core/tasks.py`, explicitement pour rendre possible une
  bascule ultérieure vers un autre moteur. Aucun cahier ne le demandait.
- **La régularisation de paie et le rapprochement bancaire refusent d'agir seuls.**
  `bank_reconciliation.suggest_matches` **propose** et ne poste jamais ; c'est déjà,
  par anticipation, l'interdit que la Phase 4 formulera en §4.4 (« un flux entrant
  propose, un humain dispose »).
- **La performance du rappel qualité est réellement mesurée** (QUA-4,
  `test_recall_performance.py`), là où la quasi-totalité des autres critères de
  performance des quatre cahiers restent des intentions non instrumentées.
- **Les dérogations à l'isolation sont recensées et nommées** plutôt que dispersées :
  `PrjGuestAccess` (`RLS_FORCE_FOR_OWNER = False`), `tenant_export.py`, `sandbox.py`.

---

## 5. Régressions et points non vérifiables

**Aucune régression n'a été constatée.** Les points que les deux audits précédents
signalaient comme conformes et qui ont été re-vérifiés ici le sont restés ; les deux
violations structurelles de l'audit Phase 3 sont refermées et couvertes par des tests
de non-régression (`apps/payroll/tests/test_rbac_full_matrix.py` couvre nommément les
deux fuites RBAC).

**Trois critères sont marqués ❓ Non vérifié** — ni confirmés ni infirmés :

| Réf. | Pourquoi |
|---|---|
| P1/CRM-7 | Parcours chronométré (90 s, 12 clics) : exige une mesure sur parcours réel, aucun test de ce type dans `tests/e2e/`. |
| P1/ACC-6 | Rapprochement de la déclaration de TVA à l'ariary près et état justificatif ligne à ligne : le service existe (`tax_returns.py`), le niveau de preuve n'a pas été atteint dans le temps imparti. |
| P2/BI-5 | Chargement d'un tableau de bord de six tuiles en moins de 3 s et dégradation indépendante par tuile : aucune mesure. |

**Deux critères sont N/A par nature** et doivent le rester : `P3/QUA-10` (exercice de
rappel blanc validé par le contrôleur qualité du client) et `P3/PAY-12` (jeu de
bulletins témoins signé par un expert-comptable OECFM). Aucun code ne peut les tenir.

**Une mesure est explicitement laissée en suspens** : les compteurs de budget
d'architecture (§3.2), faute de Django installé dans l'environnement de cet audit. Le
plan de rattrapage doit commencer par les ré-exécuter.

---

## 6. Ce qui a changé depuis cet audit

Cet audit est un instantané. Les chantiers engagés ensuite ferment des critères
qu'il compte encore comme partiels ou absents — les lignes du §2 ne sont pas
réécrites, la trace du point de départ étant ce qui rend le progrès lisible.

| Critère | Verdict à l'audit | Depuis |
|---|---|---|
| `P1/ACC-1` | 🟡 — plan chargé par commande, jamais automatiquement, et jamais selon le pays | Fermé par **D10-5** : `load_chart_of_accounts` résout le plan par `tenant → pays → référentiel`, dans les quatre chemins de création de tenant. Un tenant `--country=SN` ne reçoit plus le plan malgache. |
| `P1/ACC-2` | 🟡 — la garde n'inspectait pas la structure des états financiers, et exemptait `reports.py` | Fermé par **D10-3/4/6** : la structure vit dans `AccFramework.statement_structure`, la garde est élargie à ses trois angles morts (codes à 1-2 chiffres, littéraux entiers, `management/`), une garde nouvelle interdit toute structure d'état financier en Python, et un test prouve la portabilité vers un second référentiel. |
| `P1/ACC-7` | ✅ avec réserve — la forme PCG était en dur dans `reports.py` | Réserve levée par **D10-3**. |
| §3.2 Budgets d'architecture | ❓ non mesurables | Mesurés le jour même (300 / 576 / 240) et relevés de +33 % à **415 / 800 / 320**. |

## 7. Suite

Le plan de fermeture des écarts constatés ici — rattrapage des Phases 1 à 3, puis les
34 sprints de la Phase 4 — est dans
[`docs/planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md`](../planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md).
