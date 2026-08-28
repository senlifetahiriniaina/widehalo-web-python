# Formats d'import comptable, caisse et référentiels

Ce document décrit les formats de fichier acceptés par les assistants
d'import de l'application, colonne par colonne. Il couvre cinq imports
réellement implémentés et testés : plan comptable et journal de caisse
(§2-3), puis partenaires, catalogue et quantités initiales de stock (§4),
ainsi que la qualification/identification universelle des données
importées (§6, chantier RG-QUALIF) et l'import de factures client/
fournisseur qu'elle démontre de bout en bout.

## 1. Principes généraux

- **Jamais de publication automatique.** Un import ne crée que des écritures
  comptables `brouillon` (`AccMove.state=draft`) — jamais `posted`. Elles
  suivent ensuite le circuit normal de validation du module `accounting`.
- **Statut « anomalie » plutôt que rejet ou intégration silencieuse.** Une
  ligne dont l'application ne peut pas déduire un compte, une date ou une
  caisse valides avec certitude est mise en attente de résolution humaine
  (`AccImportRow.status=anomaly`), jamais résolue par une supposition. Les
  autres lignes du même fichier s'importent normalement — une ligne
  problématique ne bloque jamais tout le lot (contrairement à l'import du
  plan comptable, qui reste tout-ou-rien, cf. § 2).
- **Mécanisme de version + alias de colonnes.** Chaque format porte un
  numéro de version entier et une table d'alias qui associe un champ
  canonique à plusieurs libellés de colonne acceptés (accents/casse/espaces
  ignorés). C'est le mécanisme concret de compatibilité ascendante — cf.
  § 5.
- **Aucune donnée réelle d'un client comme fixture.** Les jeux de données
  utilisés pour valider ces formats en test sont **synthétiques**,
  reproduisant la forme des colonnes et chaque catégorie d'anomalie
  observée, jamais les données financières réelles d'une entreprise.

## 2. Format d'import du plan comptable

Fichier `.xlsx`, une ligne d'en-tête suivie d'une ligne par compte.
Endpoint : `POST /api/v1/accounting/imports/chart-of-accounts` (upload
multipart, champ `file`) ; écran : `/accounting/config/imports/chart-of-accounts/`.

| Champ canonique   | Libellés de colonne acceptés                                            | Type                | Obligatoire | Description |
|--------------------|---------------------------------------------------------------------------|----------------------|-------------|-------------|
| `code`             | `Code`, `N° de compte`, `N° de compte proposé`                            | texte                | oui         | Code du compte PCG (ex. `571`). |
| `name`             | `Name`, `Intitulé`, `Intitulé du compte (PCG 2005)`                       | texte                | oui         | Libellé du compte. |
| `account_class`    | `Account_class`, `Classe`, `Classe PCG`                                   | entier (1-7)         | oui         | Classe PCG du compte. |
| `type`             | `Type`                                                                     | texte (valeur enum)  | non*        | Valeur canonique de `AccAccount.type` (ex. `cash`, `expense`, `income`...). |
| `nature`           | `Nature`                                                                   | texte (libellé libre)| non*        | Libellé descriptif français (ex. « Trésorerie », « Charge ») — utilisé pour déduire `type` si la colonne `type` est absente, via une table de correspondance best-effort (voir ci-dessous). |
| `categorie_caisse` | `Categorie_caisse`, `Catégorie de caisse LIFE MDG`, `Catégorie de caisse`  | texte                | non         | Si renseignée, crée/actualise une correspondance `AccCashCategoryMapping` (catégorie de caisse → ce compte), utilisée par l'import du journal de caisse (§ 3). |

\* Au moins l'une des deux colonnes `type`/`nature` doit permettre de
résoudre un type de compte valide — sinon la ligne est en erreur.

**Table de correspondance `nature` → `type`** (best-effort, jamais une
supposition silencieuse — toute valeur de `nature` absente de cette table
produit une erreur de ligne explicite plutôt qu'un type deviné) :

| `nature` (libellé français) | `type` résolu |
|---|---|
| Actif immobilisé | `asset` |
| Actif (tiers) | `receivable` |
| Passif financier | `liability` |
| Passif (tiers) | `payable` |
| Trésorerie | `cash` |
| Charge / Charge financière | `expense` |
| Produit / Produit (contra) | `income` |

**Comportement du commit** : idempotent par code — un compte dont le code
existe déjà pour ce tenant est **ignoré** (jamais écrasé), compté
séparément dans le résumé (`skipped_existing_count`) plutôt que traité comme
une erreur bloquante. En revanche, la **validation** (champs obligatoires,
types) reste tout-ou-rien : si une seule ligne échoue la validation
structurelle, **rien n'est enregistré** (`row_errors` détaille chaque ligne
en échec avec son index et ses erreurs par champ).

**Préparation du fichier avant import** : la feuille importée doit contenir
**uniquement** la ligne d'en-tête suivie des lignes de comptes — aucune
ligne de titre/légende avant l'en-tête, aucun commentaire ou paragraphe de
synthèse après la dernière ligne de compte. Le lecteur xlsx ignore les
lignes entièrement vides, mais pas une ligne contenant du texte libre dans
une seule cellule (ex. une note explicative en bas de feuille) — une telle
ligne est lue comme une ligne de compte invalide et fait échouer tout
l'import (comportement voulu : mieux vaut un refus explicite, avec le
numéro de ligne fautif dans `row_errors`, qu'une tentative de deviner où
s'arrête le tableau). Un classeur exporté avec des feuilles d'analyse
annexes (notes méthodologiques, structure par classe, incohérences
relevées...) doit isoler la feuille du plan comptable proprement dit — ou en
extraire une copie propre — avant import.

Exemple (extrait) :

```text
Classe | Code | Intitulé          | Type    | Catégorie de caisse
5      | 571  | Caisse principale | cash    | Caisse
6      | 601  | Achats matières   | expense | Achat matière première
```

## 3. Format d'import du journal de caisse / trésorerie

Fichier `.xlsx`, une ligne d'en-tête suivie d'une ligne par opération.
Endpoint : `POST /api/v1/accounting/imports/cash-journal` (upload
multipart, champ `file`) ; écran : `/accounting/config/imports/cash-journal/`,
avec un écran de résolution des lignes en anomalie par lot
(`/accounting/config/imports/cash-journal/<batch_id>/`).

Ce format est calqué sur un export réel de journal de caisse (colonnes
`DATE`/`CAISSE`/`CATEGORIE`/`EXCLU DES TOTAUX (solde periode)`/`CODE PCG
DETECTE`/`LIBELLE`/`ENTREE`/`SORTIE`, entre autres) — c'est le cas d'usage
qui a motivé ce chantier.

| Champ canonique      | Libellés de colonne acceptés                                | Type              | Obligatoire | Description |
|-----------------------|----------------------------------------------------------------|--------------------|-------------|-------------|
| `date`                 | `Date`                                                          | date               | oui         | Date de l'opération. |
| `date_estimee`         | `Date estimee`                                                  | date               | non         | Traçabilité uniquement (`raw_data`), jamais utilisée pour résoudre une période. |
| `caisse`               | `Caisse`                                                        | texte              | oui         | Identifie la caisse cible — résolue **par ligne** vers un `AccJournal` de type `cash` existant, par code ou nom (insensible casse/accents). Plusieurs caisses physiques peuvent coexister dans un même fichier. |
| `categorie`            | `Categorie`                                                     | texte              | non*        | Catégorie de caisse propre à l'entreprise — résolue vers un compte via `AccCashCategoryMapping` (§ 2) si aucun compte explicite n'est fourni. |
| `exclu_des_totaux`     | `Exclu des totaux (solde periode)`, `Exclu des totaux`          | texte (`Oui`/autre)| non         | Ligne de solde de période/report à nouveau — **jamais transformée en écriture**, exclue de toute résolution de compte/caisse/période pour éviter un double comptage. |
| `compte_pcg`           | `Compte pcg`, `Code pcg detecte`                                | texte              | non*        | Code de compte explicite — **prime toujours** sur la résolution par catégorie quand il est renseigné et valide. |
| `libelle`              | `Libelle`                                                       | texte              | non         | Libellé de l'écriture générée. |
| `entree`               | `Entree`                                                        | décimal            | non**       | Montant en entrée (encaissement). |
| `sortie`               | `Sortie`                                                        | décimal            | non**       | Montant en sortie (décaissement). |
| `nature_origine`, `type_piece`, `partenaire`, `client`, `fournisseur` | `Nature d'origine`, `Type piece`, `Partenaire`, `Client`, `Fournisseur` | texte | non | Champs purement informatifs, conservés dans `raw_data` (traçabilité/débogage) — jamais utilisés pour résoudre un compte, une caisse, une période, ni rapprochés d'un partenaire réel. |

\* Une ligne doit fournir soit `compte_pcg` (un code de compte existant),
soit une `categorie` déjà mappée vers un compte (§ 2) — sinon anomalie.
\*\* Une ligne doit renseigner soit `entree`, soit `sortie` (jamais les deux),
sauf si elle est marquée `exclu_des_totaux`.

**Chaque ligne propre produit une vraie écriture en partie double** (deux
lignes de mouvement) : compte de caisse/banque du journal résolu en
contrepartie du compte résolu (débit caisse/crédit compte résolu pour une
entrée ; l'inverse pour une sortie).

### Codes d'anomalie

| Code | Signification |
|---|---|
| `MONTANT_ENTREE_ET_SORTIE` | Les deux colonnes `ENTREE` et `SORTIE` sont renseignées simultanément sur la même ligne. |
| `MONTANT_NUL` | Ni `ENTREE` ni `SORTIE` ne sont renseignées, et la ligne n'est pas marquée `EXCLU DES TOTAUX`. |
| `DATE_MANQUANTE` | Aucune date exploitable sur la ligne. |
| `DATE_INVALIDE` | Date hors bornes raisonnables (avant l'an 2000, ou plus d'un an dans le futur). |
| `PERIODE_FERMEE_OU_INEXISTANTE` | Aucune période comptable ouverte ne couvre cette date pour ce tenant. |
| `COMPTE_INCONNU` | Un code de compte est fourni explicitement (`COMPTE PCG`) mais n'existe pas dans le plan comptable du tenant. |
| `CATEGORIE_NON_MAPPEE` | Aucun compte fourni explicitement, et la catégorie de caisse n'a pas (encore) de correspondance vers un compte. |
| `CAISSE_INCONNUE` | La caisse indiquée ne correspond à aucun journal de type caisse existant, ou ce journal n'a pas de compte de caisse configuré. |

Une anomalie de niveau **lot** (pas ligne) est également signalée dans
`batch_warnings` du résumé : une même catégorie de caisse résolue vers deux
comptes différents au sein du même import (incohérence de saisie à
corriger).

### Résolution d'une ligne en anomalie

`POST /api/v1/accounting/imports/cash-journal/rows/{row_id}/resolve` (ou
formulaire de l'écran de détail du lot) : corrige la ligne — compte choisi
manuellement, date corrigée, ou ligne écartée volontairement
(`discard=true`, ex. doublon). Si la ligne devient propre, une écriture
brouillon est créée et son statut passe à `resolved` ; sinon elle reste
`anomaly` avec les codes mis à jour. **Jamais de résolution devinée** : le
compte ou la date corrigés proviennent toujours d'une action humaine
explicite, jamais d'une heuristique.

Exemple (extrait) :

```text
Date       | Caisse | Categorie        | Compte pcg | Libelle          | Entree | Sortie
2026-01-05 | Caisse | Vente comptant   |            | Vente au comptant| 50000  |
2026-01-06 | Caisse |                  | 601        | Achat fournitures|        | 12000
```

## 4. Imports référentiels (partenaires, catalogue, stocks)

Trois imports supplémentaires, construits sur le même socle
(`apps/core/services/import_xlsx.py` pour la lecture, alias d'en-têtes,
numéro de version) mais avec des choix de commit différents selon que la
ligne référence ou non une entité externe qu'il faut pouvoir résoudre plus
tard :

- **Partenaires** et **catalogue** sont **tout-ou-rien** (comme le plan
  comptable, §2) : une ligne invalide n'a pas de notion de « corriger plus
  tard » utile côté utilisateur (contrairement à un compte ou une caisse
  inconnue du journal de caisse) — rien n'est enregistré tant que le
  fichier n'est pas corrigé, `row_errors` détaille chaque ligne en échec.
- **Stocks (quantités initiales)** utilise en revanche une **file
  d'anomalies** (comme le journal de caisse, §3) : une ligne référence
  jusqu'à trois entités externes (variante, entrepôt, emplacement) et une
  référence non reconnue ne doit jamais bloquer les autres lignes propres
  du même classeur.

### 4.1 Partenaires (`apps.partners.models.Partner`)

Endpoint : `POST /api/v1/partners/imports/partners` (upload multipart,
champ `file`) ; écran : `/partners/imports/`.

| Champ canonique | Libellés de colonne acceptés | Type | Obligatoire | Description |
|---|---|---|---|---|
| `code` | `Code` | texte | non | Code partenaire → `Partner.reference`. Si fourni, l'import est **idempotent par code** (un code déjà utilisé par ce tenant est ignoré, jamais écrasé) ; si absent, une référence est générée (séquence `PART-<année>-NNNN`, comme la création manuelle) et chaque ré-import crée une nouvelle fiche. |
| `name` | `Name`, `Nom`, `Raison sociale` | texte | oui | Raison sociale. |
| `nif` | `NIF` | texte | non | Numéro d'identification fiscale. Un NIF déjà porté par un autre partenaire du même tenant **n'est jamais bloquant** : une `DuplicateAlert` est journalisée pour revue humaine (même comportement que la création manuelle via `services.onboarding.create_partner`). |
| `roles` | `Roles`, `Role` | liste (texte, séparateur `;`) | non | Parmi `client`/`fournisseur`/`transporteur`/`sous_traitant` (libellés français acceptés, traduits vers les valeurs canoniques du modèle `client`/`supplier`/`carrier`/`subcontractor` — ces valeurs canoniques sont aussi acceptées directement). Une valeur non reconnue n'est **jamais devinée** : elle est laissée telle quelle, ce qui fait échouer la validation (erreur de ligne explicite). |
| `credit_limit_mga` | `Credit_limit_mga`, `Plafond de crédit`, `Limite de crédit` | décimal | non | Plafond de crédit en Ariary (0 = pas de plafond). |
| `email`, `phone`, `address` | `Email` ; `Phone`, `Téléphone` ; `Address`, `Adresse` | texte | non | Colonnes lues (compatibilité du format déjà documenté avant l'implémentation de cet écran) mais **non persistées** : `Partner` ne porte aujourd'hui aucun champ coordonnées. Une ligne qui les renseigne est comptée dans `coordinates_ignored_count` du résumé, jamais silencieusement perdue sans trace. |

### 4.2 Catalogue (`apps.catalog.models.ProductTemplate`/`ProductVariant`/`TextileSpec`)

Endpoint : `POST /api/v1/catalog/imports/catalog` (upload multipart, champ
`file`) ; écran : `/catalog/config/imports/`.

Une ligne = un gabarit produit (`ProductTemplate`). `uom` doit référencer
une unité de mesure **déjà existante** pour ce tenant (FK obligatoire,
jamais créée automatiquement — une unité de mesure engage des conversions
que l'import n'a pas à deviner) ; `category` est créée à la volée si elle
n'existe pas encore (simple classification par nom).

| Champ canonique | Libellés de colonne acceptés | Type | Obligatoire | Description |
|---|---|---|---|---|
| `template_code` | `Template_code`, `Code` | texte | non | Code du gabarit → `ProductTemplate.reference`. Import **idempotent par code**, même principe que les partenaires (§4.1). |
| `template_name` | `Template_name`, `Nom`, `Name` | texte | oui | Nom du produit. |
| `category` | `Category`, `Catégorie` | texte | non | Catégorie de catalogue (`Category`, créée si absente). |
| `uom` | `Uom`, `Unité`, `Unité de mesure` | texte | oui | Code d'une `UnitOfMeasure` existante — code inconnu : erreur de ligne explicite. |
| `variant_attributes` | `Variant_attributes`, `Attributs de variantes`, `Attributs` | texte (`attribut=valeur;...`) | non | Amorce les attributs générateurs de variantes du gabarit (`Attribute`/`AttributeValue`, créés si absents) — **au maximum 2 attributs distincts** par ligne (RG catalogue). La génération effective des variantes est déléguée à `apps.catalog.services.variants.generate_variants` (plafond de 50 combinaisons, jamais réimplémenté ici). |
| `material`, `composition`, `weight_gsm`, `width_cm` | `Material`/`Matière` ; `Composition` ; `Weight_gsm`/`Grammage` ; `Width_cm`/`Laize` | texte/décimal | non | Spécification textile (`TextileSpec`), créée pour chaque variante générée si au moins un de ces champs est renseigné. |

### 4.3 Stocks — quantités initiales (`apps.stocks.models.StkQuant`, via `StkMove`)

Fichier `.xlsx`, une ligne d'en-tête suivie d'une ligne par couple
produit/emplacement. Endpoint : `POST
/api/v1/stocks/imports/initial-quantities` (upload multipart, champ
`file`) ; écran : `/stocks/imports/`, avec un écran de résolution des
lignes en anomalie par lot (`/stocks/imports/<batch_id>/`).

| Champ canonique | Libellés de colonne acceptés | Type | Obligatoire | Description |
|---|---|---|---|---|
| `variant_code` | `Variant_code`, `Code variante`, `Référence variante` | texte | oui | Référence de la variante produit (`ProductVariant.reference`), résolue via `apps.catalog.services.public.get_variant_id_by_reference` (règle de couplage n°1 — jamais un import direct de `apps.catalog.models` depuis `stocks`). |
| `warehouse_code` | `Warehouse_code`, `Entrepôt`, `Code entrepôt` | texte | oui | Code d'un `StkWarehouse` existant (insensible à la casse). |
| `location_code` | `Location_code`, `Emplacement`, `Code emplacement` | texte | oui | Code d'un `StkLocation` existant au sein de l'entrepôt ci-dessus. |
| `qty` | `Qty`, `Quantité`, `Quantité initiale` | décimal | oui | Quantité d'ouverture — doit être strictement positive. |
| `unit_cost_mga` | `Unit_cost_mga`, `Coût unitaire`, `Coût unitaire MGA` | décimal | non | Coût unitaire d'ouverture (valorisation FIFO de la première couche créée). |
| `lot_reference` | `Lot_reference`, `Lot`, `Numéro de lot` | texte | non | Numéro de lot — un `StkLot` est créé s'il n'existe pas encore pour ce couple (produit, nom de lot). |

**Chaque ligne propre produit un `StkMove` de type `ajustement`, déjà
VALIDÉ** (pas seulement brouillon, à la différence de l'import comptable) :
depuis un emplacement virtuel dédié à l'ouverture de stock
(`StkLocation.type=inventaire`, code `STOCK-INITIAL`, un par entrepôt,
créé au premier import) vers l'emplacement interne demandé — une quantité
initiale n'a pas de circuit d'approbation à suivre après coup, l'acte
d'import EST la confirmation (même principe que
`services.inventory.validate_inventory`, qui valide immédiatement les
mouvements d'écart qu'il génère).

### Codes d'anomalie

| Code | Signification |
|---|---|
| `VARIANTE_INCONNUE` | `variant_code` ne correspond à aucune variante du tenant. |
| `ENTREPOT_INCONNU` | `warehouse_code` ne correspond à aucun entrepôt du tenant. |
| `EMPLACEMENT_INCONNU` | `location_code` ne correspond à aucun emplacement de l'entrepôt résolu. |
| `QUANTITE_INVALIDE` | `qty` absente, non numérique ou inférieure ou égale à zéro. |

### Résolution d'une ligne en anomalie

`POST /api/v1/stocks/imports/initial-quantities/rows/{row_id}/resolve` (ou
formulaire de l'écran de détail du lot) : corrige la ligne (code variante,
entrepôt, emplacement, quantité) ou l'écarte volontairement
(`discard=true`). Si la ligne devient propre, le mouvement validé est
créé et son statut passe à `resolved` ; sinon elle reste `anomaly` avec
les codes mis à jour. **Jamais de résolution devinée**, même discipline
que la résolution d'une ligne du journal de caisse (§3).

## 5. Compatibilité ascendante et évolution du format

Chaque format porte un numéro de version entier
(`CHART_OF_ACCOUNTS_FORMAT_VERSION`, `CASH_JOURNAL_FORMAT_VERSION`,
actuellement `1` chacun) et une table d'alias d'en-têtes qui associe un
champ canonique à l'ensemble des libellés de colonne acceptés — c'est ce
mécanisme qui permet à un fichier déjà en circulation aujourd'hui (colonnes
`"CODE PCG DETECTE"`, `"N° de compte proposé"`, etc.) et à un fichier écrit
avec les libellés canoniques documentés ci-dessus d'être tous deux acceptés
sans modification.

- **Évolution compatible** (ajout d'un synonyme de colonne, ajout d'un
  champ optionnel) : ajouter un alias à la table existante, **sans**
  incrémenter le numéro de version — un fichier déjà en circulation continue
  de s'importer sans changement.
- **Évolution incompatible** (renommage d'un champ obligatoire, changement
  de sémantique d'une colonne existante) : incrémenter le numéro de version
  et ajouter une nouvelle entrée dans un registre `{version: table_d_alias}`
  — même patron que `MANIFEST_MIGRATIONS` de
  `apps/core/services/tenant_export.py`. Un fichier annonçant une version
  supérieure à celle supportée par l'application en cours est **refusé
  explicitement** (`ValueError`, aucune ligne traitée), jamais lu de façon
  optimiste.
- **Absence de marqueur de version** dans le fichier importé : la version 1
  (actuelle) est supposée par défaut — c'est le cas de tout fichier déjà en
  circulation aujourd'hui, y compris les fichiers ayant servi de référence à
  la conception de ce format.

Exemple concret de ce que donnerait une V2 du format de journal de caisse
(hypothétique, pas encore implémentée) : si un futur besoin exigeait de
distinguer un moyen de paiement mobile money par ligne, on ajouterait un
champ optionnel `payment_method` avec ses propres alias — compatible, donc
sans changement de version. Si à l'inverse la colonne `CAISSE` devait être
remplacée par un identifiant structuré incompatible avec la résolution par
code/nom actuelle, la version serait incrémentée à `2` et l'ancien
comportement resterait disponible pour tout fichier n'annonçant pas
explicitement la version `2`.

## 6. Qualification et identification universelle des données importées (RG-QUALIF)

### 6.1 Principe

Avant ce chantier, deux imports (journal de caisse, stock) bloquaient déjà
une ligne dont une référence externe ne pouvait pas être résolue avec
certitude (`status=anomaly`, aucun document créé) — mais **aucun
importeur ne tentait jamais d'identifier un partenaire**, et une
référence non reconnue bloquait systématiquement la ligne même quand une
valeur par défaut sûre existait (compte d'attente, emplacement virtuel).

Ce chantier généralise un principe simple, appliqué à chaque type de
référence externe d'une ligne importée : **s'il existe une valeur par
défaut sûre, l'utiliser immédiatement et matérialiser le document
provisoire ; sinon, ne jamais matérialiser de document, mais ne jamais
non plus bloquer le reste du lot.** Chaque code d'anomalie est donc classé
une fois pour toutes dans un registre **défaultable / non-défaultable**
(§6.2), remplaçant l'ancienne distinction "anomalie référentielle
souple" / "anomalie structurelle bloquante".

Vocabulaire de statut unifié, partagé par `AccImportRow` (journal de
caisse), `StkImportRow` (stock) et le nouveau `AccInvoiceImportRow`
(factures) :

| Statut | Signification |
|---|---|
| `ok` | Ligne parfaitement identifiée, aucun placeholder utilisé. |
| `needs_qualification` | Document provisoire matérialisé sur au moins un placeholder — en attente qu'un humain fournisse l'entité réelle (`qualify_import_row`). |
| `pending_approval` | Qualification soumise, en attente d'une décision d'approbation (`ApprovalRequest` créée par `qualify_import_row`). |
| `qualified` | Qualification approuvée (ou aucune approbation requise) — la ligne ne référence plus aucun placeholder. |
| `unresolvable` | Anomalie non-défaultable — aucun document créé, ligne reste visible dans la même file, ne bloque jamais le reste du lot. |
| `resolved` | Anomalie `unresolvable` corrigée manuellement (`resolve_import_row`, mécanisme antérieur à RG-QUALIF, conservé pour les codes qui restent bloquants). |
| `discarded` | Ligne écartée volontairement par un humain. |

### 6.2 Registre défaultable / non-défaultable par code d'anomalie

**Journal de caisse** (`apps.accounting.services.cash_journal_import`) :

| Code | Défaultable ? | Valeur par défaut | Champ trace |
|---|---|---|---|
| `COMPTE_INCONNU` | Oui | Compte d'attente (`chart_of_accounts.ensure_suspense_account`, code `471`) | `uses_placeholder_account` |
| `CATEGORIE_NON_MAPPEE` | Oui | Compte d'attente (idem) | `uses_placeholder_account` |
| `PARTENAIRE_NON_IDENTIFIE` | Oui | Partenaire placeholder du rôle concerné (`partners.services.public.ensure_default_partner`) | `uses_placeholder_partner` |
| `DATE_MANQUANTE` / `DATE_INVALIDE` | Oui | Date du jour si une période ouverte la couvre, sinon date de début de la période ouverte la plus récente | `uses_default_date` |
| `MONTANT_NUL` | **Non** | — fabriquer un montant serait fabriquer un fait financier | — |
| `MONTANT_ENTREE_ET_SORTIE` | **Non** | — direction du mouvement ambiguë | — |
| `CAISSE_INCONNUE` | **Non, par exception délibérée** | — une caisse générique fausserait la position de trésorerie par caisse, même prudence qu'un montant ambigu | — |
| `PERIODE_FERMEE_OU_INEXISTANTE` (date explicite valide mais hors de toute période ouverte) | **Non** | — inventer une période comptable n'a pas de repli sûr | — |

**Import de stock** (`apps.stocks.services.stock_import`) :

| Code | Défaultable ? | Valeur par défaut | Champ trace |
|---|---|---|---|
| `VARIANTE_INCONNUE` | Oui | Variante placeholder (`catalog.services.public.ensure_default_variant`) | `uses_placeholder_variant` |
| `EMPLACEMENT_INCONNU` | Oui | Emplacement virtuel "Zone à qualifier" de l'entrepot (`services.defaults.ensure_unqualified_location`) | `uses_placeholder_location` |
| `ENTREPOT_INCONNU` | **Non** | — aucun entrepôt par défaut sûr, un `StkMove` a toujours besoin d'un entrepôt réel | — |
| `QUANTITE_INVALIDE` | **Non** | — inventer une quantité fabriquerait un fait de stock | — |

**Import de factures** (`apps.accounting.services.invoice_import`, nouveau) :

| Code | Défaultable ? | Valeur par défaut | Champ trace |
|---|---|---|---|
| `PARTENAIRE_NON_IDENTIFIE` | Oui | Partenaire placeholder (rôle fournisseur si `SENS=fournisseur`, client sinon) | `uses_placeholder_partner` |
| `PRODUIT_INCONNU` | Oui | Variante placeholder — donnée d'identification pure, jamais matérialisée sur `AccMoveLine` | `uses_placeholder_variant` |
| `COMPTE_INCONNU` (colonne `COMPTE` optionnelle fournie mais non reconnue) | Oui | Compte d'attente | `uses_placeholder_account` |
| `TVA_NON_DETERMINEE` | Oui, **mais toujours `needs_qualification`** | Compte d'attente pour la ligne de TVA — sujet réglementaire sensible (déclaration TVA, ACC-CAL1/DCOM) | `uses_placeholder_tax` |
| `DATE_MANQUANTE` / `DATE_INVALIDE` | Oui | Même repli que le journal de caisse | `uses_default_date` |
| `REFERENCE_MANQUANTE` | **Non** | — impossible de regrouper les lignes d'une même facture | — |
| `SENS_INVALIDE` (ni "client" ni "fournisseur") | **Non** | — la polarité comptable ne peut pas être devinée | — |
| `QUANTITE_INVALIDE` / `PRIX_INVALIDE` | **Non** | — fabriquerait un fait financier | — |
| `CONFIGURATION_COMPTABLE_MANQUANTE` (aucun journal vente/achat, aucune période ouverte, aucun compte client/fournisseur) | **Non** | — gap de configuration à la charge de l'administrateur du tenant | — |

`TVA_NON_DETERMINEE` est le seul code de ce registre qui déclenche
`needs_qualification` **même si aucune autre dimension de la ligne
n'utilise de placeholder** — une facture dont la TVA n'est pas identifiée
avec certitude reste sujette à revue, quelle que soit la qualité du
reste de la ligne.

### 6.3 Double couche d'approbation

L'acte de **qualifier** une ligne (remplacer un placeholder par l'entité
réelle) est lui-même soumis à une `ApprovalRule` dédiée par module
(`ensure_qualification_approval_rule` dans chaque service d'import),
scopée au content-type de la ligne d'import et à la condition
`requires_placeholder` — **indépendante** des seuils de validation déjà
existants sur le document final (ex. seuils de validation facture, cf.
`accounting.services.invoices.ensure_default_approval_thresholds`).
Concrètement :

1. `qualify_import_row(row, ..., qualified_by=...)` remplace le
   placeholder par l'entité réelle sur le document déjà matérialisé
   (édition directe pour le journal de caisse/factures, dont l'`AccMove`
   reste `draft` ; **extourne puis recrée** le mouvement pour le stock,
   dont le `StkMove` est déjà validé — cf. docstring de
   `stock_import.qualify_import_row`).
2. Si la règle de qualification est active, une `ApprovalRequest` est
   créée (`status=pending_approval`) ; sinon la ligne passe directement
   `qualified`.
3. La décision passe par l'endpoint **générique déjà existant**
   `POST /api/v1/approvals/{id}/decide` (`apps.core.api_workflow`,
   Lot 1 étape 8) — aucun nouvel endpoint de décision n'a été créé.
   Un registre de hooks post-décision (`_qualification_decision_hooks`,
   résolu via `services.public` de chaque app) répercute la décision sur
   le statut de la ligne d'import concernée, en plus de la décision
   `ApprovalRequest` elle-même.
4. L'écran générique "Mes validations en attente" (`GET
   /api/v1/approvals/pending`) surface les nouvelles demandes de
   qualification **sans aucune modification** — il est déjà générique
   par content-type (vérifié par test,
   `apps.core.tests.test_qualification_generic_approval_screen`).

RBAC : `qualify_accimportrow` / `qualify_accinvoiceimportrow` /
`qualify_stkimportrow` (codenames déclarés en `Meta.permissions` des
modèles de ligne d'import) gardent `POST .../rows/{id}/qualify` —
accordés aux rôles "domaine cible" de chaque module (`comptable` pour
`accounting`, `magasinier` pour `stocks`) ainsi qu'à `admin`/`direction`
(pilotage transverse), cf. `apps.core.services.rbac_policy.
CUSTOM_PERMISSIONS`.

### 6.4 Résolution de partenaire par nom libre — simplification v1 assumée

`apps.partners.services.public.find_partner_by_name(tenant, name)` (et
son pendant `apps.core.services.entity_resolution` pour le vocabulaire
partagé `ResolutionConfidence`/`ResolutionResult`) implémente
**uniquement la correspondance EXACTE normalisée** (accents/casse/espaces
ignorés) : `ResolutionConfidence.FUZZY` n'est jamais retourné en v1,
même sur un nom presque identique. Une correspondance approximative
(similarité, phonétique) est une amélioration future possible sans
changer ce contrat. Zéro ou plusieurs partenaires correspondant au nom
normalisé donnent toujours `UNRESOLVED` — jamais de devinette sur
ambiguïté, même discipline que `apps.accounting.services.
bank_reconciliation.suggest_matches` (0 ou 2+ candidats → aucune décision
automatique).

### 6.5 Entités placeholder

Une par module, jamais un modèle centralisé dans `core` (respect strict
de la règle de couplage n°1) :

| Module | Champ | Fonction de création (idempotente) |
|---|---|---|
| `partners` | `Partner.is_placeholder` | `services.defaults.ensure_default_partner(tenant, role)` — un placeholder par rôle |
| `catalog` | `ProductVariant.is_placeholder` | `services.defaults.ensure_default_variant(tenant)` — un seul placeholder par tenant, sous une catégorie "Non classé" |
| `accounting` | `AccAccount.is_placeholder` | `services.chart_of_accounts.ensure_suspense_account(tenant)` — compte d'attente, code `471`, classe 47x |
| `stocks` | (emplacement virtuel, pas de champ dédié) | `services.defaults.ensure_unqualified_location(warehouse)` — un par entrepôt, code `ZONE-A-QUALIFIER` |

### 6.6 Aucune donnée réelle comme fixture

Comme pour tous les imports décrits dans ce document, les jeux de
données utilisés pour valider la qualification en test sont
**synthétiques** (fabriqués inline avec `openpyxl.Workbook()`, cf.
`apps/accounting/tests/test_cash_journal_import.py`,
`test_invoice_import.py`, `apps/stocks/tests/test_stock_import.py`) —
jamais les données financières réelles d'une entreprise.
