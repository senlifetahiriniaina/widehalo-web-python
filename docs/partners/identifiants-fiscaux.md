# Identifiants fiscaux — format, vérification, reprise

> Lot T3 (Phase 4). Ce document s'adresse à qui exploite le produit, pas à
> qui l'écrit : il dit ce que le contrôle refuse, ce qu'il ne prétend pas
> vérifier, et comment mesurer un référentiel avant que la soumission de
> factures ne devienne bloquante.

## Ce que le cahier demande, et où le refus tombe

Deux passages disent des choses différentes, et l'arbitrage a été tranché
avant d'écrire une ligne :

- La prose (l.224) : « un identifiant fiscal absent ou faux, qui
  n'empêchait qu'une impression jusqu'ici, **empêchera désormais une
  validation** » — dans un paragraphe intitulé « Trois travaux que la
  Phase 4 impose au CLIENT ».
- Le critère EFA-1 : « un champ obligatoire manquant **bloque la
  soumission** et désigne le champ, **sans invalider la facture** ».

**Le critère prévaut.** Conséquence concrète : ce lot ne casse la
facturation de personne. Il livre le format, la normalisation, la
vérification et l'outil de mesure ; c'est le contrôle de complétude du
bloc C qui refusera la soumission en nommant le champ manquant. Le client
a le temps de nettoyer son référentiel — ce que le cahier appelle
précisément un travail à sa charge.

## Ce que le contrôle refuse — et ce qu'il ne dit pas

**Le format n'est pas inventé.** Le format exact du NIF malgache n'est pas
dans le cahier et aucune source primaire n'est disponible ici ; le jeu de
démonstration lui-même emploie des valeurs fictives (« MG-NIF-100001 »).
Écrire une expression régulière stricte fabriquerait une règle fiscale et
la présenterait comme vérifiée — ce que le projet s'interdit (§0.5). Même
posture qu'au lot T2 pour `tva.taux_export`.

Ce que le contrôle tient, pour Madagascar (`nif` et `stat`) :

| Il refuse | Il n'affirme pas |
|---|---|
| moins de 4 ou plus de 32 caractères | que l'identifiant existe à la DGI |
| tout ce qui se réduit au vide (espaces seuls) est ramené à « pas d'identifiant », jamais gardé tel quel | qu'il appartient à ce tiers-là |
| tout caractère hors `A-Z 0-9 - / . espace` — donc les accents, la ponctuation de phrase, un paragraphe collé dans le mauvais champ | qu'il est encore actif |

Le « faux » au sens fort se vérifie ailleurs : par l'opération OP8 auprès
du référentiel (ci-dessous). Chaque format déclaré porte une **réserve
écrite** obligatoire (≥ 40 caractères, vérifiée par une garde CI) qui dit
ce qu'il vaut et ce qu'il ne vaut pas.

Le jour où une source primaire existera, resserrer le motif est un
changement de **paramètre** dans `apps/core/services/fiscal_identifiers.py`,
pas une reprise de code — c'est ce qu'EFA-7 exige déjà du format de
facture.

## Où le contrôle s'applique

Sur **toutes les portes**, parce que Django ne fait tourner les validateurs
de champ que dans `full_clean()`, jamais dans `save()` — et six surfaces
écrivaient `nif` sans passer par un formulaire. Le contrôle est donc dans
`save()`, pour :

- `partners.Partner.nif` et `partners.Partner.stat` (le tiers) ;
- `core.Tenant.nif` et `core.Tenant.stat` (**l'émetteur** — EFA-1 exige les
  mentions du vendeur autant que celles du client).

Le pays qui décide du format est lu sur la société (`Tenant.country_code`,
« MG » par défaut), jamais figé.

### Normalisation, et pourquoi elle ne réécrit pas tout

À l'enregistrement, la valeur est mise en majuscules et ses espaces sont
réduits. Elle n'est **pas** dépouillée de ses tirets : l'une des deux
formes en présence peut être la forme officielle, et le produit ne
tranche pas à la place du comptable.

Le rapprochement de doublons, lui, compare la forme **canonique** (lettres
et chiffres seulement). « MG-NIF-100002 » et « mg nif 100002 » lèvent
désormais une alerte de doublon ; avant ce lot, ils créaient deux fiches en
silence — à la création manuelle comme à l'import.

## OP8 — la vérification par le référentiel

Le cahier décrit OP8 comme « sortant, lecture, **synchrone** », avec
« dégradation en valeur saisie si le tiers ne répond pas » (§4.1). Deux
règles déjà tenues l'interdisent telle quelle : aucun module métier n'émet
d'appel réseau (garde CI depuis S6), et l'échec d'un tiers ne bloque jamais
une transition métier (FLX-2).

La lecture retenue : **la demande part par le hub de flux, et son résultat
annote le tiers**. La valeur saisie reste autoritative tant qu'elle n'est
pas contredite. Créer un tiers ne dépendra jamais de la latence d'un
référentiel.

Quatre états, lisibles sur la fiche :

| État | Ce qu'il dit |
|---|---|
| **Non vérifié** | personne n'a interrogé le référentiel — état normal, pas un défaut |
| **Confirmé** | le référentiel a répondu, à la date affichée |
| **Introuvable** | le référentiel ne connaît pas cet identifiant — la valeur saisie n'est pas effacée pour autant |
| **Référentiel indisponible** | l'échange a échoué ; rien n'est conclu |

Une confirmation **expire au bout d'un an** (`VALIDITY_DAYS`). Une
confirmation de 2024 ne dit rien de 2026 : sans péremption, un tiers radié
resterait « confirmé » pour toujours.

La commande périodique `verify_fiscal_identifiers` (déclarée quotidienne à
4 h) demande la vérification des identifiants dont la réponse manque ou a
expiré, et relit les verdicts arrivés. Sans liaison active vers un
connecteur `referentiel_fiscal`, elle ne fait rien — ce n'est pas une
erreur.

## La reprise : chiffrer avant de bloquer

Un travail qu'on met à la charge de quelqu'un sans lui donner de quoi le
mesurer n'est pas un travail, c'est une surprise. La commande d'audit
**lit et ne modifie rien** :

```bash
python manage.py audit_fiscal_identifiers                      # toutes les sociétés
python manage.py audit_fiscal_identifiers --tenant-code DEMO   # une seule
python manage.py audit_fiscal_identifiers --details            # liste chaque tiers
```

Elle sépare **trois travaux différents**, qu'un total unique mélangerait :

1. **Sans NIF** — à collecter auprès du tiers ;
2. **Mal formé** — à corriger dans la fiche, le motif du refus est donné ;
3. **Doublon canonique** — deux fiches portent le même identifiant sous
   deux formes : à fusionner ou à distinguer.

Elle ne normalise **pas** en masse, délibérément : réécrire la saisie de
comptables sans qu'ils l'aient demandée est une correction qui ne se
défend pas, et l'une des deux formes peut être l'officielle.

Sortie type :

```
DEMO — 128 tiers, 14 sans NIF, 3 mal formé(s), 2 groupe(s) de doublon.

19 tiers à traiter au total. Aucune modification n'a été faite :
la correction reste une décision humaine.
```

## Ce que les autres modules peuvent lire

La règle de couplage n°1 interdit à `accounting` de toucher
`partners.Partner`. Le contrôle de complétude du bloc C passe donc par
`apps.partners.services.public` :

- `get_partner_fiscal_identity(partner_id)` — identifiant, état de
  vérification **et** date, ensemble : rendre le seul identifiant
  laisserait croire qu'un NIF présent est un NIF valide, ce que ce lot
  existe pour lever ;
- `missing_fiscal_identifiers(partner_id, required=("nif",))` — les champs
  exigés que le tiers ne porte pas, pour que le refus **nomme le champ**
  (EFA-1). `required` est un paramètre et non une constante : le profil
  pays du bloc C le fournira (EFA-7).
