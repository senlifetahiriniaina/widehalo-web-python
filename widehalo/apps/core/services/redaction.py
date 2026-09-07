"""FLX-8 — la rédaction des secrets, sur les trois surfaces du critère.

Le critère : « un motif ressemblant à un secret n'apparaît dans aucun
journal, aucune charge utile archivée et aucun message d'erreur affiché à
l'utilisateur. » Le dictionnaire du cahier (§13.2) le redit du côté de la
charge utile : « rédaction des secrets à l'écriture ».

**Pourquoi dans `core` et pas dans `flows`.** Le filtre de journalisation
est global — il s'applique à tout ce que le produit écrit, pas seulement
au hub de flux. Et `core` ne peut pas importer `flows`. Même raison que
`core.cost_units`, qui vit ici pour la même raison exactement.

**Ce que ce module ne prétend pas faire.** Il ne détecte pas un secret,
il détecte un MOTIF DE SECRET — le critère le dit lui-même, « un motif
ressemblant à un secret ». La différence est honnête et il faut l'écrire :
une chaîne aléatoire de quarante caractères qui ne serait annoncée par
rien restera visible. On ne cherche pas l'entropie, délibérément : un seuil
d'entropie rédige les identifiants de commande, les empreintes, les
sommes de contrôle et les UUID, c'est-à-dire précisément ce qu'un
diagnostic a besoin de lire. Un journal illisible est un journal qu'on
finit par désactiver, et une protection désactivée ne protège rien.

**Quatre familles de motifs, chacune pour une raison.**

1. *Le couple clef-valeur nommé.* `password=...`, `"api_key": "..."`,
   `Authorization: ...`. C'est de loin la forme la plus fréquente : une
   charge utile JSON recopiée dans un message d'erreur, un en-tête HTTP
   dans une trace. Le vocabulaire des noms est celui de la garde
   `test_secrets_are_never_stored_in_clear.py`, jamais un second.
2. *Les schémas d'autorisation HTTP.* `Bearer ...`, `Basic ...`. Ils
   apparaissent sans nom de champ, dans une ligne d'en-tête recopiée.
3. *Les informations d'identification dans une URL.*
   `https://utilisateur:motdepasse@hote`. Une URL de liaison mal saisie
   les porte, et une URL se journalise partout.
4. *Le jeton JWT.* Trois segments base64url séparés par des points. Il se
   reconnaît à sa FORME et non à son nom, ce qui est justement ce qui le
   rend dangereux : personne ne l'annonce.
"""

from __future__ import annotations

import re
from typing import Any

#: Ce qui remplace le secret. Explicite : une valeur effacée sans le dire
#: se lit comme une valeur absente, et un diagnostic partirait alors sur
#: « le champ n'était pas renseigné » plutôt que « on ne vous le montre
#: pas ».
MASQUE = "[secret rédigé]"

#: Les noms qui ANNONCENT un secret. Repris de `_SECRET_NAME`
#: (`tests/architecture/test_secrets_are_never_stored_in_clear.py`), plus
#: les trois que seule une trace HTTP fait apparaitre — `authorization`,
#: `signature`, `client_secret` — et qui ne sont jamais des noms de
#: colonne.
NOMS_DE_SECRET = (
    "secret",
    "password",
    "passwd",
    "passphrase",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "credentials",
    "token",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "client_secret",
    "signature",
)

_NOMS = "|".join(NOMS_DE_SECRET)

#: 1. Le couple clef-valeur. Le nom peut être entouré de guillemets, la
#: valeur aussi ; le séparateur est `=` ou `:`. La valeur s'arrête au
#: premier séparateur structurel — guillemet, virgule, accolade, crochet,
#: espace, point-virgule, fin de ligne — sinon un `password=x, montant=5`
#: rédigerait le montant avec.
_CLEF_VALEUR = re.compile(
    rf'(?P<clef>["\']?\b(?:{_NOMS})\b["\']?\s*[:=]\s*)(?P<valeur>"[^"]*"|\'[^\']*\'|[^\s,;}}\]&]+)',
    re.IGNORECASE,
)

#: 2. Les schémas d'autorisation HTTP, sans nom de champ.
_SCHEMA_HTTP = re.compile(r"\b(?P<schema>Bearer|Basic|Token)\s+(?P<valeur>[\w\-._~+/=]{8,})")

#: 3. Les informations d'identification dans une URL. Le nom d'utilisateur
#: est conservé : il sert au diagnostic (« ce n'est pas le bon compte »)
#: et n'est pas le secret.
_URL = re.compile(r"(?P<avant>[a-zA-Z][\w+.-]*://[^/\s:@]+:)(?P<valeur>[^@\s]+)(?P<apres>@)")

#: 4. Le jeton JWT, reconnu à sa forme. Trois segments base64url, le
#: premier commençant par `eyJ` — l'en-tête `{"` encodé, présent dans tout
#: JWT réel. Sans cette ancre, l'expression attraperait n'importe quel
#: `a.b.c`, donc des noms de domaine et des chemins pointés.
_JWT = re.compile(r"\beyJ[\w-]*\.[\w-]+\.[\w-]+")


#: Deux masques que deux passes ont posés côte à côte n'en font qu'un.
_MASQUES_CONSECUTIFS = re.compile(rf"(?:{re.escape(MASQUE)}\s*){{2,}}")


def _masque_en_gardant_les_guillemets(correspondance: re.Match[str]) -> str:
    valeur = correspondance.group("valeur")
    if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
        return f"{correspondance.group('clef')}{valeur[0]}{MASQUE}{valeur[0]}"
    return f"{correspondance.group('clef')}{MASQUE}"


def redact_secrets(texte: Any) -> str:
    """Rend le texte, ses motifs de secret remplacés par `MASQUE`.

    Accepte n'importe quoi et rend une chaîne : les appelants sont des
    chemins d'erreur (un message d'exception, un enregistrement de
    journal), et un rédacteur qui lèverait sur un type inattendu
    remplacerait une fuite par une panne.

    L'ordre des passes compte. Le JWT d'abord, sinon la passe clef-valeur
    le tronquerait au premier point et le motif ne serait plus
    reconnaissable pour ce qu'il est.

    Les GUILLEMETS de la valeur sont conservés, et ce n'est pas
    cosmétique : cette fonction rédige aussi la charge utile ARCHIVÉE,
    c'est-à-dire ce qui part chez le tiers. Rendre `{"api_key": [secret
    rédigé]}` transformerait un JSON valide en texte que le tiers refuse,
    et le refus serait mis sur le compte du tiers.

    La passe finale replie les masques consécutifs. Sans elle,
    `Authorization: Bearer xyz` ressort masqué DEUX fois — une par le
    schéma HTTP, une par le couple clef-valeur — ce qui est correct mais
    illisible."""
    if texte is None:
        return ""
    valeur = texte if isinstance(texte, str) else str(texte)
    valeur = _JWT.sub(MASQUE, valeur)
    valeur = _URL.sub(rf"\g<avant>{MASQUE}\g<apres>", valeur)
    valeur = _SCHEMA_HTTP.sub(rf"\g<schema> {MASQUE}", valeur)
    valeur = _CLEF_VALEUR.sub(_masque_en_gardant_les_guillemets, valeur)
    return _MASQUES_CONSECUTIFS.sub(MASQUE, valeur)


def contains_secret_pattern(texte: Any) -> bool:
    """`True` si la rédaction changerait quelque chose.

    Existe pour les gardes et pour les tests : affirmer « ce message ne
    contient pas de motif de secret » doit se faire avec le MÊME
    vocabulaire que la rédaction, sinon les deux divergent et la garde
    cesse de garder ce que le rédacteur fait."""
    valeur = texte if isinstance(texte, str) else str(texte or "")
    return redact_secrets(valeur) != valeur


__all__ = [
    "MASQUE",
    "NOMS_DE_SECRET",
    "contains_secret_pattern",
    "redact_secrets",
]
