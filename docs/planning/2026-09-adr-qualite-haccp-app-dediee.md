# ADR — Qualité/HACCP : application dédiée neuve (décision D2)

**Statut** : Acceptée (tranchée avec l'utilisateur, cf. `docs/planning/
2026-09-cahier-des-charges-v3-phase3-plan.md` §2, décision D2).
**Date** : 2026-09 (Phase 3, sprint P6 de la Vague 1).
**Source** : `docs/audit/2026-09-cahier-des-charges-v3-phase3-audit.md` (§3.5 —
« Terminologie et mécanique HACCP... le plus gros chantier neuf du cahier, sans
équivalent partiel exploitable »).

## Contexte

Le cahier des charges Phase 3 (§3.5, WQ1-10 dans l'audit) exige un mécanisme
HACCP complet : plans de contrôle par point critique, non-conformité
**bloquante** (pas seulement documentée), certificat de conformité obligatoire
à la réception, alerte de contrôle en retard, dossier de rappel produit. L'audit
a confirmé qu'aucun équivalent partiel exploitable n'existe dans le dépôt
aujourd'hui — c'est le chantier le plus consequent du reste de la Phase 3, sans
socle partiel à étendre.

Deux options d'architecture ont été comparées avant d'engager le Bloc D (26 JT,
Vague 2) :

- **Option A — fusion dans `apps.stocks`** (proposition par défaut de l'agent
  de planification) : étendre `StkQualityState`/`StkRecall` existants pour
  porter la logique HACCP complète.
- **Option B — application dédiée `apps.quality`** (retenue, décision D2) :
  nouvelle app découplée, sur le même patron générique `content_type`/
  `object_id` déjà utilisé par `core.models.quality.QltInspection`/
  `core.models.risk.RiskItem`.

## Décision

**Option B retenue** : `apps.quality` est une application Django dédiée,
indépendante de `apps.stocks`.

Justification :

1. **HACCP est un domaine de conformité/audit à part entière**, pas une
   propriété du stock. Ses consommateurs réels dépassent largement `stocks` :
   réception achat (§3.1), sortie production (§3.4), livraison client — fusionner
   dans `apps.stocks` en aurait fait une dépendance transversale de conformité
   pour tout le dépôt, direction architecturale contraire à la discipline de
   couplage du modulith (`tests/architecture/test_module_boundaries.py`) :
   `stocks` gère le mouvement et la valorisation de la marchandise, pas la
   politique de conformité réglementaire d'un secteur (agroalimentaire).
2. **Précédent déjà établi dans le dépôt** : `core.models.quality.
   QltInspection`/`QltChecklistTemplate` (générique, `content_type`/
   `object_id`, déjà consommé par `apps.purchase` — chantier INT3, inspection
   de réception) prouve que ce dépôt préfère un module dédié/générique plutôt
   que d'incruster une logique de conformité dans une app métier. `apps.quality`
   suit le même réflexe architectural, mais comme application COMPLÈTE (pas
   seulement un modèle `core`) car HACCP porte une vraie logique métier
   (transitions bloquantes, validation de certificat obligatoire, alertes de
   retard) qui n'a pas sa place dans `core` non plus — `core` reste un socle
   générique léger, jamais le porteur des règles d'un régime de conformité
   précis.
3. **`apps.stocks` porte déjà deux primitives adjacentes mais distinctes** :
   `StkQualityState` (conséquence sur la quantité/valorisation d'une décision
   de classification, RG-STK-7) et `StkRecall` (journal de rappel piloté par la
   généalogie de lot). Cette ADR ne tranche PAS leur devenir — les garder
   telles quelles, les migrer partiellement vers `apps.quality`, ou les faire
   coexister via un lien `content_type` reste une décision explicitement
   différée au sprint **D5** du Bloc D (cf. plan, table Bloc D), une fois la
   vraie modélisation HACCP (D1-D4) livrée et le besoin réel de réconciliation
   mieux connu.

## Conséquences

- **Effort recalculé** : Bloc D passe de 17 JT (hypothèse fusion) à **26 JT**
  (application dédiée) — déjà intégré à la table de synthèse du plan Phase 3
  (`docs/planning/2026-09-cahier-des-charges-v3-phase3-plan.md` §3/§6). Le
  delta (+9 JT) couvre : scaffolding de module propre, références génériques
  `content_type`/`object_id` vers `purchase`/`mrp`/`sales` plutôt que des FK
  directes, surface `services/public.py` propre, entrées RBAC dédiées.
- **Ce sprint (P6) livre uniquement le squelette** : `apps.py`, `module.py`
  (dépendance déclarée : `core` uniquement, pour l'instant), `models.py` vide
  (aucun modèle avant D1), `services/public.py` vide (même situation initiale
  que `apps.helpdesk.services.public`/`apps.feasibility.services.public` à
  leur première étape). Aucune logique métier HACCP n'est livrée par ce
  sprint — elle arrive au Bloc D (D1 : plan/point critique/mesure/
  non-conformité ; D2 : certificat obligatoire à réception ; D3 : alerte
  contrôle en retard ; D4 : dossier de rappel avec immutabilité ; D5 :
  réconciliation avec `core.QltInspection`/`stocks.StkQualityState`/
  `StkRecall`).
- **Couplage** : aucune autre app ne doit importer `apps.quality.models` —
  toute consommation cross-app passera par `apps.quality.services.public` une
  fois peuplé, garde-fou déjà actif (`test_module_boundaries.py`), trivialement
  respecté tant que le module est vide.

## Alternatives rejetées

- **Fusion dans `apps.stocks`** (Option A) : rejetée, cf. justification
  ci-dessus (point 1) — ferait de `stocks` un hub de conformité transversal,
  contraire à sa responsabilité (mouvement/valorisation de stock).
- **Fusion dans `apps.core`** : rejetée — `core` doit rester un socle
  générique (voir `QltInspection`/`RiskItem`, volontairement minces et
  génériques), pas le porteur de règles métier propres à un régime de
  conformité sectoriel (HACCP est spécifique agroalimentaire, `core` sert
  tous les secteurs).
- **Statu quo (aucun mécanisme dédié)** : rejetée d'emblée — le cahier §3.5
  exige explicitement un blocage automatique et une mécanique HACCP réelle,
  sans équivalent partiel ; ne rien construire laisse un écart critique déjà
  identifié par l'audit comme priorité 5 sur 10 (§6).
