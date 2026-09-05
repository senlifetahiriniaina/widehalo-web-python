# ADR — Abstraction du référentiel comptable PCG 2005 / SYSCOHADA (décision D10)

**Statut** : Acceptée (tranchée avec l'utilisateur — le plan de rattrapage la mettait
hors périmètre, l'arbitrage l'a remise en tête).
**Date** : 2026-09-05.
**Source** : [`docs/audit/2026-09-audit-complet-phases-1-4.md`](../audit/2026-09-audit-complet-phases-1-4.md)
§2.1 (critère `ACC-2`, verdict 🟡) et §3.5 ; cahier des charges
[`Phase 1 §12.2 et §13.3`](../cdc-complet/phase-1-crm-sales-accounting-pos-simulation-ia.md).
**Chantier** : D10, ≈ 42 JT, six sprints.

## Contexte

Le cahier des charges Phase 1 §12.2 pose une exigence que le dépôt ne tient
qu'à moitié, et il la pose comme un invariant produit et non comme un réglage :

> « **Madagascar n'est pas membre de l'OHADA.** […] Ce sont deux référentiels
> distincts : plan de comptes, états financiers et logiques de retraitement diffèrent.
> Toute confusion entre les deux produit une comptabilité non conforme. Cette
> distinction est un invariant du produit, pas un détail de paramétrage. »

Et il en tire deux règles opposables, reprises en §13.3 :

> « Aucun numéro de compte n'apparaît en dur dans le code : les automatismes passent
> par les comptes par défaut du tenant, eux-mêmes rattachés au plan du référentiel
> actif. »
> « Les états financiers sont produits selon la structure du référentiel actif du
> tenant, jamais selon une structure codée en dur. »

**Ce qui est déjà tenu, et qu'il ne faut surtout pas reconstruire.** L'audit classait
l'abstraction en « absente » ; c'est vrai de la structure, faux de la moitié du
travail :

- `AccAccount.type` (11 valeurs fonctionnelles) et `AccJournal.type` (7 valeurs) sont
  un vocabulaire abstrait, sans référence au PCG. **Les six automatismes de
  `apps/accounting/services/public.py` résolvent tous leur compte par ce champ** —
  aucun ne passe par un numéro littéral.
- `reports.py::balance_sheet` est piloté à 100 % par `type` et `is_current` : le bilan
  est déjà portable.
- Les treize apps consommatrices passent par `services.public` avec des UUID nus ou
  `account_id=None` — aucune n'importe `apps.accounting.models`.

**Ce qui manque réellement**, par ordre de poids : la table de passage
`reports.py::_CR_NATURE_MAPPING` (12 postes, ~60 préfixes de compte « retranscrits
verbatim de l'Annexe II du PCG 2005 ») et la cascade des neuf soldes intermédiaires
codée en Python ; l'absence de toute entité « référentiel » et « plan de comptes » ;
l'absence d'une table de comptes par défaut du tenant, les automatismes se rabattant
sur un `.first()` **sans `order_by`**, donc non déterministe ; et les classifications
par classe PCG en dur (`account_class=6`, `=7`, `==2`, `_CLASSIFICATION_BY_PCG_CLASS`,
`_FINANCIAL_INCOME_PREFIXES = ("76", "77")`).

**Un défaut fonctionnel constaté au passage** : dans les quatre chemins de création ou
de réinitialisation de tenant (`create_tenant.py`, `auth_web.py`, `tenant_reset.py`,
`seed_core.py`), `load_pcg2005` est appelé **inconditionnellement**, par un
`call_command` dont le nom est en dur. Un tenant créé avec `--country=SN` reçoit
aujourd'hui le plan comptable malgache. Et `CountryDefaultsProfile.chart_of_accounts_code`,
semé à `"PCG2005"` par la migration `core/0011`, **n'est lu par personne**.

## Options comparées

### Option A — le schéma littéral du cahier : les tables dans `apps.core`

Le §12.2 nomme les tables `core_accounting_framework`, `core_chart_of_accounts`,
`core_account`, et place `acc_journal_entry_line`/`acc_journal_entry`/`acc_journal` en
face. Suivre le schéma à la lettre imposerait de déplacer `AccAccount` de
`apps.accounting` vers `apps.core`.

### Option B — tout dans `apps.accounting` (retenue)

Le référentiel, le plan de comptes, les comptes par défaut et la table de transposition
vivent dans `apps.accounting`, exposés aux autres modules par
`accounting.services.public`.

## Décision

**Option B.** Le référentiel comptable est modélisé dans `apps.accounting`.

Justification :

1. **La déviation au schéma du cahier est déjà acquise et assumée depuis trois
   phases.** `AccAccount` est `acc_account` dans `apps.accounting`, pas `core_account`
   dans `apps.core`. Le préfixe `core_` du §12.2 est une convention rédactionnelle du
   document, pas une contrainte d'architecture : ce que le cahier exige réellement est
   la **règle** « tenant → pays → framework actif → plan de comptes → comptes
   autorisés », qui est indépendante de l'app d'accueil. Déplacer 40 modèles pour
   respecter un préfixe coûterait une migration de schéma majeure pour zéro gain
   fonctionnel.
2. **`core` doit rester un socle générique léger.** Le principe a été posé et justifié
   par l'ADR précédente ([`2026-09-adr-qualite-haccp-app-dediee.md`](2026-09-adr-qualite-haccp-app-dediee.md)) :
   « `core` reste un socle générique léger, jamais le porteur des règles d'un régime de
   conformité précis ». Un plan comptable national est exactement cela. Le référentiel
   comptable est au module comptable ce que le plan de contrôle HACCP est au module
   qualité.
3. **La règle de couplage du modulith rend l'option A inutile.** Les autres modules
   n'ont jamais besoin d'un objet `AccAccount` : ils manipulent des UUID et passent par
   `accounting.services.public`, ce que `tests/architecture/test_module_boundaries.py`
   vérifie déjà. Placer les tables dans `core` pour « les rendre accessibles » répondrait
   à un problème qui n'existe pas.
4. **`CountryDefaultsProfile` reste dans `core` et devient enfin utile.** C'est lui qui
   porte `country_code → chart_of_accounts_code` ; `accounting` le lit pour résoudre le
   framework. Le sens de la dépendance est celui que le dépôt pratique déjà (`core` ne
   connaît pas `accounting`, `accounting` lit `core`), et le `call_command` par chaîne
   utilisé aujourd'hui dans les quatre chemins de création de tenant reste le mécanisme
   d'appel, précisément pour ne pas créer une dépendance déclarée `core → accounting`.

## Périmètre — ce que D10 livre, et ce qu'il ne livre pas

**Livré** : les entités `AccFramework`, `AccChartOfAccounts`, `AccTenantDefaultAccount`
et `AccountMapping` ; le rattachement de `AccAccount` à un plan ; la structure des états
financiers portée par le référentiel et non par le code ; le chargement du plan piloté
par le pays du tenant ; et la garde d'intégration continue qui rend `ACC-2` opposable.

**Non livré, et il faut le dire pour ne pas laisser croire l'inverse** :

- **Un plan SYSCOHADA complet et des états financiers OHADA conformes.** Le jeu
  SYSCOHADA livré est un **jeu de démonstration minimal**, dont la seule fonction est de
  prouver par un test qu'aucune structure n'est codée en dur. Il porte la même réserve
  que le PCG 2005 déjà en place : **non validé par un expert-comptable**, à ne jamais
  présenter comme une nomenclature faisant autorité. Ouvrir un tenant OHADA réel
  suppose un chantier de localisation distinct.
- **Le bloc fiscal malgache.** `AccTaxCalendar` et ses 11 déclarations DGI,
  `fiscal_export.CANEVAS_NOTES`, `dcom.py`, `ircm.py`, `local_tax.py`,
  `tax_returns.py` sont couplés au **Code général des impôts malgache**, pas au plan
  comptable. Un tenant OHADA n'en voudrait pas, mais leur remplacement est un autre
  chantier, étranger au critère ACC-2. Seule exception traitée ici : les points où ces
  fichiers lisent une **classe comptable** (`_CLASSIFICATION_BY_PCG_CLASS`,
  `_FINANCIAL_INCOME_PREFIXES`), qui deviennent des attributs du référentiel.
- **La devise au niveau modèle.** Les défauts `currency = "MGA"` sur `AccAccount`,
  `AccJournal`, `AccMove` et `AccMoveLine`, et surtout `AccExchangeRate.rate_to_mga`
  dont le **nom de colonne code la devise**, restent en l'état : leur reprise est une
  migration de schéma sur des tables volumineuses pour un gain nul tant qu'un seul
  référentiel est actif.
- **L'entrepôt décisionnel.** `analytics.AnFactEcriture.compte_classe_pcg` fige le nom
  PCG dans le schéma analytique (migration `analytics/0001_initial`). Même
  raisonnement : dette réelle, reprise coûteuse, gain nul aujourd'hui.

Ces quatre points sont à rouvrir ensemble au moment du « pays #2 », avec le reste de la
localisation.

## Conséquences

1. **La table de transposition `AccountMapping` est livrée vide.** Le cahier le demande
   explicitement — « aucune utilité immédiate en Phase 1 […] livrée malgré tout parce
   que son coût est faible maintenant et qu'elle sera la pièce centrale du déploiement
   OHADA ». Livrer la coquille maintenant évite de reprendre le modèle d'écritures plus
   tard.
2. **La garde `test_no_hardcoded_account_numbers.py` change de nature.** Sa docstring
   reconnaît aujourd'hui ne pas prétendre résoudre ACC-2 et exempte
   `services/reports.py` — c'est-à-dire précisément le fichier qui porte la structure
   des états financiers. Après D10-3, cette exemption est retirée (**55 littéraux
   disparaissent avec `_CR_NATURE_MAPPING`**) et le motif est élargi à ses trois angles
   morts : codes à 1-2 chiffres, littéraux entiers, répertoire `management/`.
3. **Les automatismes deviennent déterministes.** Le `.first()` sans `order_by` des six
   gaps de `services/public.py` est remplacé par une résolution explicite via
   `AccTenantDefaultAccount`, avec repli sur `type` et journalisation quand le registre
   est incomplet. C'est une correction de défaut, pas seulement une abstraction.
4. **Le budget d'architecture a été relevé en conséquence** (+33 %, 415/800/320, cf.
   `config/settings/base.py`) : D10 ajoute ≈ 4 modèles et un écran de paramétrage, et
   le plafond d'écrans était saturé exactement à 240/240.
5. **La réserve OECFM se propage au référentiel.** Le PCG 2005 chargé par le dépôt est
   déjà un jeu « représentatif et simplifié, non validé par un expert-comptable »
   (docstring de `chart_of_accounts.py`). Rendre le référentiel paramétrable ne valide
   rien : la réserve doit être portée par `AccFramework` lui-même, visible à l'écran,
   et non enfouie dans une docstring.
