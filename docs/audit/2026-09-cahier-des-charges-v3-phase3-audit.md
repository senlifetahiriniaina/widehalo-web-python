# Audit — WideHalo v3, cahier des charges Phase 3 vs. code réel

> **Document historique — ne plus citer comme état courant.**
> Cet audit décrit le dépôt tel qu'il était à sa date. Il a été remplacé par
> [`docs/audit/2026-09-audit-complet-phases-1-4.md`](2026-09-audit-complet-phases-1-4.md),
> qui reprend les 203 critères des quatre cahiers des charges sur le code
> d'aujourd'hui. Conservé pour la traçabilité de la décision, pas pour la lecture
> de l'état du produit.


**Date** : 2026-09-04
**Périmètre** : dépôt `widehalo-web-python`, branche `claude/widehalo-cdc-phase3-docs-ah1bs4`
(basée sur `madagascar1`, qui porte déjà les modules `pos`/`simulation`/`analytics`/`bi`/
`forecast`/`strategy`/`whatsapp` livrés depuis l'audit Phase 1+2), confrontée au document
fourni *WideHalo v3 — Cahier des charges Phase 3* (v3.0, sept. 2026 — Socle d'inventaire,
Stock et entrepôt, Achats/Import/CREDOC, Production, Qualité et HACCP, Paie, extension
Forecast).

**Méthode** : identique à `docs/audit/2026-09-cahier-des-charges-v3-audit.md` (Phase 1+2),
reconduite à l'identique pour rester comparable : introspection directe du code (modèles,
services, vues, API, migrations, tests) par trois passes d'exploration ciblées couvrant
chacune un sous-ensemble du cahier, chaque affirmation sourcée par un chemin de fichier
(et, si possible, une fonction ou un numéro de ligne). Un point non vérifiable avec un
niveau de confiance suffisant est marqué **❓ Non vérifié** plutôt que deviné.

---

## 1. Résumé exécutif

**Le prérequis du cahier est rempli** : « Phases 1 et 2 en production » (page de garde du
cahier) est vrai à la date de cet audit — l'audit précédent (2026-09-03) avait constaté
POS et Simulation financière totalement absents et la Phase 2 officielle non engagée ;
les commits qui ont suivi (`f9efaa0`, `2647040`, `1466ce8`, `91b104f`, `cf97851`,
`a7a5608`, `74b7bdc`) ont livré ces sept chantiers. Ce socle n'est pas rediscuté ici.

**Comme pour les Phases 1+2, le dépôt n'a pas été construit pour satisfaire ce cahier
Phase 3 littéralement — mais, cette fois, pour une raison inverse.** L'audit précédent
avait trouvé un dépôt qui avait grandi sur *un autre périmètre* que celui demandé
(`stocks`, `purchase`, `mrp`, `payroll`, `presence`…, explicitement qualifiés à l'époque
de « contenu qui correspond, dans la nomenclature des deux cahiers fournis, à la Phase 3 »)
: ce même code est aujourd'hui le candidat naturel pour couvrir CE cahier. Le
constat de cet audit est que cette correspondance est **réelle mais partielle** : les
modules existent, une bonne partie de leur mécanique métier est solide et testée, mais ils
ont été conçus pour des besoins antérieurs et différents de ceux, très précis, que ce
cahier Phase 3 formalise — d'où un taux de conformité littérale modeste malgré un volume
de fonctionnalités déjà livrées très supérieur à ce qu'une Phase 3 « from scratch »
produirait à ce stade.

**Sur les 59 critères d'acceptation du cahier** (12 Stock, 10 Achats/Import/CREDOC, 10
Production, 10 Qualité/HACCP, 12 Paie, 5 extension Forecast) : **8 conformes (14 %), 27
partiels (46 %), 21 absents (36 %), 2 non vérifiables, 1 sans objet**. Aucun domaine
n'est à zéro, aucun domaine n'est complet.

**Deux principes structurants du cahier sont concrètement violés par le code existant**,
pas seulement non couverts :
1. *« Aucun module ne tient son propre compteur »* (§12.1) — la réception d'achat
   (`apps/purchase`) ne crée **jamais** de mouvement dans `apps.stocks.StkMove` : deux
   comptabilités de quantité coexistent et divergent silencieusement.
2. *« Le salarié n'a pas de compte. Il n'existe pas de portail salarié »* (§6.1) — un
   authentique portail self-service (`apps/payroll/urls.py` → `my_payslips`/
   `payslip_detail`/`payslip_download`) existe et fonctionne.

À l'inverse, plusieurs briques dépassent nettement ce que le cahier attend à ce stade :
un cycle de crédit documentaire réel (RUU 600, états non sautables), un dossier d'import
et un moteur de coût débarqué déjà câblés à la valorisation, une courbe de consommation
textile par taille calculée depuis la géométrie du patron (pas seulement déclarée), une
généalogie de lot bidirectionnelle avec dossier de rappel, un moteur de règles de paie
générique dont un paramètre réglementaire porte déjà un statut de validation OECFM.

---

## 2. Prérequis — Phases 1 et 2 en production

| Point | État |
|---|---|
| Phase 1 officielle (CRM, Sales, Accounting, POS, Simulation financière, IA) | Complétée depuis l'audit du 2026-09-03 : POS (`f9efaa0`) et Simulation financière (`2647040`) livrés, les écarts CRM/Sales/Accounting/IA relevés alors n'ont pas été ré-audités ici (hors périmètre de cette mission, centrée sur la Phase 3). |
| Phase 2 officielle (entrepôt en étoile + dictionnaire d'indicateurs, BI, Forecast, Strategy, WhatsApp) | Complétée depuis le même audit : `1466ce8` (analytics), `91b104f` (BI), `cf97851` (forecast), `a7a5608` (strategy), `74b7bdc` (whatsapp). Non ré-audités en détail ligne à ligne ici, sauf pour la partie directement réutilisée par la Phase 3 (§3.3, §3.7). |
| Condition explicite du cahier Phase 3 (§4, ligne « Prérequis ») : *« Le modèle dimensionnel de la Phase 2 doit accueillir de nouveaux faits sans reprise »*, à vérifier au sprint 2 selon le cahier | Vérifié dans cet audit (§3.1, point 12.5) : `apps.analytics` existe avec un vrai patron star-schema (dimensions Temps/Tiers/Article, faits Vente/TicketPos/Encaissement/Écriture) — la structure se prête à extension par ajout de faits, mais **aucun des 4 faits Phase 3 demandés (mouvement, réception, ordre de fabrication, paie) n'existe encore**. La condition d'accueil « sans reprise » est donc plausible mais non démontrée : elle n'a jamais été mise à l'épreuve par un ajout réel. |

---

## 3. Couverture par domaine

### 3.1 Socle d'inventaire et modèle de mouvement (§12) — Partiel, avec un principe fondateur non tenu

Le mouvement de stock (`apps.stocks.models.StkMove`) est **rigoureux sur sa partie
centrale** : une ligne unique porte toujours origine ET destination (double entrée), un
mouvement validé est immuable — toute correction passe par `reverse_move` (mouvement
inverse référencé, `apps/stocks/services/moves.py`), jamais par une modification —, la
date d'effet (`StkMove.date`) est bien distincte de la date de création
(`BaseModel.created_at`), et une propriété *Hypothesis* (test basé sur des propriétés,
pas des exemples) prouve que la somme algébrique par produit reste nulle. C'est un socle
de qualité au-dessus de la moyenne des modules audités dans ce dépôt.

Mais trois exigences centrales ne sont pas tenues :
- **CUMP exigé, FIFO livré.** La méthode réellement implémentée et testée
  (`services/moves.py::_consume_fifo_layers`) est du FIFO par couches ; le paramètre
  `valuation_method="cmp"` existe mais n'a **aucun effet différencié** — le code appelle
  inconditionnellement la même logique FIFO quel que soit le paramètre choisi.
- **Aucune écriture comptable sur un mouvement ordinaire.** Seuls les écarts
  d'inventaire produisent une écriture (`services/inventory.py` → `accounting.services.
  public.create_stock_adjustment_entry_from_source`) ; une réception ou une livraison ne
  génère jamais l'écriture d'inventaire permanent que le cahier exige de chaque
  mouvement.
- **« Aucun module ne tient son propre compteur » est violé** : `apps.purchase.services.
  receiving.receive_order_line` incrémente `qty_received` et crée un `PurReceiptLine`
  sans jamais appeler `apps.stocks` — confirmé par recherche exhaustive, aucune fonction
  de réception d'achat n'existe dans l'API publique de `stocks`. C'est, très précisément,
  le risque que le cahier désigne en toutes lettres à sa section 6.2 (« un mouvement de
  stock ne se supprime jamais ») — ici, il ne s'agit pas d'une suppression mais d'une
  absence de création : le même effet de divergence silencieuse.

Sur le reste du socle : la hiérarchie d'emplacements n'a pas de limite à 3 niveaux
(self-FK sans garde), l'état « en transit » d'un transfert inter-dépôts existe comme
valeur d'énumération mais n'est utilisé par aucun service, le lot est bien porté par le
mouvement (conforme à l'exigence centrale du §12.3) mais un lot bloqué (`StkLot.
is_held()`) reste compté disponible et proposable en FEFO — seule la concrétisation du
mouvement échouerait —, et le FEFO lui-même est un moteur réel et testé mais jamais
invoqué automatiquement.

### 3.2 Module Stock et entrepôt (§13.1) — Le moteur existe, l'expérience terrain visée par le cahier n'existe pas

Le cahier fait du confort terrain (scan, tablette, mode dégradé) une exigence
fonctionnelle de premier rang, pas un raffinement. Sur ce point précis, l'écart est net :
`templates/stocks/index.html` est une application de gestion desktop à onglets, sans
aucune mention de scan ou de mode hors-ligne dans tout le module (recherche exhaustive
négative), alors que le protocole hors-ligne du POS existe déjà et est explicitement
désigné par le cahier comme réutilisable (H19) — il n'est réutilisé nulle part dans
`stocks`.

Deux règles de gestion sont **positivement contredites**, pas seulement absentes :
- **Comptage à l'aveugle** (§13.1, règle de gestion n°2) : la quantité théorique est
  affichée sur le même écran que la saisie du comptage
  (`templates/stocks/index.html:407,411`) — l'inverse de ce que le cahier exige.
- **Séparation des tâches à l'inventaire** (§6.3) : rien n'empêche l'utilisateur qui a
  compté de valider son propre écart ; les tests eux-mêmes le font compter et valider
  par le même utilisateur (`tests/test_inventory.py:100-107,133-137`).

Le moteur sous-jacent est en revanche solide : réservation modélisée comme une ligne
distincte du mouvement (conforme à §12.3), moteur FEFO testé, blocage de lot au niveau
mouvement, écarts d'inventaire produisant un mouvement de régularisation immuable
(`STK-8` ✅).

### 3.3 Module Achats, import et CREDOC (§13.2) — La bonne surprise de cet audit, mais déconnectée du stock

Trois briques inattendues et substantielles existent déjà, hors de `apps.purchase` :
- **Un vrai crédit documentaire** (`apps.financing.models.FinCredoc`), cycle RUU 600 en
  états qui refusent tout saut (`tests/test_credoc.py::test_credoc_cannot_skip_states`).
- **Un dossier d'import réel** (`apps.logistics.models.LogShipment`/`LogCustomsFile`),
  avec calcul douanier détaillé (CAF, droits, TVA).
- **Un moteur de coût débarqué testé et déjà branché sur la valorisation**
  (`apps.accounting.services.landed_costs.py`), qui revalorise rétroactivement les
  couches FIFO — la propre documentation en ligne de ce fichier le décrit comme un
  « calculateur autonome, jamais d'écriture postée », ce qui est **obsolète** : un
  chantier ultérieur non documenté l'a effectivement câblé au moteur de stock. C'est
  exactement le même schéma de commentaire périmé que celui relevé sur
  `sales.mark_delivered` dans l'audit Phase 1+2, et retrouvé une seconde fois ici sur
  `apps.purchase.tests.test_acceptance` (qui documente encore un stub « stock toujours à
  zéro » alors que `run_reordering` lit désormais le vrai stock disponible).

Mais ces trois briques vivent chacune dans un module différent (`financing`,
`logistics`, `accounting`) sans jamais former le « dossier conteneur en une chronologie »
que le cahier exige (ACH-5, 🟡) — et surtout, la réception d'achat qui devrait les relier
au stock physique ne produit aucun mouvement (§3.1). Le rapprochement à trois voies
existe et bloque réellement, mais ne compare que 2 voies numériques (commande/facture),
la quantité reçue restant purement informative (ACH-8, 🟡). La conversion d'unité
d'achat → unité de stock, l'unité de conservation du taux de change à la date de
référence côté commande, et la séparation réceptionnaire/facture (ACH-9) sont absentes.

### 3.4 Module Production (§13.3) — Substantiel sur le calcul, déconnecté du stock sur l'exécution

`apps.mrp` a une vraie profondeur : nomenclature multi-niveaux avec détection de cycle
(`services/bom.py`), formules de coût prévu/réel à 3 composantes testées et exactes
(`services/costing.py`), ordre de fabrication avec cycle de vie complet gardé par
`django_fsm`, kanban qui journalise au chatter. Point notable qui **dépasse** le cahier :
la courbe de consommation matière par taille (textile) n'est pas seulement « déclarée »
comme le cahier le demande, elle est **calculée automatiquement** depuis la géométrie
réelle du patron (`apps.patronage.services.consumption.py`), tracée et réversible.

Mais l'exécution physique reste déconnectée du stock, par le même défaut structurel que
§3.1/§3.3 :
- La réservation de composants (`reserve_order`) se contente d'une chaîne libre sur
  `MrpOrderComponent.state`, sans jamais appeler le moteur de réservation réel de
  `stocks` — aucun effet sur la disponibilité.
- La sortie de matière vers un façonnier ne crée **aucun mouvement de stock** :
  `TYPE_SOUS_TRAITANT` existe comme type d'emplacement dans `stocks` mais n'est utilisé
  par aucun service ; le docstring de `MrpSubcontractOrder` admet lui-même que ce
  branchement « sera fait quand `stocks` existera » — commentaire obsolète, `stocks`
  existe déjà.
- Les fonctions de coût prévu/réel, correctement écrites et testées, **ne sont invoquées
  par aucun point d'entrée réel** (`views.py`, `api.py`, `close_order`) — orphelines.
- Un ordre clôturé bloque bien toute nouvelle transition FSM, mais n'empêche pas une
  déclaration de consommation matière ultérieure (aucune vérification d'état dans ce
  chemin).
- Aucune variante « nomenclature de process » agroalimentaire (sous-produits,
  coproduits, rendement attendu) n'existe.
- Le kanban se déplace par bouton, jamais par glisser-déposer tactile — documenté comme
  tel dans le code lui-même.

### 3.5 Module Qualité et HACCP (§13.4) — Le plus gros écart du cahier

Aucune terminologie HACCP (point de contrôle critique, limite critique, plan de
contrôle, fréquence, certificat de validité) n'existe nulle part dans le dépôt —
recherche exhaustive négative. Le dépôt contient en réalité **deux socles qualité
construits indépendamment et jamais connectés entre eux** :
- `apps.core.QltChecklistTemplate`/`QltInspection` — un outil de checklist générique,
  dont le service admet lui-même que l'ouverture d'un ticket de non-conformité
  structuré « reste un travail futur », et dont un échec ne fait que notifier deux
  rôles, sans aucun effet sur le stock.
- Un noyau qualité/traçabilité plus mature dans `apps.stocks`
  (`StkQualityState`/`StkRecall`/généalogie récursive amont-aval), construit pour un
  chantier de traçabilité agro antérieur à ce cahier, qui couvre réellement le blocage
  physique d'un lot et le rappel produit.

Ni l'un ni l'autre ne couvre : le blocage **automatique** d'un lot au dépassement d'une
limite critique dans la même transaction (QUA-1, ❌), le refus de libération tant qu'une
non-conformité reste ouverte (QUA-2, ❌ — aucune entité « non-conformité » structurée
n'existe), le certificat d'analyse obligatoire à la réception (QUA-8, ❌ — le champ
existe sur `StkLot` mais n'est référencé nulle part), ou l'alerte de contrôle en retard
(QUA-9, ❌).

À l'inverse, le rappel produit (`apps.stocks.services.recall.py`) répond mieux qu'attendu
à l'esprit de QUA-4/5/6 : généalogie bidirectionnelle réelle, dossier figé à sa
génération. Mais rien ne garantit techniquement ce gel — pas de verrou d'immutabilité au
niveau modèle, pas de journal réellement en ajout-seul (QUA-6/QUA-7, la discipline
repose sur un seul point d'entrée de service, pas sur une garantie structurelle) — et
aucun test de performance (QUA-4, seuil des 5 secondes) n'existe.

### 3.6 Module Paie (§13.5) — Exécution solide, deux violations concrètes du cloisonnement

Le moteur de paie est réellement générique (`services/rules_engine.py::
evaluate_structure` évalue n'importe quelle règle sans modification de code — PAY-5
techniquement satisfait), le calcul principal ne code aucun taux réglementaire en dur
(IRSA/CNaPS/OSTIE/FMFP viennent de `RegulatoryParameter`), un cycle produit une écriture
comptable réellement équilibrée et testée (PAY-10 ✅), et — changement notable depuis
l'audit Phase 1+2, qui avait constaté ce champ **totalement absent** — `RegulatoryParameter`
porte désormais un statut de validation OECFM (`statut_validation`/`mark_validated()`,
`apps/core/models/regulatory.py`) avec un verrou de déploiement testé
(`apps/core/tests/test_regulatory_deployment_gate.py`).

Mais ce verrou n'est **jamais appelé** par `apps.payroll.services.batches.
validate_and_post_batch` : un cycle de paie précis peut donc être publié avec un
paramètre non validé si le contrôle de déploiement tenant-wide n'a pas encore tourné
(PAY-3, 🟡). L'immutabilité du bulletin publié repose sur la seule absence d'endpoint de
modification — à la différence de `AccMove`, protégé par un trigger base de données —
donc sans garantie qui résisterait à un accès direct (PAY-8, 🟡). Le mécanisme de
régularisation existe comme champ (`PayPayslip.rectifies`) mais n'est utilisé par aucun
service, API ou test — entièrement inatteignable en pratique (PAY-9, ❌).

Deux écarts dépassent la simple couverture fonctionnelle et constituent des violations
concrètes de règles explicites du cahier — détaillées en §5.

### 3.7 Extension du module Forecast (§13.6) — Non commencée, mais amorçable sans reprise

Le module `apps.forecast` documente lui-même, dans son propre code, que le calcul de
besoins matière a été explicitement reporté par le cahier Phase 2 à cette Phase 3 — ce
n'est pas un oubli. Le socle sur lequel s'appuyer existe et est réutilisable : le modèle
en étoile (`apps.analytics`) et le protocole de rétrotest/erreur publiée
(`ForSeriesForecast`, déjà utilisé pour la prévision des ventes) sont directement
transposables. Mais aucun des 5 écrans/mécanismes du cahier n'existe : `apps.purchase.
services.reordering.run_reordering` s'en approche le plus (il compare déjà le stock
disponible réel aux seuils min/max), mais transforme directement une règle en demande
d'achat brouillon, sans étape de proposition dépliable ni décision d'acceptation
explicite — à l'inverse de l'exigence du cahier (« jamais automatique »). La charge
d'atelier projetée et l'alerte de péremption (la donnée `StkLot.date_expiry` existe,
aucune alerte n'y est câblée) n'ont aucun équivalent.

---

## 4. Tableau des 59 critères d'acceptation

Légende : ✅ Conforme (8/59, 14 %) · 🟡 Partiel (27/59, 46 %) · ❌ Absent (21/59, 36 %) ·
❓ Non vérifié (2/59) · N/A Sans objet (1/59, nécessite des utilisateurs réels).

### Socle d'inventaire + Stock et entrepôt (STK-1 à STK-12)

| Réf | Statut | Résumé |
|---|---|---|
| STK-1 | ✅ | Mouvement négatif refusé sauf dérogation par rôle, motivée, journalisée. |
| STK-2 | 🟡 | Égalité mouvement/agrégat prouvée par test ; pas d'écran de contrôle de divergence. |
| STK-3 | 🟡 | FEFO réel et testé, jamais invoqué automatiquement ; pas de motif de sélection manuelle. |
| STK-4 | 🟡 | Lot bloqué exclu à la concrétisation du mouvement, mais compté disponible/proposable en amont. |
| STK-5 | ❌ | État « en transit » : valeur d'énumération jamais exploitée par un service. |
| STK-6 | ❌ | Comptage NON à l'aveugle — quantité théorique affichée avec la saisie. |
| STK-7 | ❌ | Aucune séparation compteur/validateur ; les tests font compter et valider par le même utilisateur. |
| STK-8 | ✅ | Écart validé → mouvement de régularisation immuable, référencé à la session. |
| STK-9 | ❌ | Aucun mécanisme hors-ligne dans `stocks`. |
| STK-10 | ❌ | Recherche par code-barres non câblée à un écran/API. |
| STK-11 | 🟡 | Immutabilité de fait (pas d'écran d'édition) mais non gardée explicitement. |
| STK-12 | ❌ | Aucun mouvement ordinaire ne produit d'écriture comptable. |
| ACH-1 | ✅ | Demande au-dessus du seuil bloquée sans approbation, y compris par API. |
| ACH-2 | 🟡 | Reste-à-recevoir exact, mais toute surlivraison refusée sans tolérance paramétrable. |
| ACH-3 | ❌ | Pas de conversion d'unité d'achat → stock ; aucun mouvement créé à la réception. |
| ACH-4 | 🟡 | Cycle CREDOC refuse les sauts d'état, mais transitions non motivées/documentées en pratique. |
| ACH-5 | 🟡 | Dossier d'import réel, mais commande/CREDOC/réception vivent dans 3 écrans séparés. |
| ACH-6 | 🟡 | Taux de change CREDOC jamais recalculé a posteriori ; côté commande d'achat, champ non exploité. |
| ACH-7 | 🟡 | Moteur de coût débarqué réel et testé, mais revalorise des couches FIFO, pas un CUMP. |
| ACH-8 | 🟡 | Rapprochement bloquant réel, mais à 2 voies numériques (quantité reçue non comparée). |
| ACH-9 | ❌ | Aucune séparation réceptionnaire/validateur de facture. |
| ACH-10 | ❌ | Aucun fait analytique achats/coût débarqué à comparer au moteur de valorisation. |

### Production et Qualité/HACCP (PRD-1 à PRD-10, QUA-1 à QUA-10)

| Réf | Statut | Résumé |
|---|---|---|
| PRD-1 | ✅ | BOM multi-niveaux, détection de cycle testée, quantités développées exactes. |
| PRD-2 | ✅ | Consommation textile par taille — dépasse le cahier (calculée, pas seulement déclarée). |
| PRD-3 | ❌ | Réservation cosmétique, aucun effet réel sur la disponibilité en stock. |
| PRD-4 | 🟡 | Lot fini attaché aux composants si saisie manuelle du lot ; désactivé par défaut hors filière agro. |
| PRD-5 | 🟡 | Kanban journalise au chatter, mais par bouton — pas de glisser-déposer tactile. |
| PRD-6 | ✅ | Taux de conformité calculé depuis les déclarations réelles, jamais saisi. |
| PRD-7 | 🟡 | Motif obligatoire à la déclaration si écart ; aucune réconciliation matière à la clôture. |
| PRD-8 | ❌ | Sous-traitance de façon : aucun mouvement de stock réel créé. |
| PRD-9 | 🟡 | Formules de coût exactes et testées, mais jamais invoquées dans le cycle de vie réel. |
| PRD-10 | 🟡 | Transitions FSM gardées ; déclaration de consommation non gardée sur ordre clôturé. |
| QUA-1 | ❌ | Aucun blocage automatique sur dépassement de limite critique (notion inexistante). |
| QUA-2 | ❌ | Aucune entité non-conformité structurée ; libération jamais bloquée par ce motif. |
| QUA-3 | 🟡 | Horodatage serveur non-antidatable réel ; motif et identité optionnels au niveau service. |
| QUA-4 | ❓ | Généalogie/rappel fonctionnels ; aucun test de performance (seuil 5 s) trouvé. |
| QUA-5 | 🟡 | Généalogie bidirectionnelle réelle, récursive ; jamais comparée à un recalcul brut en test. |
| QUA-6 | 🟡 | Dossier de rappel figé par discipline de service, sans verrou d'immutabilité modèle. |
| QUA-7 | ❌ | Aucune garantie technique d'ajout-seul sur le journal de rappel. |
| QUA-8 | ❌ | Champ certificat existant sur le lot, jamais référencé ni bloquant. |
| QUA-9 | ❌ | Aucune notion de contrôle dû/en retard. |
| QUA-10 | N/A | Exercice de rappel blanc — nécessite utilisateurs réels, hors périmètre d'un audit de code. |

### Paie et extension Forecast (PAY-1 à PAY-12, FOR-11 à FOR-15)

| Réf | Statut | Résumé |
|---|---|---|
| PAY-1 | 🟡 | Barèmes réglementaires paramétrés ; majorations d'heures supplémentaires codées en dur. |
| PAY-2 | ✅ | Calcul utilise la version du paramètre à la date du bulletin, testé sur recalcul antérieur. |
| PAY-3 | 🟡 | Statut de validation OECFM existe (nouveau depuis Phase 1+2) ; jamais vérifié à la publication d'un cycle. |
| PAY-4 | 🟡 | Base/taux/règle affichés par ligne, tableau non dépliable, version du paramètre non tracée. |
| PAY-5 | 🟡 | Moteur générique réel ; aucun écran de création de rubrique ni simulation sur salarié témoin. |
| PAY-6 | 🟡 | Avenant = version datée du contrat, mais fonction de création jamais appelée en pratique. |
| PAY-7 | 🟡 | Détection d'anomalie de variation de net réelle et bloquante ; acquittement global, pas par anomalie motivée. |
| PAY-8 | 🟡 | Immutabilité par absence d'API, sans garantie base de données (contrairement à `AccMove`). |
| PAY-9 | ❌ | Champ de régularisation existant, jamais utilisé par aucun service/API/test. |
| PAY-10 | ✅ | Écriture comptable équilibrée réellement postée et testée. |
| PAY-11 | 🟡 | Masquage/scope réels mais testés sur un seul rôle manager ; deux fuites RBAC concrètes trouvées (§5). |
| PAY-12 | ❓ | Prérequis structurel présent ; validation humaine par expert-comptable hors périmètre du code. |
| FOR-11 | 🟡 | Star schema extensible sans reprise démontrée structurellement ; aucun fait Phase 3 encore ajouté. |
| FOR-12 | ❌ | Aucune proposition dépliable ; réapprovisionnement existant ignore les commandes en cours. |
| FOR-13 | ❌ | Transformation en demande d'achat non conditionnée à une acceptation explicite ; pas de taux mesuré. |
| FOR-14 | ❌ | Aucune charge d'atelier projetée ; briques de capacité disponibles mais non assemblées. |
| FOR-15 | ❌ | Donnée de péremption présente sur le lot ; aucune alerte câblée. |

---

## 5. Sécurité transverse — cloisonnement paie (§6.1) et intégrité (§6.2)

Ce qui **fonctionne réellement**, au-delà de la simple documentation :
- `admin` et `direction` sont explicitement exclus de tout droit sur `payroll` par
  défaut (`docs/RBAC.md` §3.1) — seul `rh` a l'accès complet, plus strict que la plupart
  des modules du dépôt.
- Le second facteur est réellement forcé pour `rh` par un middleware
  (`apps.core.middleware.MFAEnforcementMiddleware`, `settings.CORE_MFA_REQUIRED_ROLES`),
  pas seulement documenté.
- Le 403 explicite (jamais 404) sur un bulletin d'autrui, déjà noté dans l'audit
  Phase 1+2, reste vrai.

Ce qui **viole concrètement** une règle explicite du cahier :
- **Portail salarié interdit, présent.** `apps/payroll/urls.py` expose `my_payslips`/
  `payslip_detail`/`payslip_download`, trois vues accessibles à tout utilisateur
  authentifié (filtrées uniquement par « c'est bien mon propre bulletin »). Le cahier :
  *« Il n'existe pas de portail salarié en Phase 3... Un portail multiplierait les
  comptes à gérer pour un bénéfice faible à cette taille d'entreprise »* — sans nuance
  ni exception.
- **Export planifié non cloisonné pour la paie.** Le mécanisme générique de diffusion
  planifiée (`apps.reporting`) vérifie la permission à la *création* d'une
  planification, mais `run_schedule` l'exécute ensuite sans revérification, avec des
  destinataires (`RptSchedule.recipients`) non revérifiés — un titulaire du rôle `rh`
  peut donc légalement planifier l'envoi périodique par e-mail d'un bulletin individuel
  (`PAY-BULL`, déjà enregistré comme rapport) à des destinataires qui n'ont eux-mêmes
  pas accès à la paie. Le cahier : *« Aucun export libre... ne peut pas être planifié ni
  diffusé par le canal de messagerie »*.
- **Journalisation de la révélation de montant, jamais raccordée.** `log_pii_access()`
  existe (`apps.core.services.audit.py`, action `ACTION_PII_ACCESS`) mais n'est appelée
  nulle part dans le dépôt — le mécanisme de masquage lui-même est réel et actif
  (`SENSITIVE_FIELDS`), mais binaire (champ présent ou absent), jamais « révélé à la
  demande avec action journalisée » comme le cahier le décrit.

Ce qui est **vérifiable seulement par construction, pas par un garde-fou automatisé** —
à la différence de ce que le cahier exige explicitement (« vérifié par test CI ») :
aucun module de paie n'a de test d'intégration continue équivalent à `tests/
architecture/test_no_hardcoded_account_numbers.py` (qui, de plus, ne couvre que
`apps.accounting`) ; l'exclusion des outils IA sur la paie est réelle aujourd'hui
(confirmée par recherche exhaustive dans les trois registres d'outils IA) mais repose
sur une discipline de revue de code, pas sur un test qui échouerait automatiquement si
elle était violée demain — une fissure concrète existe déjà : `payroll` figure dans la
liste des modules autorisés de la recherche en langage naturel (`apps.ai.services.
natural_language_search.py`), sans effet aujourd'hui faute de document payroll indexé,
mais sans garde qui l'empêcherait à la prochaine extension.

---

## 6. Écart net avec le cahier Phase 3

**Manque clairement, à traiter en priorité** (par ordre d'impact) :
1. Réception d'achat déconnectée du mouvement de stock — double comptabilité de
   quantité (§3.1, §3.3).
2. Portail salarié à retirer ou requalifier explicitement avec l'utilisateur (§5).
3. CUMP réellement implémenté (le paramètre existe, la logique ne le respecte pas)
   (§3.1).
4. Écriture comptable sur mouvement ordinaire, pas seulement sur écart d'inventaire
   (§3.1).
5. Terminologie et mécanique HACCP (blocage automatique, non-conformité bloquante,
   certificat obligatoire, contrôle en retard) — le plus gros chantier neuf du cahier,
   sans équivalent partiel exploitable (§3.5).
6. Comptage à l'aveugle et séparation des tâches à l'inventaire — actuellement
   contredits, pas seulement absents (§3.2).
7. Réservation de composants et sous-traitance de façon réellement adossées au moteur
   de stock (§3.4).
8. Verrou de publication de cycle de paie sur paramètre non validé, effectivement
   appelé (§3.6).
9. Export planifié cloisonné pour la paie (§5).
10. Extension Forecast — non commencée, mais le socle analytique et le protocole de
    rétrotest sont prêts à l'accueillir (§3.7).

**Dépasse ou couvre déjà largement l'exigence** :
- Crédit documentaire réel (RUU 600), dossier d'import et moteur de coût débarqué déjà
  câblé à la valorisation — plus riche que ce qu'on attendrait à ce stade.
- Courbe de consommation textile par taille calculée depuis la géométrie du patron, pas
  seulement déclarée.
- Généalogie de lot bidirectionnelle et dossier de rappel, construits pour un besoin
  agro antérieur à ce cahier.
- Statut de validation OECFM sur les paramètres réglementaires, ajouté depuis l'audit
  Phase 1+2 (verrou de déploiement tenant-wide réel, seulement pas encore relié au cycle
  de paie).
- `admin`/`direction` explicitement exclus de la paie par défaut, 2FA réellement forcé
  en middleware.
- Le protocole de rétrotest/erreur publiée de la prévision de ventes (Phase 2) est un
  socle méthodologique directement réutilisable pour la charge d'atelier, au-delà de ce
  qui était demandé pour la Phase 2 elle-même.

---

## 7. Recommandations priorisées

1. **Décider avec l'utilisateur du sort du portail salarié** (§5) : le retirer pour se
   conformer au cahier, ou documenter explicitement une dérogation assumée — le silence
   actuel expose à un écart de conformité qui serait découvert en recette externe.
2. **Câbler la réception d'achat au moteur de mouvement de stock**
   (`purchase.services.receiving` → `stocks.services.public`) — c'est le point unique
   dont dépendent ACH-3, ACH-7 (CUMP réel), ACH-10 et la moitié de la valeur du socle
   §12.1 lui-même.
3. **Implémenter réellement le CUMP** ou, à défaut, documenter explicitement (comme le
   permet le cahier lui-même, §11.1) que le FIFO est retenu à la place — mais alors
   corriger le paramètre `valuation_method="cmp"` qui affiche aujourd'hui un choix sans
   effet.
4. **Appeler le verrou de validation OECFM depuis `validate_and_post_batch`** — la pièce
   manquante est un appel de fonction, le mécanisme lui-même est déjà construit et
   testé.
5. **Exclure explicitement la paie du mécanisme générique de diffusion planifiée**
   (`apps.reporting`), et raccorder `log_pii_access()` à la révélation de montant.
6. **Statuer sur le périmètre Qualité/HACCP** : les deux socles existants
   (`core.Qlt*` et `stocks` qualité/rappel) doivent-ils fusionner, ou le cahier
   nécessite-t-il un chantier neuf dédié ? C'est la décision de conception la plus
   structurante avant tout développement Phase 3 sur ce domaine.
7. **Réconcilier les commentaires de code obsolètes** trouvés une troisième fois dans ce
   dépôt (après `sales.mark_delivered`, déjà relevé en Phase 1+2) : `landed_costs.py` et
   `apps/purchase/tests/test_acceptance.py` documentent tous deux un comportement que le
   code a dépassé sans que le commentaire ne soit mis à jour — un signal répété qui
   mériterait une revue systématique des docstrings « limitation connue » du dépôt.

---

## 8. Limites de cet audit

- Chaque domaine a été audité par un passage dédié (socle inventaire + Stock + Achats ;
  Production + Qualité ; Paie + Forecast) plutôt que par une revue unique exhaustive —
  cohérent avec la méthode de l'audit Phase 1+2, mais signifie qu'un point de couplage
  entre deux domaines audités séparément (ex. Production ↔ Stock, Paie ↔ Forecast) a pu
  être vérifié par un seul des deux passages, pas croisé deux fois.
- Les critères marqués ❓ ou nécessitant un test de performance/charge réelle (QUA-4,
  temps de restitution de généalogie) n'ont pas été mesurés — seulement examinés par
  lecture de code et de tests existants.
- Les modules `crm`/`sales`/`accounting`/`ia` (Phase 1) et `bi`/`strategy`/`whatsapp`
  (Phase 2) n'ont pas été ré-audités ici : cet audit suppose leur état tel que décrit
  dans `docs/audit/2026-09-cahier-des-charges-v3-audit.md`, actualisé seulement pour ce
  que la Phase 3 en réutilise directement (§2).
- Comme pour l'audit précédent, aucune mesure d'expérience utilisateur (SUS, SEQ, temps
  par tâche, adoption du scan) n'a été ni ne pouvait être réalisée sans utilisateurs
  réels.
