# Plan de développement — Cahier des charges Phase 3 vs. code réel

**Source de vérité pour le contenu** : [`docs/audit/2026-09-cahier-des-charges-v3-phase3-audit.md`](../audit/2026-09-cahier-des-charges-v3-phase3-audit.md) —
59 critères d'acceptation confrontés au code : **8 conformes, 27 partiels, 21 absents, 2
non vérifiables, 1 sans objet**. Ce document ne ré-audite rien ; il organise la fermeture
des écarts déjà constatés.
**Patron de structure** : [`docs/planning/2026-refonte-ux-sprints.md`](2026-refonte-ux-sprints.md)
(cadence, gabarit de sprint, table de synthèse, section risques), adapté à un chantier
majoritairement backend/service plutôt qu'UI.
**Statut** : plan **prospectif**, non encore exécuté. Chaque sprint porte un objectif et
une définition de fin, pas un « livré ».

---

## 1. Résumé de l'état des lieux

| Statut | Nombre | Part |
|---|---|---|
| ✅ Conforme | 8 | 14 % |
| 🟡 Partiel | 27 | 46 % |
| ❌ Absent | 21 | 36 % |
| ❓ Non vérifiable | 2 | 3 % |
| N/A Sans objet | 1 | 2 % |

Deux violations structurelles à traiter en priorité (pas seulement des écarts de
couverture) : la réception d'achat ne crée jamais de mouvement de stock (double
comptabilité de quantité), et un portail salarié self-service existe alors que le
cahier l'interdit explicitement.

---

## 2. Décisions actées

Quatre décisions structurantes, tranchées avec l'utilisateur, qui fixent le périmètre
et l'effort de ce plan :

| # | Décision | Choix retenu | Impact |
|---|---|---|---|
| D1 | Portail salarié self-service (`apps/payroll/urls.py` → `my_payslips`/`payslip_detail`/`payslip_download`) | **Retrait.** Conformité stricte au cahier (« le salarié n'a pas de compte »). | Sprint P1, ~1 JT. |
| D2 | Architecture Qualité/HACCP (deux socles existants, non connectés : `core.QltChecklistTemplate`/`QltInspection` peu intégré, et `apps.stocks` `StkQualityState`/`StkRecall` plus mature) | **Chantier neuf dédié** — nouvelle app avec son propre domaine et sa propre surface `services.public`, plutôt qu'une extension de `apps.stocks`. | Bloc D, ~26 JT (au lieu de ~17 JT si fusion sur `stocks`). |
| D3 | Méthode de valorisation du stock (le cahier exige le CUMP, le code implémente du FIFO par couches ; le paramètre `valuation_method="cmp"` existe sans effet différencié) | **Vrai CUMP implémenté** — nouvelle logique de consommation par quantité pondérée, et non le FIFO documenté comme alternative que le cahier §11.1 aurait pourtant permis d'acter. | Sprint P3, ~7 JT (au lieu de ~1 JT si FIFO documenté). |
| D5 | Verrou de validation OECFM des paramètres réglementaires de paie (le champ de statut existe déjà en base, mais n'est jamais vérifié à la publication d'un cycle) | **Blocage strict** à la publication si un paramètre actif n'est pas validé — conforme à la lettre du cahier. | Sprint P4, ~1 JT, inchangé. |

Deux points d'implémentation mineurs, non re-questionnés, retenus comme hypothèses de
travail par défaut :
- **D4** — mapping des écritures comptables par nature de mouvement de stock (sprint A3) :
  à valider avec un profil comptable au moment du sprint, pas bloquant en amont.
- **D6** — retrait de `payroll` de la liste des modules autorisés de la recherche IA en
  langage naturel (`apps/ai/services/natural_language_search.py`) plutôt qu'une garde CI
  additionnelle : option la plus sûre et la plus simple à réviser plus tard si besoin.

---

## 3. Cadence et gabarit de sprint

Cadence identique au patron du dépôt : **15 Jour-Token (JT) par semaine**
(`docs/planning/2026-refonte-ux-sprints.md` §2). Gabarit adapté à un chantier
backend/service plutôt qu'UX :

| Jours | JT | Contenu |
|---|---|---|
| J1–J3 | 9 JT | Construction : service(s)/modèle(s) du sprint. |
| J4 | 3 JT | Intégration + vérification des critères d'acceptation référencés (STK/ACH/PRD/QUA/PAY/FOR). |
| J5 | 3 JT | **Jour de durcissement** : test d'architecture dédié si pertinent (patron `tests/architecture/test_module_boundaries.py`/`test_no_hardcoded_account_numbers.py`), docstrings remises à jour (éviter un nouveau commentaire périmé après ceux déjà relevés sur `sales.mark_delivered` et `landed_costs.py`), test de non-régression sur les modules connectés. |

---

## 4. Vague 1 — Sprint 0 : les 7 priorités de l'audit

Ordre d'impact repris de l'audit §7. **Dépendance structurante : P2 précède le reste de
la vague** — P3 (CUMP) n'a de sens que sur des mouvements de réception réels, et P2 est
le prérequis technique de tout le Bloc A/B/C en Vague 2. P1/P4/P5/P6/P7 sont indépendants
entre eux et peuvent être menés en parallèle de P2.

| # | Lot | Objectif | Définition de fin | Fichiers principaux | Effort |
|---|---|---|---|---|---|
| P1 | Retrait du portail salarié | Se conformer au cahier (D1) | Routes/vues `my_payslips`/`payslip_detail`/`payslip_download` retirées, test négatif confirmant leur absence | `apps/payroll/urls.py`, `apps/payroll/views.py`, `templates/payroll/my_payslips.html`, `docs/RBAC.md` (mise à jour) | 1 JT |
| P2 | Câbler la réception d'achat au mouvement de stock | Fin de la double comptabilité de quantité | Nouvelle fonction publique `apps.stocks.services.public.receive_purchase_line(...)` (même patron que `receive_production_output` : résout/crée l'emplacement virtuel fournisseur, appelle `create_move`+`validate_move`) ; `apps/purchase/services/receiving.py::receive_order_line` l'appelle après création du `PurReceiptLine`, en respectant le garde-fou `test_module_boundaries.py` (import uniquement via `services.public`) ; test `apps/purchase/tests/test_receiving.py` étendu pour vérifier le quant après réception | `apps/stocks/services/public.py`, `apps/purchase/services/receiving.py`, `apps/purchase/tests/test_receiving.py` | 5 JT |
| P3 | Vrai CUMP (D3) | La valorisation recalcule un coût unitaire moyen pondéré à chaque entrée, les sorties consomment ce coût moyen — plus de FIFO par couches | Nouvelle logique de consommation par quantité pondérée dans `apps/stocks/services/moves.py` (remplace `_consume_fifo_layers` pour le mode par défaut), tests Hypothesis existants étendus pour prouver l'invariant sous CUMP, paramètre `valuation_method` documenté comme n'exposant plus qu'un seul mode réel | `apps/stocks/services/moves.py`, `apps/stocks/tests/test_valuation.py`, `apps/stocks/tests/test_hypothesis_properties.py` | 6–8 JT |
| P4 | Verrou OECFM à la publication (D5) | `validate_and_post_batch` refuse tout cycle utilisant un paramètre réglementaire actif non validé | Appel de `apps.core.services.regulatory_governance.unvalidated_active_parameters()` ajouté en tête de `validate_and_post_batch` ; test posant un `RegulatoryParameter` non validé actif et vérifiant le refus (miroir de `test_regulatory_deployment_gate.py`, appliqué au cycle de paie réel) | `apps/payroll/services/batches.py`, `apps/payroll/tests/` | 1 JT |
| P5 | Cloisonnement paie transverse | Export planifié exclu pour la paie ; révélation de montant journalisée | (a) `apps/reporting/services/scheduling.py::run_schedule`/exécution planifiée revérifie la permission à l'exécution, pas seulement à la création, et refuse tout `report_code` de la famille paie hors permission confirmée ; (b) `apps.core.services.audit.log_pii_access()` (déjà écrite, jamais appelée) raccordée au point de révélation d'un montant masqué par `SENSITIVE_FIELDS` | `apps/reporting/services/scheduling.py`, `apps/core/services/audit.py`, vue de détail bulletin/paie | 3 JT |
| P6 | Décision Qualité/HACCP actée (D2) — ADR + amorçage | Document de décision (ADR) formalisant D2, squelette de la nouvelle app avec `services/public.py` présent (vide/minimal), prêt pour le Bloc D | Nouveau document de décision (`docs/audit/` ou `docs/planning/`, à la discrétion de l'implémenteur), squelette `apps/quality/` (app Django minimale : `apps.py`, `models.py`, `services/public.py`, `module.py`) | 2 JT |
| P7 | Réconcilier les commentaires de code obsolètes | Les docstrings décrivent le comportement réel du code | `apps/accounting/services/landed_costs.py` : retirer la mention « calculateur autonome, jamais d'écriture postée » (obsolète depuis son câblage réel à la valorisation) ; `apps/purchase/tests/test_acceptance.py` : retirer la mention d'un stub « stock toujours à zéro » (obsolète depuis `run_reordering`) ; ajouter un rappel court dans le gabarit de revue (CI/PR) invitant à vérifier les docstrings « limitation connue » à chaque sprint de durcissement | `apps/accounting/services/landed_costs.py`, `apps/purchase/tests/test_acceptance.py` | 1 JT |

**Total Vague 1 : ≈ 20 JT** (≈ 1,5 semaine à la cadence retenue).

---

## 5. Vague 2 — Blocs jusqu'à conformité complète

### Bloc A — Socle/Stock (dépend de P2)

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| A1 | Natures de mouvement complètes + état « en transit » + contrôle de divergence | `StkMove.MOVE_TYPE_CHOICES` porte les 12 natures du cahier (3 manquantes aujourd'hui sur 9, à confirmer précisément contre le texte du cahier au moment du sprint) ; nouveau service `transfer_between_warehouses` en deux phases (via l'emplacement `TYPE_TRANSIT`, déjà modélisé mais jamais utilisé) ; écran/API de contrôle STK-2 (agrégat quant vs. somme des mouvements) | `apps/stocks/models.py`, `apps/stocks/services/moves.py` (nouveau `transfer_between_warehouses`), `apps/stocks/services/consistency.py` | 5 JT |
| A2 | Lot bloqué exclu du disponible/FEFO + limite de 3 niveaux d'emplacement | `services/quants.py::select_lot_fefo`/`get_available_stock_qty` excluent tout lot `is_held()==True` en amont (pas seulement à `create_move`) ; garde sur `StkLocation.parent` refusant une profondeur > 3 | `apps/stocks/services/quants.py`, `apps/stocks/services/public.py::get_available_stock_qty`, `apps/stocks/models.py::StkLocation` | 3 JT |
| A3 | Écriture comptable sur mouvement ordinaire (STK-12) | Toute validation de mouvement interne↔interne poste une écriture équilibrée, via une nouvelle fonction généralisant `create_stock_adjustment_entry_from_source` ; mapping `move_type → AccAccount.type` validé avec un profil comptable (D4) | `apps/stocks/services/moves.py`, `apps/accounting/services/public.py` (nouvelle `create_stock_movement_entry_from_source`) | 6 JT |
| A4 | Comptage à l'aveugle + séparation des tâches | Quantité théorique masquée pendant la saisie, affichée seulement après validation ; RBAC empêchant `counted_by == validated_by` sur un même écart | `templates/stocks/index.html` (lignes 407/411), `apps/stocks/services/inventory.py`, `apps/stocks/tests/test_inventory.py` | 3 JT |
| A5 | Gardes explicites + immutabilité technique | Garde sur changement d'unité de stock après premier mouvement ; garde sur passage géré-par-lot si stock non nul ; verrou base de données sur `StkMove` validé (aujourd'hui immuable par absence d'API seulement) | `apps/catalog/models.py`, `apps/stocks/models.py`, nouvelle migration trigger | 4 JT |
| A6 | Mode dégradé + écran magasinier scan-first | Réutilisation du protocole hors-ligne déjà écrit pour `apps.pos` (même patron de file d'attente) appliqué à `stocks` ; nouvel écran mobile-first avec recherche code-barres câblée (STK-10) | référence `apps/pos/services/` (protocole hors-ligne, à réutiliser sans dupliquer), nouveau `templates/stocks/tw-scan.html`, `apps/stocks/views.py` | 6 JT |

**Bloc A : 27 JT**

### Bloc B — Achats, import et CREDOC (B1 dépend de P2 ; B4/B7 dépendent de P3 pour ACH-7)

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| B1 | Conversion unité d'achat → stock | `receive_purchase_line` (créée en P2) applique un facteur de conversion avant l'appel à `create_move` | `apps/purchase/models.py`, `apps/stocks/services/public.py::receive_purchase_line` | 3 JT |
| B2 | Chronologie unifiée CREDOC/import/coût débarqué + transitions motivées | Nouvel écran agrégeant `FinCredoc`/`LogShipment`/`LogCustomsFile` en une frise chronologique par dossier (lecture seule, via les `services.public` respectifs) ; chaque transition CREDOC exige un motif obligatoire journalisé | vue composite nouvelle, `apps/financing/services/credoc.py` | 5 JT |
| B3 | Taux de change commande d'achat exploité | `PurOrder` porte et exploite un taux de change à la date de référence, même patron que `FinCredoc.amount_foreign`/`credoc_fx_variance` déjà livré | `apps/purchase/models.py`, `apps/purchase/services/orders.py` | 2 JT |
| B4 | Rapprochement à trois voies réel + tolérance de surlivraison paramétrable | Quantité reçue réellement comparée (pas seulement commande/facture) ; seuil de tolérance configurable au lieu d'un refus systématique (ACH-2) | service de rapprochement facture existant (à confirmer précisément au sprint) | 4 JT |
| B5 | Séparation réceptionnaire/facture | RBAC/service refusant qu'un même utilisateur réceptionne ET valide la facture associée | `apps/purchase/services/receiving.py`, module `accounting` (validation facture fournisseur) | 2 JT |

**Bloc B : 16 JT** (ACH-10 fermé au Bloc Transverse T2, pas dupliqué ici)

### Bloc C — Production (dépend de P2 ; C2 réutilise les emplacements `TYPE_SOUS_TRAITANT` déjà modélisés)

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| C1 | Réservation de composants réelle | `reserve_order` appelle `stocks.services.public.check_and_reserve_stock` par composant, au lieu de ne toucher que `component.state` | `apps/mrp/services/orders.py::reserve_order` | 3 JT |
| C2 | Sous-traitance de façon avec mouvement réel | Nouvelle paire `stocks.services.public.send_to_subcontractor`/`receive_from_subcontractor` (emplacement `TYPE_SOUS_TRAITANT` déjà modélisé, jamais utilisé) appelée par `MrpSubcontractOrder` | `apps/stocks/services/public.py`, service de sous-traitance de `apps/mrp` | 4 JT |
| C3 | Brancher le calcul de coût dans le cycle réel + réconciliation matière à clôture | `compute_planned_cost` appelé à la réservation, `compute_real_cost` à `close_order` (PRD-9) ; réconciliation matière consommée vs. théorique tracée à la clôture (PRD-7) | `apps/mrp/services/orders.py::close_order`, `apps/mrp/services/costing.py` (déjà correct, à invoquer) | 4 JT |
| C4 | Garde d'état sur la déclaration de consommation | `record_component_consumption` refuse si l'ordre est dans un état clôturé | `apps/mrp/services/transformation.py::record_component_consumption` | 1 JT |
| C5 | Nomenclature de process agroalimentaire (sous-produits/coproduits/rendement) | Nouvelle variante de nomenclature portant rendement attendu et lignes de sous-produits/coproduits ; revue de l'activation par défaut de l'attachement du lot fini hors filière agro (PRD-4) | `apps/mrp/models.py`, `apps/mrp/services/bom.py` | 6 JT |
| C6 | Kanban glisser-déposer tactile | Remplace le patron « bouton » par un vrai glisser-déposer (Alpine/Sortable), cibles ≥ 44 px conservées | `templates/mrp/kanban.html` | 3 JT |

**Bloc C : 21 JT**

### Bloc D — Qualité et HACCP (chantier neuf dédié, D2 — dépend de P6)

Architecture retenue : nouvelle app `apps.quality` (amorcée en P6), qui **orchestre** le
domaine HACCP (plans de contrôle, points critiques, mesures, non-conformités,
certificats, dossier de rappel) mais **réutilise** les mécanismes physiques déjà
construits et testés dans `apps.stocks` via sa surface `services.public` plutôt que de
les dupliquer — notamment le blocage de lot (`set_quality_state`, déjà existant) et le
calcul de généalogie (`lot_genealogy_tree`, déjà existant et performant). Le
rattachement d'une non-conformité ou d'un plan de contrôle à un lot/une réception/un
ordre de fabrication suit le patron déjà en place dans ce dépôt pour ce type de
référence transverse (content-type/object-id, comme `core.RiskItem`/`QltChecklistTemplate`),
pour ne pas créer de dépendance dure entre `apps.quality` et `apps.stocks`/`apps.mrp`/
`apps.purchase` au niveau modèle. Le sort de `core.QltChecklistTemplate`/`QltInspection`
(garder, migrer vers `apps.quality`, ou retirer) est à trancher au sprint D1, une fois le
nouveau domaine modélisé.

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| D1 | Domaine HACCP + non-conformité structurée + blocage automatique (QUA-1, QUA-2, QUA-3) | Modèles `apps.quality` (plan de contrôle, point critique, mesure, non-conformité) ; une mesure hors limite critique déclenche, dans la même transaction, un appel à `stocks.services.public.set_quality_state(lot, BLOCKED, ...)` ; la libération d'un lot est refusée tant qu'une non-conformité liée reste ouverte ; motif et identité rendus obligatoires (pas seulement optionnels comme aujourd'hui côté `stocks`) | `apps/quality/models.py`, `apps/quality/services/public.py`, `apps/stocks/services/public.py` (hook de blocage appelé depuis `quality`) | 8 JT |
| D2 | Certificat d'analyse obligatoire et bloquant à réception (QUA-8) | La réception (câblée en P2/B1) refuse si l'article exige un certificat et qu'aucun certificat valide n'est rattaché au lot | `apps/catalog/models.py` (flag « exige certificat »), `apps/quality/services/public.py`, `apps/stocks/services/public.py::receive_purchase_line` | 4 JT |
| D3 | Alerte contrôle dû/en retard (QUA-9) | Commande planifiée comparant la fréquence d'un plan de contrôle au dernier contrôle réalisé par lot, notification en cas de dépassement | `apps/quality/services/public.py`, nouvelle commande de management | 3 JT |
| D4 | Dossier de rappel : réutilisation de la généalogie + immutabilité technique (QUA-4 à QUA-7) | Le dossier de rappel d'`apps.quality` appelle `stocks.services.public.lot_genealogy_tree` (pas de recalcul dupliqué) ; verrou base de données empêchant toute modification/suppression d'un dossier déjà généré (même patron que le trigger d'immutabilité d'`AccMove`) ; test de performance sur un jeu de données représentatif (seuil 5 s) | `apps/quality/models.py`, `apps/quality/services/public.py`, nouvelle migration trigger, `apps/quality/tests/test_recall_performance.py` | 6 JT |
| D5 | Décision sur `core.QltChecklistTemplate`/`QltInspection` et sur `StkQualityState`/`StkRecall` existants | Migration des données utiles vers `apps.quality` si retenues, ou retrait documenté ; mise à jour de `docs/RBAC.md` en conséquence | selon décision au sprint (`apps/core/models/quality.py`, `apps/stocks/models.py`) | 5 JT |

**Bloc D : 26 JT**

### Bloc E — Paie, reste (E1/E2 indépendants ; les autres dépendent de P4/P5 pour cohérence)

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| E1 | Majorations d'heures supplémentaires vers un paramètre versionné (PAY-1) | `DEFAULT_OVERTIME_MULTIPLIERS` remplacé par des `RegulatoryParameter` (même patron que les taux déjà paramétrés) | `apps/payroll/services/expr.py`, nouveaux `RegulatoryParameter` | 3 JT |
| E2 | Garde CI paie (pas de barème en dur) + retrait de `payroll` de la recherche IA (D6) | Nouveau `tests/architecture/test_no_hardcoded_payroll_rates.py` (miroir de `test_no_hardcoded_account_numbers.py`) ; `payroll` retiré de `apps/ai/services/natural_language_search.py` | `tests/architecture/test_no_hardcoded_payroll_rates.py` (nouveau), `apps/ai/services/natural_language_search.py` | 2 JT |
| E3 | Ligne de bulletin dépliable + version du paramètre tracée (PAY-4) | UI expand par ligne, chaque ligne référence la version exacte du `RegulatoryParameter` appliqué | `templates/payroll/payslip_detail.html`, `apps/payroll/models.py` | 3 JT |
| E4 | Écran de simulation de rubrique sur salarié témoin (PAY-5) | Nouvel écran appelant le moteur de règles contre un employé désigné « témoin », sans persistance réelle | `apps/payroll/views.py`, nouveau template | 4 JT |
| E5 | `create_amendment` câblé en pratique (PAY-6) | Appelé depuis l'écran de modification de contrat | `apps/payroll/services/contracts.py::create_amendment`, vue contrat | 2 JT |
| E6 | Acquittement d'anomalie motivé par anomalie (PAY-7) | Remplace l'acquittement global par un acquittement par anomalie individuelle avec motif obligatoire | `apps/payroll/services/batches.py` | 3 JT |
| E7 | Régularisation réellement utilisée (PAY-9) | Nouveau service de régularisation, seul point d'entrée renseignant `PayPayslip.rectifies` | `apps/payroll/services/regularization.py` (nouveau), vue dédiée | 4 JT |
| E8 | RBAC testé sur les 13 rôles (PAY-11) | Suite de tests paramétrée sur l'ensemble des rôles, couvrant les 2 fuites RBAC déjà identifiées par l'audit §5 | `apps/payroll/tests/test_rbac_full_matrix.py` (nouveau) | 3 JT |
| E9 | Immutabilité technique du bulletin publié (PAY-8) | Verrou base de données sur `PayPayslip` publié, même patron que le trigger `AccMove`/D4 | nouvelle migration trigger | 2 JT |

**Bloc E : 26 JT**

### Bloc F — Extension Forecast (dépend du Bloc A, du Bloc C, et du Bloc Transverse pour F1/F3)

| Sprint | Objectif | Définition de fin | Fichiers | Effort |
|---|---|---|---|---|
| F1 | Besoin matière prévisionnel via nomenclature | Explosion des prévisions de vente à travers les nomenclatures, confrontée au stock/réservations/commandes en cours | `apps/forecast/services/material_needs.py` (nouveau) | 5 JT |
| F2 | Proposition de réapprovisionnement dépliable + acceptation/rejet + taux mesuré | Nouveau modèle de proposition interposé entre `run_reordering` et la création de la demande d'achat — jamais automatique, taux d'acceptation calculé | `apps/purchase/services/reordering.py` (refactor), nouveau modèle | 5 JT |
| F3 | Charge d'atelier projetée vs. réalisé | Réutilise le protocole de rétrotest déjà existant pour la prévision de ventes, appliqué à la charge par poste | `apps/forecast/services/workload_forecast.py` (nouveau) | 5 JT |
| F4 | Alerte de péremption | Commande planifiée sur la date limite de lot, notification/tableau de bord | `apps/stocks/services/expiry_alerts.py` (nouveau) | 2 JT |

**Bloc F : 17 JT**

### Bloc Transverse — Extension du modèle dimensionnel (interleaved, pas groupé en fin de plan)

Un fait développé juste après que son domaine source soit fiabilisé — le cahier exige
une preuve d'extension « sans reprise », mieux démontrée par 4 ajouts espacés qu'un
batch de fin de projet qui ne la testerait qu'une fois.

| Sprint | Objectif | Fait ajouté | Dépendance | Effort |
|---|---|---|---|---|
| T1 | Fait mouvement de stock | Un fait par `StkMove` validé | P2 | 3 JT |
| T2 | Fait réception/achat (ferme ACH-10) | Un fait par réception, coût débarqué inclus | Bloc B (B1), P3 | 3 JT |
| T3 | Fait ordre de fabrication | Un fait par ordre clôturé, coût planifié vs. réel | Bloc C (C3) | 3 JT |
| T4 | Fait paie | Un fait par bulletin publié | Bloc E (E1/E3 au moins) | 3 JT |

**Bloc Transverse : 12 JT**

---

## 6. Table de synthèse

| Bloc | Sprints | Effort (JT) | Dépendances amont | Critères fermés |
|---|---|---|---|---|
| Vague 1 (Sprint 0) | P1–P7 | 20 | — | Portail retiré, réception câblée, CUMP réel, PAY-3 fermé, cloisonnement paie, ADR Qualité, docstrings à jour |
| A — Socle/Stock | A1–A6 | 27 | P2 | STK-2,3,4,5,6,7,9,10,11,12 |
| B — Achats/Import/CREDOC | B1–B5 | 16 | P2, P3 | ACH-2,3,4,5,6,8,9 |
| C — Production | C1–C6 | 21 | P2 | PRD-3,4,5,7,8,9,10 |
| D — Qualité/HACCP | D1–D5 | 26 | P6 | QUA-1,2,3,4,5,6,7,8,9 |
| E — Paie | E1–E9 | 26 | P4, P5 | PAY-1,4,5,6,7,8,9,11 |
| F — Extension Forecast | F1–F4 | 17 | Bloc A, Bloc C, Bloc T | FOR-11 (démontré),12,13,14,15 |
| T — Transverse | T1–T4 | 12 | P2/P3, Bloc B/C/E respectivement | ACH-10, FOR-11 (prérequis) |
| **Total** | | **≈ 165 JT** | | 57/59 critères couverts par du code ; QUA-10 et PAY-12 restent hors portée (exercice avec utilisateurs réels, validation humaine par expert-comptable) |

À 15 JT/semaine : **≈ 11 semaines (~2,5–3 mois)** pour l'intégralité du plan.

---

## 7. Matrice de couverture des 59 critères

| Domaine | Critères fermés par ce plan | Sprint(s) |
|---|---|---|
| Stock (STK-1..12) | STK-1, STK-8 déjà ✅ (aucune action) ; STK-2,3,4 → A1/A2 ; STK-5 → A1 ; STK-6,7 → A4 ; STK-9,10 → A6 ; STK-11 → A5 ; STK-12 → A3 | A1–A6 |
| Achats (ACH-1..10) | ACH-1 déjà ✅ ; ACH-2 → B4 ; ACH-3 → B1 ; ACH-4,5 → B2 ; ACH-6 → B3 ; ACH-7 → P3 (CUMP réel) + B1 ; ACH-8 → B4 ; ACH-9 → B5 ; ACH-10 → T2 | P3, B1–B5, T2 |
| Production (PRD-1..10) | PRD-1,2,6 déjà ✅ ; PRD-3 → C1 ; PRD-4 → C5 ; PRD-5 → C6 ; PRD-7,9 → C3 ; PRD-8 → C2 ; PRD-10 → C4 | C1–C6 |
| Qualité/HACCP (QUA-1..10) | QUA-1,2,3 → D1 ; QUA-4,5,6,7 → D4 ; QUA-8 → D2 ; QUA-9 → D3 ; QUA-10 hors portée (N/A, exercice avec utilisateurs réels) | D1–D5 |
| Paie (PAY-1..12) | PAY-2,10 déjà ✅ ; PAY-1 → E1 ; PAY-3 → P4 ; PAY-4 → E3 ; PAY-5 → E4 ; PAY-6 → E5 ; PAY-7 → E6 ; PAY-8 → E9 ; PAY-9 → E7 ; PAY-11 → E8 ; PAY-12 hors portée (❓, validation humaine OECFM) | P4, E1–E9 |
| Forecast (FOR-11..15) | FOR-11 → T1–T4 (démonstration par l'ajout réel des 4 faits) ; FOR-12,13 → F2 ; FOR-14 → F3 ; FOR-15 → F4 | F1–F4, T1–T4 |
| Transverse (§6.1/§6.2 sécurité paie) | Portail retiré → P1 ; export cloisonné + journalisation PII → P5 | P1, P5 |

---

## 8. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Régression sur les modules déjà connectés au moment de câbler `stocks`↔`purchase`↔`mrp` (P2, C1, C2) | Jour de durcissement à chaque sprint ; garde-fou déjà existant `tests/architecture/test_module_boundaries.py` (tout appel inter-app passe par `services.public`) exécuté en CI à chaque sprint touchant plusieurs apps. |
| Ampleur du chantier Qualité/HACCP neuf (Bloc D) sous-estimée — c'est le plus gros écart de l'audit et une app entièrement nouvelle | Re-estimation obligatoire au sprint D1 avant d'engager D2–D5 ; le sort de `core.Qlt*`/`stocks` qualité (D5) est volontairement placé en fin de bloc, une fois le nouveau domaine mieux compris. |
| CUMP réel (P3) plus coûteux que prévu si la cascade sur les tests Hypothesis révèle des invariants non anticipés | Sprint dimensionné avec une fourchette (6–8 JT plutôt qu'un chiffre unique) ; si dépassement, le sprint peut être scindé sans bloquer P4–P7 qui n'en dépendent pas. |
| Dérive de périmètre pendant le Bloc D (nouvelle app) vers une réimplémentation complète de ce que `stocks`/`mrp` font déjà | Principe explicite en tête du Bloc D : `apps.quality` orchestre, ne duplique pas le blocage de lot ni le calcul de généalogie déjà construits et testés côté `stocks`. |
| Le Bloc F (Forecast) et le Bloc Transverse (T1–T4) sont interdépendants avec presque tous les autres blocs | Séquencement explicite : T1 après P2, T2 après B1/P3, T3 après C3, T4 après E1/E3 — chaque fait est développé au fil de l'eau, jamais en batch de fin de projet. |

---

## 9. Alternatives de séquencement envisagées

1. **Parallélisation multi-piste.** Après la Vague 1, les Blocs A/B/C, D et E sont
   largement indépendants entre eux (seuls B1/C1/C2 dépendent de P2, pas des sprints
   A1–A6 eux-mêmes). Avec plusieurs sessions/agents en parallèle, le calendrier peut
   descendre à ~5–6 semaines pour le même volume. **Non retenue par défaut** pour rester
   comparable au patron mono-piste du reste du dépôt, mais explicitement disponible comme
   accélérateur si le rythme d'une semaine et demie pour la Vague 1 seule s'avère trop
   lent en pratique.
2. **Regrouper les 4 faits analytiques (Bloc T) en un seul sprint de clôture** plutôt
   qu'interleaved — **écartée** : le cahier exige une preuve d'extension « sans reprise »
   par un ajout réel, mieux démontrée par 4 ajouts espacés qu'un batch qui ne la testerait
   qu'une fois.
3. **Traiter le Bloc D (Qualité/HACCP) avant les Blocs A/B/C**, sur l'argument que c'est
   le plus gros écart — **écartée** : le Bloc D dépend d'un temps de latence humaine (ADR
   D2, sprint P6), alors que le Bloc A est un prérequis dur pour presque tout le reste
   (Achats, Production, Forecast) et ne dépend d'aucune décision bloquante. Démarrer le
   Bloc A immédiatement après la Vague 1 minimise le risque d'attente.
4. **CUMP documenté comme FIFO retenu plutôt qu'implémenté** — c'était la recommandation
   par défaut de la conception initiale (le cahier §11.1 l'autorise explicitement, pour
   1 JT au lieu de 6–8). **Écartée par décision explicite de l'utilisateur** (D3) : le
   vrai CUMP est implémenté, cohérent avec l'esprit du cahier plutôt qu'avec son
   échappatoire la moins coûteuse.
