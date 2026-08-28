# Formats d'import comptable, caisse et référentiels

Ce document décrit les formats de fichier acceptés par les assistants
d'import de l'application, colonne par colonne. Il couvre deux imports
réellement implémentés et testés (plan comptable, journal de caisse) et
plusieurs formats **documentés mais dont l'écran d'import reste à
construire** dans un chantier dédié (partenaires, catalogue, stocks).

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

## 4. Autres imports documentés (écran non encore implémenté)

Les formats ci-dessous sont documentés pour permettre une migration future
depuis un existant, mais **aucun écran d'import n'est encore construit**
pour eux — à traiter dans un chantier dédié, une fois qu'un besoin concret
se présente. `apps/core/services/import_wizard.py` (mapping colonne→champ,
validation à blanc, commit atomique tout-ou-rien) est le point de départ
naturel pour les bâtir.

### Partenaires (`apps.partners.models.Partner`)

| Colonne proposée | Type | Description |
|---|---|---|
| `code` | texte | Code partenaire (auto-généré si absent). |
| `name` | texte | Raison sociale. |
| `nif` | texte | Numéro d'identification fiscale (unicité par tenant, doublon détecté mais non bloquant). |
| `roles` | liste (texte, séparateur `;`) | Parmi `client`/`fournisseur`/`transporteur`/`sous_traitant`. |
| `credit_limit_mga` | décimal | Plafond de crédit en Ariary. |
| `email`, `phone`, `address` | texte | Coordonnées. |

### Catalogue (`apps.catalog.models.ProductTemplate`/`ProductVariant`/`TextileSpec`)

| Colonne proposée | Type | Description |
|---|---|---|
| `template_code` | texte | Code du gabarit produit. |
| `template_name` | texte | Nom du produit. |
| `category` | texte | Catégorie de catalogue. |
| `uom` | texte | Unité de mesure de base. |
| `variant_attributes` | texte (`attribut=valeur;...`) | Attributs générateurs de variantes (max 2, plafond 50 combinaisons). |
| `material`, `composition`, `weight_gsm`, `width_cm` | texte/décimal | Spécification textile (`TextileSpec`), optionnelle. |

### Stocks — quantités initiales (`apps.stocks.models.StkQuant`/mouvement d'inventaire initial)

| Colonne proposée | Type | Description |
|---|---|---|
| `variant_code` | texte | Référence de la variante produit. |
| `warehouse_code` | texte | Entrepôt. |
| `location_code` | texte | Emplacement au sein de l'entrepôt. |
| `qty` | décimal | Quantité initiale. |
| `unit_cost_mga` | décimal | Coût unitaire initial (valorisation d'ouverture). |
| `lot_reference` | texte | Numéro de lot, si la traçabilité par lot est activée pour ce produit. |

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
