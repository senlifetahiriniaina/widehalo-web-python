# Audit — WideHalo v3, cahiers des charges Phase 1 + Phase 2 vs. code réel

> **Document historique — ne plus citer comme état courant.**
> Cet audit décrit le dépôt tel qu'il était à sa date. Il a été remplacé par
> [`docs/audit/2026-09-audit-complet-phases-1-4.md`](2026-09-audit-complet-phases-1-4.md),
> qui reprend les 203 critères des quatre cahiers des charges sur le code
> d'aujourd'hui. Conservé pour la traçabilité de la décision, pas pour la lecture
> de l'état du produit.


**Date** : 2026-09-03
**Périmètre** : dépôt `widehalo-web-python`, branche `claude/verification-cahier-charges-phases-vamu6g`
(41 commits au-dessus de `madagascar1`), confrontée aux deux documents fournis :
*WideHalo v3 — Cahier des charges Phase 1* (v3.0, sept. 2026 — CRM, Sales,
Accounting/PCG 2005, POS, Simulation financière temps réel, IA) et *Phase 2* (v3.0,
sept. 2026 — Business Intelligence, Forecast, Strategy, WhatsApp).

**Méthode** : introspection directe du code (modèles, services, vues, urls,
templates, migrations, tests, CI) par trois passes d'exploration ciblées, complétée
par une relecture directe des fichiers les plus sensibles (`docs/RBAC.md`,
`RegulatoryParameter`, `sales/services/orders.py::mark_delivered`). Chaque
affirmation ci-dessous est sourcée par un chemin de fichier. Quand une affirmation
n'a pas pu être vérifiée avec un niveau de confiance suffisant dans le temps imparti
à cet audit, elle est marquée **Non vérifié** plutôt que devinée — voir §9.

---

## 1. Résumé exécutif

**Le dépôt n'a pas été construit pour satisfaire les deux cahiers des charges
fournis ici.** Il contient un plan de sprints interne différent et déjà « clôturé »
(`docs/planning/2026-refonte-ux-sprints.md`, 16 sprints S0–S15), répondant à un
« dossier de refonte UX » antérieur structuré en lots L0–L9 (Fondations, Data grid,
Textile, Agro, Compta/Paie MG, Personnalisation/offline, IA gateway, rattrapage du
catalogue existant). Ce plan ne mentionne **ni** POS, **ni** Simulation financière,
**ni** entrepôt analytique/dictionnaire d'indicateurs, **ni** Forecast/Strategy/
WhatsApp au sens des deux documents fournis. Sa clôture ne dit donc rien de la
conformité aux cahiers des charges Phase 1/Phase 2 réels — c'est tout l'objet de cet
audit.

**Sur les 52 critères d'acceptation de la Phase 1 officielle** : 4 modules sur 6
existent et sont substantiels (Sales, Accounting, CRM, IA), 2 modules sur 6 sont
**totalement absents** (POS, Simulation financière temps réel — aucune app, aucun
modèle, zéro occurrence des concepts clés). Sur les modules présents, l'exécution
métier est souvent solide mais les garde-fous architecturaux structurants du cahier
manquent : pas d'abstraction comptable PCG 2005/SYSCOHADA, pas de statut de
validation OECFM sur les paramètres réglementaires (donc pas de verrou de
déploiement possible), pas de garde-fou CI sur les permissions d'endpoint.

**Sur les 38 critères d'acceptation de la Phase 2 officielle** : les deux
préalables architecturaux (entrepôt en étoile, dictionnaire d'indicateurs gouverné)
sont **totalement absents**, et aucun des quatre modules ne correspond à ce que le
cahier décrit — ce qui porte les mêmes noms dans le dépôt (`reporting`, le forecast
de `sales`, `strategy`, le service `whatsapp`) répond à des besoins réels mais plus
modestes, antérieurs et indépendants de ce cahier des charges Phase 2. **La Phase 2
telle que spécifiée n'a pas été engagée.**

**Ce qui dépasse réellement le cahier des charges** (à mettre au crédit du dépôt,
voir §8) : l'interdiction du text-to-SQL est respectée plus strictement que demandé
(aucun outil d'écriture n'existe pour l'IA, pas seulement « pas de SQL ») ; le
masquage de champs sensibles (marge, salaires) est un niveau de contrôle N4 que le
cahier ne demandait pas explicitement ; la suppression réelle (`DELETE`) n'est
jamais exposée nulle part dans le produit, au-delà de l'exigence du cahier.

**Constat transversal notable** : les budgets d'architecture réels du dépôt
(254 modèles / 515 endpoints / 218 écrans mesurés au dernier inventaire connu,
plafonds CI à 290/600/240) **dépassent déjà** les plafonds révisés que les deux
cahiers demandent pour Phase 1+Phase 2 cumulées (230/720/135 puis 285/840/180) — non
pas parce que CRM/Sales/Accounting/POS/Simulation/IA/BI/Forecast/Strategy/WhatsApp
ont été sur-livrés, mais parce que le dépôt a grandi sur un **autre périmètre**
(`mrp`, `purchase`, `payroll`, `stocks`, `logistics`, `presence`, `projects`,
`helpdesk`, `financing`, `patronage`, `feasibility`…) — du contenu qui correspond,
dans la nomenclature des deux cahiers fournis, à la **Phase 3** (hors périmètre).

---

## 2. Deux feuilles de route distinctes — à ne pas confondre

| | Plan interne déjà exécuté (`docs/planning/`) | Cahiers des charges fournis (ce qui est audité ici) |
|---|---|---|
| Structure | Lots L0–L9 (UX transverse, Textile, Agro, Compta/Paie, Perso/offline, IA gateway, rattrapage catalogue) | Phase 1 : CRM/Sales/Accounting/POS/Simulation/IA — Phase 2 : BI/Forecast/Strategy/WhatsApp |
| POS | Non mentionné | Module central de la Phase 1 |
| Simulation financière | Non mentionné | Module central de la Phase 1 |
| Dictionnaire d'indicateurs / entrepôt | Non mentionné | Préalable architectural de toute la Phase 2 |
| Statut | « Clôturé » (Sprint 15, commit `2666d69`) | Non engagés au sens de ces documents |

Conclusion : **le statut « Phase 1 clôturée » du plan interne ne doit pas être lu
comme une conformité au cahier des charges Phase 1 fourni par l'utilisateur.** Ce
sont deux référentiels différents qui, par coïncidence de vocabulaire (« Phase 1 »),
peuvent se laisser confondre.

---

## 3. Couverture par module — Phase 1

### 3.1 CRM — Partiel

Pipeline/étapes/pertes/activités bien modélisés (`widehalo/apps/crm/models.py`
`CrmLead`, `CrmStage`, `CrmActivity`, `CrmTeam`), scoping serveur par portefeuille
réel (`crm/services/scoping.py::scope_leads_for_user`). Mais : sociétés/contacts
vivent hors CRM (`apps/partners`, pas de FK directe depuis `CrmLead` — seulement un
`partner_id`) ; **aucun kanban ni glisser-déposer** (liste triable uniquement,
`templates/crm/list.html`) ; aucune segmentation ; le « tableau de bord commercial »
est un jeu de rapports téléchargeables (`crm/services/reports.py`), pas un tableau
interactif ; le chatter (`c-chatter`) n'est **pas** câblé sur les objets CRM (câblé
uniquement sur `SalesOrder` et `mrp`).

### 3.2 Sales — Présent, le plus complet des six

Devis → commande → facture/avoir → écriture comptable réellement câblés
(`sales/services/quotations.py`, `orders.py`, `invoicing.py` →
`accounting/services/public.py::create_customer_invoice_from_source`), acomptes,
numérotation continue non modifiable (trigger DB, `accounting/migrations/0005_*`),
variantes textile taille/couleur (`catalog/services/variants.py`), unités de mesure
agro avec conversions (`catalog/models.py::UnitConversion`), listes de prix, TVA
20 %. **Écart de continuité réel** : la transition commande → bon de livraison
n'atteint jamais le module `stocks` (§6). **Écart transverse** : pas d'autosave de
brouillon en cas de coupure réseau pendant la saisie d'un devis (reporté
explicitement au Sprint 3 du plan interne, jamais repris depuis).

### 3.3 Accounting — Partiel : exécution solide, abstraction absente

Écritures, lettrage, rapprochement bancaire (dont mobile money), déclarations TVA,
états financiers (balance, grand livre, bilan, compte de résultat), clôture
d'exercice : tout existe et est testé (`accounting/services/reports.py`,
`bank_reconciliation.py`, `tax_returns.py`). Mais **deux mandats architecturaux du
cahier n'existent pas** :

1. Aucune abstraction multi-référentiel comptable — pas de `core_accounting_
   framework`/`core_chart_of_accounts`/`core_account_mapping` ; le référentiel PCG
   2005 est câblé en dur pour Madagascar (`accounting/services/chart_of_accounts.py`).
   `CountryDefaultsProfile.chart_of_accounts_code` (`apps/core/models/regulatory.py:46`)
   est un champ texte documenté lui-même comme « simple métadonnée informative ».
2. `RegulatoryParameter` (`apps/core/models/regulatory.py:8-31`) a un versionnement
   par plage de dates (`valid_from`/`valid_to`, contrainte d'exclusion Postgres) mais
   **aucun champ de statut de validation** (`NON_VALIDE`/`VALIDE_OECFM`) — vérifié
   en lisant le modèle directement. Conséquence directe : le verrou de déploiement
   exigé par le cahier (bloquer la mise en production si un paramètre actif n'est
   pas validé par un expert-comptable OECFM) est **structurellement impossible**
   aujourd'hui, faute du champ qui le porterait.

### 3.4 POS — Absent

Aucune app, aucun modèle, aucune vue. Recherche exhaustive de « pos »,
« point_of_sale », « caisse », « session_caisse », « ticket », « cash_session »,
« till » : zéro résultat pertinent (`find -iname "*pos*"` : rien). Rien de partiel à
signaler — c'est un module à construire intégralement s'il reste dans le périmètre
produit.

### 3.5 Simulation financière temps réel — Absent

Aucun moteur de scénarios, aucune bibliothèque/comparateur, aucun point mort. Ce qui
existe à proximité (`accounting/services/reports.py::treasury_forecast`, un
scénario de prêt par dossier dans `financing`, un simulateur de coût produit dans
`feasibility`) répond à des besoins ponctuels sans rapport avec le module décrit
(recalcul <100 ms, atelier de scénarios, bibliothèque personnelle/partagée).

### 3.6 IA — copilote — Présent, gouvernance solide

Liste blanche d'outils en lecture seule avec permission requise vérifiée **avant**
de proposer l'outil au LLM (`core/services/data_query_tool_registry.py`), aucun
outil d'écriture n'existe (plus strict que « pas de text-to-SQL »), journalisation
de chaque appel (`ai/models.py::AiRequest`/`AiDataQuery`), fournisseur LLM
« stub » sûr par défaut (aucun appel réseau tant qu'il n'est pas configuré
explicitement). Écart auto-documenté dans le code : pas de rôle Postgres dédié
moindre-privilège pour le chemin IA — l'isolation reste uniquement applicative.

---

## 4. Couverture par module — Phase 2

### 4.1 Préalables architecturaux (entrepôt + dictionnaire) — Absents

Recherche exhaustive de `dim_temps`/`dim_tiers`/`fact_vente`/`fact_ticket_pos`/
`entrepot`/`warehouse`(sens data warehouse)/`star_schema`/`materialized view` :
zéro résultat. Aucun modèle `Metric`/`Indicator`/`KpiDefinition`/`bi_metric`.
`StgKeyResult.metric_name` (`apps/strategy/models.py:110`) est un champ texte libre,
explicitement documenté comme « jamais validé contre une liste fermée » — l'exact
inverse d'un dictionnaire gouverné.

### 4.2 Business Intelligence — Partiel, catégoriquement différent

`apps/reporting` est un **catalogue de rapports fixes** générés à la demande
(PDF/XLSX/CSV/JSON, `RptDefinition`/`RptJob`/`RptSchedule`), chaque rapport étant un
callback codé en dur et enregistré par le module métier qui le produit
(`reporting/services/catalog.py`). Ce n'est **pas** un constructeur self-service à
mesures/dimensions déclarées, il n'y a **pas** de tableau de bord composable par
rôle, **pas** d'exploration du détail depuis un agrégé, et la diffusion planifiée
n'existe que par e-mail (`reporting/services/scheduling.py::_send_schedule_email`),
jamais par WhatsApp.

### 4.3 Forecast — Partiel, mais répond à un autre besoin

`sales/services/forecast.py` (399 lignes, lu intégralement) est un moteur réel,
explicable, volontairement non-ML (moyenne mobile pondérée + lissage exponentiel
simple, coefficient saisonnier sur fenêtre de 36 mois, composante CRM pondérée par
le pipeline, commandes récurrentes) — un bon outil de prévision de la **demande**
produit. Mais aucun des mécanismes de gouvernance Phase 2 n'existe : pas de
référence naïve saisonnière systématiquement calculée, **pas de rétrotest, pas
d'erreur publiée (MAE/biais)**, pas de calendrier de jours fériés malgaches
versionné (le champ `CountryDefaultsProfile.holidays` existe mais n'est câblé nulle
part), pas d'ajustement humain tracé/réversible, pas de prévision d'encaissement/
trésorerie à 12 mois.

### 4.4 Strategy — Partiel : OKR réel, gouvernance financière absente

Cascade d'objectifs entreprise→département→individu réelle
(`apps/strategy/models.py::StgObjective`/`StgKeyResult`/`StgCheckIn`), benchmarks
sectoriels, capacité — screens `list/create/detail/benchmarks/capacity_outlook`
existent et sont testés. **Absents** : tout modèle de budget versionné/verrouillé,
toute notion d'« Initiative », tout suivi réel/budget/prévision avec commentaire de
gestion, tout pack de revue figé et horodaté. Une cartographie des risques existe
(`core.RiskItem`) mais c'est un registre plat générique, non rattaché à la cascade
d'objectifs comme le cahier le demande.

### 4.5 WhatsApp — Squelette

`core/services/whatsapp.py` (lu intégralement, 85 lignes) et `WhatsAppMessage`
(`apps/core/models/notification.py:44-95`) forment une infrastructure d'envoi/
réception + webhook entrant, correctement **désactivée par défaut**
(`settings.WHATSAPP_ENABLED = False`). Mais aucune des exigences de gouvernance du
cahier n'existe : pas de modèle de consentement/opt-in ni de révocation, pas de
bibliothèque de modèles de message avec statut d'approbation/variables/langues
(seul un `template_name` texte libre), pas de fenêtre de service, pas de plafond de
coût mensuel par tenant, pas de conversation intégrée au chatter, pas de menu
d'intentions pour le parcours entrant (le webhook se contente d'enregistrer le
message reçu).

---

## 5. Tableau des 90 critères d'acceptation

Légende : ✅ Conforme · 🟡 Partiel · ❌ Absent · ❓ Non vérifié dans cet audit (voir §9) · N/A Sans objet (module absent, non mesurable hors utilisateurs réels, etc.)

### Phase 1 — CRM

| Réf | Statut | Justification |
|---|---|---|
| CRM-1 | 🟡 | Transition d'étape câblée (`services/pipeline.py`) et probablement auditée (signal générique), mais **pas de kanban glisser-déposer** (liste uniquement) et chatter non câblé sur CRM. |
| CRM-2 | ❓ | Solde/encours/documents sont potentiellement affichés sur la fiche `partners`, pas `crm` — contenu exact non vérifié dans cet audit. |
| CRM-3 | ❓ | Conversion piste→société+contact+opportunité en une action non vérifiée directement. |
| CRM-4 | ❓ | Tuile « relances en retard » au launchpad non vérifiée directement. |
| CRM-5 | ❓ | État vide pédagogique du pipeline non vérifié directement. |
| CRM-6 | ✅ | `scope_leads_for_user` confirmé : commercial = ses leads assignés, resp_commercial = équipe, appliqué côté serveur. |
| CRM-7 | N/A | Mesure de temps/clics nécessite des utilisateurs réels, non disponible dans cet audit. |

### Phase 1 — Sales

| Réf | Statut | Justification |
|---|---|---|
| SAL-1 | ❓ | Éditeur de lignes existe (`quotation_create.html`) ; chronométrage non mesuré. |
| SAL-2 | ✅ | `create_order_from_quotation` copie lignes/tiers/tarification sans ressaisie ; confirmé par lecture directe. |
| SAL-3 | 🟡 | L'écriture est réellement générée à la facturation (`create_customer_invoice_from_source`), mais en état **brouillon** — une validation comptable séparée est requise avant l'équilibre définitif, ce qui diffère de « génère une écriture équilibrée » lu comme immédiat. |
| SAL-4 | ✅ | Trigger DB bloque toute modification d'une facture postée. |
| SAL-5 | 🟡 | TVA pilotée par données (`AccTax`), pas codée en dur dans le code métier ; lien direct avec une table `core_regulatory_parameter` non confirmé. |
| SAL-6 | 🟡 | Numérotation séquentielle par `ReferenceMixin` ; test de concurrence explicite non confirmé. |
| SAL-7 | ❌ | Autosave de brouillon explicitement reporté (Sprint 3) et jamais repris ; seul un filet générique hors-ligne existe (`offline_queue.js`), pas une récupération de saisie en cours après rechargement. |
| SAL-8 | 🟡 | Génération PDF existe (`templates/reports/quotation.html` etc.) ; règle de présentation Ariary unifiée façon `c-money` non confirmée. |

### Phase 1 — Accounting

| Réf | Statut | Justification |
|---|---|---|
| ACC-1 | 🟡 | PCG 2005 chargeable par commande de management ; chargement *automatique à la création d'un tenant* non confirmé. |
| ACC-2 | ❌ | Aucun test CI trouvé interdisant les numéros de compte/structures en dur. |
| ACC-3 | ✅ | Écran X2 (`quick_entry`) avec suggestion de contrepartie et contrôle d'équilibre continu, confirmé par le plan interne et la structure du code. |
| ACC-4 | 🟡 | Refus applicatif confirmé (service) ; contrainte au niveau base de données elle-même non indépendamment confirmée. |
| ACC-5 | ✅ | `bank_reconciliation.py` : suggestion auto par montant/référence + lettrage manuel assisté. |
| ACC-6 | ❓ | Déclaration TVA existe (`tax_returns.py`) ; rapprochement à l'ariary près et état justificatif ligne à ligne non vérifiés en détail. |
| ACC-7 | ✅ | `balance_sheet`/`income_statement` produits et exportables. |
| ACC-8 | 🟡 | Versionnement par plage de dates réel ; **absence totale d'entrée dans le journal d'audit** (`RegulatoryParameter` n'hérite pas du modèle de base audité). |
| ACC-9 | ❌ | Aucun champ de statut de validation, donc aucun verrou de déploiement possible — confirmé par lecture directe du modèle. |
| ACC-10 | 🟡 | `AccPeriod.STATE_CLOSED` existe et structure le contrôle ; contournement API testé explicitement non confirmé. |

### Phase 1 — IA copilote

| Réf | Statut | Justification |
|---|---|---|
| IA-1 | 🟡 | Conception « lecture seule uniquement » réelle et par construction (aucun outil d'écriture n'existe) ; test CI *exhaustif* listant les endpoints du gateway non confirmé. |
| IA-2 | ✅ | `AiRequest`/`AiDataQuery` journalisent utilisateur/tenant/outil/paramètres/durée. |
| IA-3 | ✅ | Permission vérifiée avant même d'exposer l'outil au LLM (`user.has_perm()`), deny-by-default testé. |
| IA-4 | ✅ | Isolation RLS héritée du reste du dépôt pour toute donnée lue par un outil. |
| IA-5 | ✅ | Par construction : aucun outil d'écriture n'existe, donc une instruction hostile ne peut déclencher aucune action d'écriture. |
| IA-6 | 🟡 | Fournisseur stub sûr par défaut (aucun appel réseau) ; message d'indisponibilité explicite en cas de panne d'un fournisseur *configuré* non confirmé. |
| IA-7 | ❓ | Délai maximal et réponse d'attente non confirmés. |
| IA-8 | 🟡 | Bloc « Sources consultées » listant les outils invoqués existe (`templates/ai/data_query.html`) ; lien cliquable direct vers l'enregistrement source non confirmé. |
| IA-9 | 🟡 | Repli cloud désactivé par défaut (`AI_PROVIDER_CONFIG` vide) ; écran dédié énonçant explicitement les données sortantes non confirmé. |

### Phase 1 — POS (module absent)

| Réf | Statut |
|---|---|
| POS-1 à POS-9 | ❌ Absent — aucune app/modèle/vue POS n'existe dans le dépôt. |

### Phase 1 — Simulation financière (module absent)

| Réf | Statut |
|---|---|
| SIM-1 à SIM-9 | ❌ Absent — aucun moteur de simulation/atelier de scénarios n'existe dans le dépôt. |

### Phase 2 — Business Intelligence

| Réf | Statut | Justification |
|---|---|---|
| BI-1 | ❌ | Pas de dictionnaire d'indicateurs, donc pas de définition/formule/propriétaire/version unique par indicateur. |
| BI-2 | 🟡 | Le moteur de rapports existant n'expose aucun SQL libre (bon principe respecté) mais il n'y a pas de sélection de mesures/dimensions déclarées côté utilisateur — le principe de sécurité est là, le produit fonctionnel non. |
| BI-3 | ❌ | Pas de reconstruction sur une couche sémantique inexistante. |
| BI-4 | ❌ | Pas de processus de rafraîchissement d'entrepôt à afficher (l'entrepôt n'existe pas). |
| BI-5 | ❌ | Pas de tableau de bord composable par tuiles (le launchpad existe mais n'est pas ce mécanisme). |
| BI-6 | ❓ | Pas de restitution agrégée au sens du cahier ; le RBAC général (N1-N4) s'applique aux rapports existants mais un test « rôle × maille » dédié à la fuite par agrégat n'existe pas. |
| BI-7 | 🟡 | Diffusion planifiée par e-mail journalisée existe (`RptSchedule`) ; canal WhatsApp absent. |
| BI-8 | ✅ | Le moteur de rapports (`RptJob`) est déjà asynchrone par conception. |
| BI-9 | ❌ | Pas de dictionnaire, donc pas de versionnement de définition d'indicateur. |
| BI-10 | ❌ | Pas d'exploration du détail depuis un agrégé au sens du cahier. |

### Phase 2 — Forecast

| Réf | Statut | Justification |
|---|---|---|
| FOR-1 | ❌ | Pas de référence naïve saisonnière calculée/affichée systématiquement. |
| FOR-2 | ❌ | Aucune erreur (MAE/pondérée/biais) publiée, aucun rétrotest. |
| FOR-3 | ❌ | Pas de sélection de modèle par rétrotest — une seule formule fixe toujours appliquée. |
| FOR-4 | ❓ | Traitement des valeurs exceptionnelles non confirmé dans `forecast.py`. |
| FOR-5 | ❌ | Pas de calendrier de jours fériés malgaches versionné câblé au moteur (le champ `holidays` existe ailleurs, non relié). |
| FOR-6 | ❌ | Aucun champ d'ajustement humain tracé/réversible sur `SalesForecast`. |
| FOR-7 | ❌ | Découle de FOR-6 : rien à mesurer. |
| FOR-8 | ❌ | Le POS n'existe pas, donc son intégration à la prévision est impossible. |
| FOR-9 | ❌ | `treasury_forecast` (accounting) est fondé sur les échéances AR/AP, pas sur un comportement de règlement par client, et n'est pas intégré au module Forecast. |
| FOR-10 | ❌ | La Simulation financière n'existe pas, donc aucune référence possible. |

### Phase 2 — Strategy

| Réf | Statut | Justification |
|---|---|---|
| STR-1 | ❌ | `StgKeyResult.metric_name` est un texte libre, explicitement documenté comme non validé contre une liste fermée — l'inverse du critère. |
| STR-2 | 🟡 | Cascade entreprise→département→individu réelle ; non-double-comptage non indépendamment confirmé. |
| STR-3 | ❌ | Aucun modèle de budget dans `strategy`. |
| STR-4 | ❌ | Ni budget, ni scénario de simulation, ni prévision conforme à référencer. |
| STR-5 | ❌ | Aucun mécanisme d'écart budget/réel. |
| STR-6 | ❌ | Aucun mécanisme d'écart, donc aucun seuil bloquant. |
| STR-7 | ❌ | Aucun pack de revue figé/horodaté trouvé. |
| STR-8 | 🟡 | Un registre de risques générique (`core.RiskItem`) existe et est audité au sens permissions, mais non rattaché à la cascade d'objectifs comme le cahier le demande. |

### Phase 2 — WhatsApp

| Réf | Statut | Justification |
|---|---|---|
| WA-1 | ❌ | Aucun modèle de consentement, donc aucun contrôle possible à l'envoi. |
| WA-2 | ❌ | Pas de mécanisme de révocation. |
| WA-3 | ❌ | Pas de fenêtre de service ni de statut d'approbation de modèle. |
| WA-4 | 🟡 | Journal de base existe (`WhatsAppMessage` : direction/téléphone/corps/template/statut) mais sans variables, catégorie ni coût. |
| WA-5 | ❌ | Aucun plafond de coût ni limite de fréquence. |
| WA-6 | ❌ | Pas d'intégration au chatter des objets métier. |
| WA-7 | 🟡 | Canal correctement désactivé par défaut (ERP non affecté) ; file d'attente avec état visible et reprise dédiée au canal WhatsApp non confirmée (le modèle `Notification` général n'a pas de mécanisme de réessai identifié). |
| WA-8 | ❌ | Le webhook entrant enregistre le message sans menu d'intentions borné. |
| WA-9 | ❌ | Pas d'intégration entre WhatsApp et les outils IA en lecture seule. |
| WA-10 | ❌ | Pas d'écran de configuration énonçant les données sortantes ; `WHATSAPP_ENABLED` est un simple indicateur technique, pas une gouvernance. |

---

## 6. Points « à contrôler/confirmer » des deux cahiers (H1–H11, encadrés CRITIQUE/DÉCISION ACTÉE)

| Point | Cahier | État réel |
|---|---|---|
| H1 — inventaire réel du dépôt | P1 | Un document équivalent existe (`docs/planning/ECART_ARCHITECTURE.md`), mais produit pour l'autre feuille de route, pas pour ce cahier. Aucun `INVENTAIRE_EXISTANT.md` au sens de ce document. |
| H2 — taux CNaPS/OSTIE | P1 | Payroll déjà construit (hors périmètre officiel Phase 1, c'est du Phase 3) avec des taux en base ; validation OECFM non modélisable (pas de champ statut, cf. §3.3). |
| H3 — loi malgache protection des données | P1 | Question juridique, hors portée d'un audit de code — non traitée ici. |
| H4 — banc d'essai latence Ollama | P1 | Fournisseur LLM configuré en stub sûr par défaut ; aucun banc d'essai réel trouvé dans ce sandbox. |
| H5 — recalibrage JH/JT | P1 | Question de gestion de projet, sans objet pour un audit de code. |
| H6 — audit du catalogue de rapports hérité | P2 | Sans objet : la Phase 2 telle que spécifiée n'a jamais été engagée ; le catalogue `reporting` existant répond à un autre besoin. |
| H7 — banc d'essai volume analytique | P2 | Sans objet : aucun entrepôt analytique n'existe. |
| H8 — règles du fournisseur de messagerie | P2 | Aucune trace de vérification documentée dans le code (le client `MetaCloudAPIClient` est générique, sans logique de catégories/fenêtre de service). |
| H9 — numéro professionnel vérifié | P2 | `WHATSAPP_ENABLED = False` par défaut ; aucune preuve de vérification administrative. |
| H10 — profondeur d'historique pour saisonnalité | P2 | `seasonal_coefficient` exige ≥12 mois distincts sur une fenêtre de 36 mois (`sales/services/forecast.py`) — condition différente et plus faible que les « deux cycles annuels complets » du cahier ; aucun écran de diagnostic dédié. |
| H11 — capacité hebdo et ratios JT | P2 | Question de gestion de projet, sans objet pour un audit de code. |
| CRITIQUE — interdiction du text-to-SQL (P1 §13.4) | P1 | **Respectée, et dépassée** : aucun outil d'écriture n'existe pour l'IA, pas seulement l'absence de génération SQL. |
| CRITIQUE — rôle Postgres applicatif non superutilisateur (P1 §6.2) | P1 | Respectée : `NOSUPERUSER NOBYPASSRLS` explicite dans `docker/init-db/001-init-app-role.sh`. |
| CRITIQUE — Madagascar hors OHADA, distinction PCG2005/SYSCOHADA (P1 §12.2) | P1 | Trivialement non violée (un seul référentiel existe), mais **aucun garde-fou réel** ne protège contre une confusion future puisque SYSCOHADA n'est pas implémenté du tout. |
| CRITIQUE — POS hors ligne d'abord (P1 §13.5) | P1 | Sans objet : module absent. |
| CRITIQUE — simulation sans effet de bord (P1 §13.6) | P1 | Sans objet : module absent. |
| CRITIQUE — verrou de déploiement sur paramètre NON_VALIDE (P1 §13.3) | P1 | **Non respectée** : structurellement impossible, le champ de statut n'existe pas. |
| CRITIQUE — un indicateur, une définition (P2 §1) | P2 | **Non respectée** : pas de dictionnaire, `StgKeyResult.metric_name` en texte libre le contredit explicitement. |
| CRITIQUE — WhatsApp adaptateur, pas refonte (P2 §1) | P2 | **Respectée dans le principe** : le service s'appuie sur le modèle `Notification` générique plutôt que de le dupliquer — mais les fonctionnalités de gouvernance du module restent à construire. |
| DÉCISION ACTÉE — budget d'écrans legacy décroissant (P1 §10.1) | P1 | Un garde-fou de budget d'architecture existe réellement et est appliqué en CI avec historique documenté (`config/settings/base.py`, `tests/architecture/test_budget.py`) — mais pour l'autre feuille de route, pas pour tracer une migration legacy→nouvelle UI au sens de ce cahier. |

---

## 7. Liens cassés

Contrôle par échantillonnage exhaustif des noms : 331 noms d'URL déclarés
(`apps/*/urls.py` + `core`/`config`) confrontés aux 285 appels `{% url %}` distincts
trouvés dans les templates, plus 68 `href` codés en dur. **Aucun lien cassé
concret trouvé** — chaque `{% url %}` résout vers un nom enregistré ; les `href`
en dur pointent soit vers des préfixes de module réels (tuiles de navigation du
shell), soit vers des exemples en commentaire de composants réutilisables jamais
rendus. Un cas précédemment documenté comme cassé (`payroll/my_payslips.html`
se pointant lui-même en boucle) est confirmé corrigé.

**Portée de ce contrôle** : résolution de nom uniquement. Il ne vérifie pas que
chaque argument requis par une URL est correctement fourni à chaque appel, ni
qu'un rendu réel de chaque vue aboutit à un code 200 — un contrôle exhaustif de ce
type demanderait l'exécution complète de la suite de vues avec données réelles,
hors du périmètre de cet audit.

---

## 8. Continuité des workflows de bout en bout

### 8.1 Chaîne commerciale (piste → devis → commande → livraison → facture → écriture)

4 transitions sur 5 sont réellement câblées et vérifiées par lecture directe :
- piste → devis : `create_quotation(..., source_lead_id=...)` conserve le lien.
- devis accepté → commande : `create_order_from_quotation` copie lignes/tiers/
  tarification sans ressaisie.
- commande confirmée → réservation de stock : `procurement.qualify_and_process_order`
  appelle bien `stocks.services.public.check_and_reserve_stock`.
- commande → facture → écriture comptable : `invoice_order` → `accounting.services.
  public.create_customer_invoice_from_source` crée réellement un `AccMove` (en
  brouillon, cf. SAL-3 §5).

**Rupture confirmée** : commande → bon de livraison. `sales/services/orders.py::
mark_delivered` porte encore le commentaire « Simplification assumée (S2, pas
encore de `stocks`) : aucune intégration entrepôt réelle » et se contente de
recopier `qty_delivered = qty` sans jamais créer ni consulter le moindre
`StkPicking`. Or le module `stocks` existe aujourd'hui et est pleinement construit
(18 modèles, écrans dédiés) — ce commentaire est **obsolète et le lien reste
manquant**, pas une fausse alerte.

### 8.2 Chaînes POS et Simulation financière

Sans objet — les deux modules sont absents (§3.4, §3.5), aucune chaîne à tracer.

---

## 9. Cohérence RBAC — écrans et données par rôle

Le RBAC réel du dépôt, vérifié en lecture directe de `docs/RBAC.md` (sourcé
lui-même au code) et de `apps/core/services/rbac_policy.py`/`permissions.py`, est
un système à **4 niveaux indépendants** : N1 module (appartenance à un `Group`) ;
N2 objet-type (permissions Django auto-générées `view`/`add`/`change`, vérifiées
côté serveur par `require_permission()`, **jamais** `delete`) ; N3 enregistrement
(fonctions `scope_*_for_user` par module) ; N4 champ (registre déclaratif
`SENSITIVE_FIELDS` masquant marge et salaires). 11 rôles standards, une matrice
rôle×module complète et une trentaine de permissions personnalisées documentées
avec leur motif métier.

**Ce qui fonctionne bien et dépasse ce que le cahier demandait explicitement** :
- Le masquage de champ N4 (marge sur devis/commandes cachée au rôle `commercial`,
  montants de bulletin de paie cachés aux managers) est un contrôle plus fin que
  le simple « rôle × action » que le cahier décrit.
- Le scoping N3 est réel et vérifié côté serveur pour CRM (portefeuille commercial),
  Strategy (cascade département), présence/paie (accès à ses propres données
  uniquement, avec un 403 explicite plutôt qu'un 404 pour éviter l'énumération
  d'UUID sur les bulletins de paie d'autrui).
- TOTP est bien imposé aux rôles sensibles (`admin`/`direction`/`comptable`/`rh` —
  un sur-ensemble du strict minimum comptable/administrateur demandé par le cahier).
- RLS PostgreSQL est configuré correctement au niveau infrastructure (rôle
  applicatif `NOSUPERUSER NOBYPASSRLS` explicite).

**Écarts réels identifiés** :
- **Aucun test CI n'énumère les endpoints HTMX et ne vérifie qu'ils déclarent une
  permission** — le garde-fou explicitement exigé par le cahier des charges Phase 1
  (§6.4) n'existe pas.
- Le hook générique de scoping N3 (`apply_scope`) ne filtre **rien** pour les
  portées `entity`/`team`/`workshop`/`warehouse` — traité comme `global`, dette
  documentée dans le code lui-même. Le module `projects` n'a **aucun** scope N3
  câblé pour le rôle `collaborateur` (accès large au module entier, disclosé dans
  le code).
- La matrice N2 est accordée **par app entière**, jamais par modèle individuel —
  limitation architecturale documentée (ex. `magasinier` ne peut pas se voir
  restreint à un sous-ensemble des modèles `mrp`).
- Les événements d'authentification (connexion, échec de connexion) sont déclarés
  dans le journal d'audit (`ACTION_LOGIN`/`ACTION_LOGIN_FAILED`) mais **jamais
  effectivement journalisés** — zéro site d'appel trouvé dans le dépôt.
- `RegulatoryParameter` échappe entièrement au journal d'audit (n'hérite pas du
  modèle de base auditée) — alors que le cahier des charges exige explicitement la
  traçabilité de toute modification de paramètre réglementaire.
- Le canal de notification « e-mail » est du code mort : la constante existe mais
  n'est jamais assignée, et `send_mail`/`EmailMessage` n'apparaissent nulle part
  dans `apps/core` — un envoi par e-mail planifié dans `reporting` marque
  `email_sent_at` sans jamais réellement envoyer de courrier.

**Conclusion RBAC** : la cohérence rôle → écrans/données affichés est globalement
tenue pour les modules qui existent (CRM, Sales, Accounting, Strategy, IA, la
plupart des modules « Phase 3 » déjà construits), avec un contrôle serveur réel et
non un simple masquage visuel — mais deux garde-fous explicitement exigés par le
cahier des charges (test CI de permissions par endpoint, audit des paramètres
réglementaires et des connexions) manquent concrètement.

---

## 10. Ce qui dépasse le cahier des charges

À mettre honnêtement au crédit du dépôt, au-delà des exigences littérales des deux
documents :
- Interdiction d'écriture pour l'IA plus stricte que l'interdiction de text-to-SQL
  demandée (aucun outil d'écriture n'existe du tout).
- Masquage de champ sensible (N4) — mécanisme de sécurité non demandé explicitement
  par le cahier, qui ne parle que de rôle × action au niveau écran/endpoint.
- Suppression réelle (`DELETE` SQL) jamais exposée nulle part dans le produit — tout
  passe par le soft-delete applicatif, au-delà de la seule exigence sur les
  documents comptables validés.
- 403 explicite (plutôt que 404) sur l'accès à un bulletin de paie d'autrui, pour
  empêcher l'énumération — un souci de sécurité plus fin que ce que le cahier
  demandait.
- Un garde-fou de budget d'architecture (modèles/endpoints/écrans) réellement
  appliqué en CI avec historique documenté de chaque relèvement — exactement le
  mécanisme que le cahier des charges Phase 1 demande en section 10, existant déjà
  indépendamment de ce cahier.

---

## 11. Recommandations priorisées

1. **Combler le garde-fou CI de permissions par endpoint** (Phase 1 §6.4) — un test
   qui énumère les vues/endpoints et échoue si l'un d'eux ne déclare aucune
   permission. C'est le plus gros écart de sécurité *facile à corriger*.
2. **Ajouter un statut de validation au `RegulatoryParameter`** (`NON_VALIDE`/
   `VALIDE_OECFM`, `valide_par`, `valide_le`) et le verrou de déploiement associé —
   sans ce champ, la conformité PCG 2005 ne peut structurellement pas être
   « validée par un expert-comptable » au sens du cahier.
3. **Faire hériter `RegulatoryParameter` du modèle audité**, et instrumenter
   réellement les événements de connexion/échec — deux lacunes d'audit à faible
   coût de correction.
4. **Câbler `mark_delivered` au module `stocks`** (créer un vrai `StkPicking` plutôt
   que recopier `qty_delivered = qty`) — le commentaire justifiant la
   simplification est obsolète depuis que `stocks` existe.
5. **Décider explicitement, avec l'utilisateur, du sort de POS et Simulation
   financière** : les développer conformément au cahier (chantiers substantiels,
   ~9 critères d'acceptation chacun), ou documenter qu'ils sortent définitivement du
   périmètre produit — le silence actuel expose à une attente commerciale non tenue.
6. **Ne pas présenter le travail existant sous les noms `reporting`/`forecast`/
   `strategy`/`whatsapp` comme une « Phase 2 livrée »** : ce travail a de la valeur
   en soi, mais engager réellement la Phase 2 du cahier suppose de construire
   d'abord l'entrepôt analytique et le dictionnaire d'indicateurs — un chantier
   fondateur avant tout module consommateur (BI, Forecast, Strategy budget/écarts,
   diffusion WhatsApp).
7. **Réparer le canal e-mail des notifications planifiées** — actuellement du code
   mort qui marque un envoi comme fait sans jamais l'effectuer.

---

## 12. Limites de cet audit

- Les critères marqués ❓ (« Non vérifié ») n'ont pas été confirmés par lecture
  directe de code dans le temps imparti à cet audit — ils ne sont **pas** classés
  Absent par prudence, mais méritent une vérification ciblée avant d'être tenus
  pour acquis.
- Le contrôle des liens cassés (§7) porte sur la résolution de nom d'URL, pas sur
  un rendu réel de chaque vue avec des arguments réels.
- Les trois tests d'isolation RLS multi-tenant (`test_raw_sql_cannot_bypass_rls`,
  `test_raw_sql_without_tenant_setting_sees_nothing`,
  `test_cross_tenant_insert_is_rejected_by_rls`) n'ont pas été ré-exécutés dans
  cette session — leur échec précédemment documenté est attribué à l'environnement
  sandbox (absence de cluster Postgres avec rôle applicatif dédié), une explication
  plausible mais non vérifiée indépendamment ici.
- Aucune mesure d'expérience utilisateur (SUS, SEQ, temps par tâche, nombre de
  clics) n'a été ni ne pouvait être réalisée dans cet environnement sans
  utilisateurs réels — cohérent avec ce que le plan interne documente déjà pour sa
  propre feuille de route.
