# API publique WideHalo — guide d'intégration

*Version `public-v1`. Écrit pour l'intégrateur d'un client, pas pour
l'éditeur : il doit suffire sans support.*

---

## 1. Ce que cette API est, et ce qu'elle n'est pas

Elle **est** la surface par laquelle un outil tiers lit et écrit dans
WideHalo sans accès à la base et sans contourner la logique métier. Elle
traverse exactement la même couche de services que l'interface utilisateur,
avec les mêmes contrôles de rôle.

Elle **n'est pas** une vue sur le schéma de la base. Une opération publique
est un contrat nommé, pas un endpoint : le nom est stable, ce qui le sert
peut changer. C'est ce qui nous permet de refactorer l'intérieur sans casser
votre intégration — et ce qui nous interdit de vous exposer une table.

Deux limites posées par le cahier des charges du produit, et qui ne se
négocient pas :

- **Aucun accès direct à la base**, ni par un outil tiers, ni par une
  requête générée par un modèle de langage.
- **Aucune élévation par l'API.** Une clé n'obtient jamais une donnée que
  l'utilisateur qu'elle porte ne verrait pas dans l'interface. Si votre
  intégration doit lire la comptabilité, la clé doit porter un compte qui a
  ce droit — et c'est une décision du client, pas un réglage d'API.

---

## 2. Authentification

```
Authorization: Bearer wh_<société>_<secret>
```

La clé **désigne sa société** : vous n'avez aucun en-tête de société à
envoyer, et vous ne pouvez pas en changer. Présenter la clé sous une autre
société ne donne pas accès à cette société-là, cela rend la clé
introuvable — l'appel échoue.

Le secret n'est affiché **qu'une fois**, à l'émission. Nous ne pouvons pas
vous le redonner : nous n'en gardons que l'empreinte. Perdu, il se remplace ;
il ne se retrouve pas.

Une clé porte :

| Attribut | Effet |
|---|---|
| **Portées** | La liste des opérations qu'elle peut appeler. Une opération hors portée rend `403`, en la nommant. |
| **Débit** | Un maximum d'appels par heure, **par clé**. Vos autres clés ne sont pas affectées. |
| **Expiration** | Facultative. Une clé expirée rend `401`. |
| **Révocation** | Immédiate, y compris pour un appel en cours d'authentification. |

Une clé inconnue, révoquée ou expirée rend le **même** `401`, sans motif.
C'est délibéré : distinguer les trois vous apprendrait quelque chose sur une
clé qui ne vous appartient pas.

---

## 3. Erreurs

Toutes les erreurs sont au format `application/problem+json` (RFC 7807) :

```json
{
  "type": "about:blank",
  "title": "Portée insuffisante",
  "status": 403,
  "detail": "Cette clé ne porte pas l'opération « exchanges.read ».",
  "instance": "/api/public/v1/exchanges"
}
```

| Code | Ce que ça veut dire | Ce qu'il faut faire |
|---|---|---|
| `401` | Clé inconnue, révoquée ou expirée | Vérifier la clé auprès du client ; en demander une nouvelle |
| `403` | Portée insuffisante, ou le compte porté n'a pas le droit | Le `detail` nomme l'opération manquante |
| `404` | La ressource n'existe pas **ou** ne vous est pas accessible | Les deux cas sont confondus, volontairement |
| `422` | Entrée invalide — le `detail` dit laquelle | Corriger l'appel |
| `429` | Débit dépassé | Attendre le nombre de secondes de l'en-tête `Retry-After` |

`429` porte toujours `Retry-After`. Un client qui réessaie au hasard aggrave
la situation que ce plafond existe pour éviter.

---

## 4. Le schéma

`GET /api/public/v1/openapi.json` — le schéma OpenAPI de cette surface, et
d'elle seule. Il ne décrit **pas** les opérations internes du produit : elles
existent, elles ne sont pas un contrat, et aucune clé ne les atteint.

---

## 5. Environnement d'essai

Un bac à sable est une **copie datée de la société**, avec sa propre clé. Les
données y sont celles de la production au moment du clone — un bac à sable
vide ne servirait à rien pour essayer une configuration — mais elles sont
isolées : rien de ce que vous y créez n'apparaît en production, et
réciproquement.

Un bac à sable **expire**. C'est ce qui l'empêche de devenir une seconde
production, ce qu'aucun client ne décide mais que tous finissent par faire.

---

## 6. Ce qu'on vous garantit, et pour combien de temps

La politique de dépréciation est écrite dans
[`politique-depreciation.md`](politique-depreciation.md). En une phrase :
**une opération publiée ne disparaît pas sans préavis daté**, et le préavis
voyage dans les en-têtes de vos propres réponses.
