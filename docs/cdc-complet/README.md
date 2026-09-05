# Cahiers des charges WideHalo v3 — texte intégral

Les quatre cahiers des charges officiels du maître d'ouvrage (Life MDG,
septembre 2026), fournis sous forme de présentations, réécrits ici en Markdown
versionné. **Ce sont eux qui font foi** : tout audit, tout plan et toute
affirmation de conformité doivent pouvoir citer un critère de ces fichiers par
un lien, plutôt qu'une capture de diapositive que personne ne peut relire depuis
le dépôt.

| Phase | Périmètre | Durée annoncée | Critères | Document |
|---|---|---|---|---|
| **1** | CRM · Sales · Accounting (PCG 2005) · POS · Simulation financière · IA | 29 sprints | **52** | [`phase-1-…`](phase-1-crm-sales-accounting-pos-simulation-ia.md) |
| **2** | Business Intelligence · Forecast · Strategy · WhatsApp | 22 sprints | **38** | [`phase-2-…`](phase-2-bi-forecast-strategy-whatsapp.md) |
| **3** | Stock et entrepôt · Achats/Import/CREDOC · Production · Qualité et HACCP · Paie · extension Forecast | 38 sprints | **59** | [`phase-3-…`](phase-3-stock-achats-production-qualite-paie.md) |
| **4** | Socle de flux · API publique et webhooks · Conformité e-facture · Encaissement mobile · Flux bancaires · Bureautique · Commerce · Console de flux | 34 sprints | **54** | [`phase-4-…`](phase-4-connectivite-et-integrations.md) |
| | | | **203** | |

## Répartition des critères d'acceptation

| Phase | Familles de références |
|---|---|
| 1 | `CRM` 7 · `SAL` 8 · `ACC` 10 · `IA` 9 · `POS` 9 · `SIM` 9 |
| 2 | `BI` 10 · `FOR` 1-10 · `STR` 8 · `WA` 10 |
| 3 | `STK` 12 · `ACH` 10 · `PRD` 10 · `QUA` 10 · `PAY` 12 · `FOR` 11-15 |
| 4 | `FLX` 8 · `API` 7 · `EFA` 8 · `PAY` 8 · `BNK` 5 · `BUR` 5 · `COM` 4 · `MSG` 3 · `CON` 6 |

### Deux pièges de référencement

1. **`PAY-1` à `PAY-8` sont ambigus** : la Phase 3 les utilise pour la **paie**,
   la Phase 4 pour l'**encaissement mobile**. Toujours préfixer par la phase —
   `P3/PAY-1` (barèmes de paie versionnés) n'a rien à voir avec `P4/PAY-1`
   (bascule agrégateur ↔ raccordement direct).
2. **`FOR-*` est continu entre les phases** : `FOR-1` à `FOR-10` appartiennent au
   module Forecast de la Phase 2, `FOR-11` à `FOR-15` à son extension en Phase 3.
   La numérotation ne redémarre pas.

## Méthode de conversion

Extraction déterministe du XML des présentations (`ppt/slides/slideN.xml`), sans
reformulation : le texte est repris mot pour mot, les seuls ajouts sont
structurels (titres, listes, tableaux, ancres).

- Formes et tableaux lus dans l'ordre **(y, x)** de la diapositive, jamais dans
  l'ordre du XML — c'est ce qui empêche un tableau de passer avant le titre qui
  l'introduit.
- Niveaux de titre déduits de la taille de police du modèle : chapitre, section,
  chapeau, corps.
- Les **245 tableaux** sont rendus en tableaux Markdown. Un tableau coupé sur
  deux diapositives est recollé (l'en-tête répété est supprimé) : le document se
  lit par chapitre, pas par diapositive.
- Les schémas semi-graphiques sont conservés tels quels dans des blocs de code,
  indentation comprise.
- En-têtes, pieds de page et numéros de diapositive sont écartés.

### Contrôles passés à la génération

| Contrôle | Résultat |
|---|---|
| Complétude du texte (caractères hors espaces, source vs. Markdown) | 96,3 % à 96,5 % — l'écart est exactement l'en-tête/pied répété sur chaque diapositive et les en-têtes de tableau dédoublonnés au recollage |
| Références de critères retrouvées | **203 / 203**, réparties exactement comme le tableau ci-dessus |
| Tableaux Markdown bien formés | 202 tableaux, **0** ligne à largeur de colonne incohérente |

## Ce que ces documents ne sont pas

Ils décrivent ce qui est **demandé**, jamais ce qui est **livré**. Pour l'état
réel du code face à ces 203 critères, voir
[`docs/audit/2026-09-audit-complet-phases-1-4.md`](../audit/2026-09-audit-complet-phases-1-4.md),
et pour la fermeture des écarts
[`docs/planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md`](../planning/2026-09-plan-rattrapage-p1-p3-et-phase-4.md).
