# API publique — politique de dépréciation

*Engagement contractuel de la surface `public-v1`.*

---

## Le principe, et pourquoi il est écrit avant d'en avoir besoin

**Une opération publiée ne se retire plus, elle se déprécie.** C'est la
raison d'être du plafond de 80 opérations publiques : ce plafond ne borne
pas une quantité de code — les 1 500 endpoints internes se refactorent
librement — il borne un **engagement de rétrocompatibilité**. Chaque
opération publiée est une promesse qu'on ne pourra plus reprendre sans
prévenir.

Cette politique est écrite au sprint qui ouvre la surface, et pas au premier
retrait. Une politique de dépréciation rédigée le jour où l'on a besoin de
déprécier quelque chose est toujours celle qui arrange ce retrait-là.

---

## Les deux dates, et pourquoi il en faut deux

Toute opération dépréciée porte **deux dates**, jamais une seule :

| Date | Ce qu'elle dit | En-tête |
|---|---|---|
| **Dépréciation** | À partir de cette date, l'opération est déconseillée. Elle répond normalement. | `Deprecation` |
| **Retrait** | À partir de cette date, l'opération cesse de répondre. | `Sunset` |

Une seule date ne suffirait pas. « C'est déprécié » sans échéance ne se
planifie pas ; une échéance sans dépréciation préalable est une surprise. Le
produit **refuse** une déclaration qui ne porte que l'une des deux — ce n'est
pas une convention, c'est une validation à l'enregistrement.

---

## Où l'information vous parvient

1. **Dans les en-têtes de vos propres réponses.** Toute réponse d'une
   opération dépréciée porte `Deprecation` et `Sunset`. Vous n'avez rien à
   surveiller : l'information arrive dans le trafic que vous faites déjà.
2. **Dans le schéma OpenAPI public**, où l'opération est marquée.
3. **Dans ce document**, dont le tableau ci-dessous fait foi.

Le premier point est celui qui compte. Un intégrateur ne relit pas la
documentation d'une opération qui marche.

---

## Délai minimal

Le délai entre les deux dates n'est jamais inférieur à **deux versions
mineures publiées**, et jamais inférieur à **six mois**. Le plus long des
deux s'applique.

---

## Opérations dépréciées

*Aucune à ce jour.* La surface publique a ouvert au sprint S7 ; aucune
opération n'a encore été dépréciée. Ce tableau est vide **et vérifié** : un
test constate cette absence et échouera à la première dépréciation, ce qui
sera le rappel de compléter ce document en même temps que le code.

| Opération | Dépréciée le | Retirée le | Remplacée par |
|---|---|---|---|
| — | — | — | — |
