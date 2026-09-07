"""La LISTE BLANCHE des operations publiques — declaree, plafonnee, opposable.

Le cahier ne laisse aucune ambiguite sur ce que « portee » veut dire :
« portees exprimees en operations publiques declarees, JAMAIS EN TABLES »
(§13.2, entite « Cle publique d'acces »). Une portee qui nommerait des
modeles ferait de la structure interne du produit un engagement public : le
jour ou une table se scinde, tous les jetons du parc cessent d'etre
valides, ou pire, deviennent trop larges.

**Une operation publique n'est donc pas un endpoint : c'est un CONTRAT
NOMME.** Le nom est stable, l'endpoint qui le sert peut changer. C'est ce
qui rend tenable la promesse d'API-2 — « aucune operation non declaree
n'est atteignable par un jeton client, meme si l'endpoint interne
existe » — sans figer l'interne.

**Plafonnee a 80** (`settings.BUDGET_MAX_PUBLIC_OPERATIONS`), et le motif
est ecrit dans le cahier : « une operation publiee ne se retire plus, elle
se deprecie sur plusieurs versions ». Le plafond borne un ENGAGEMENT DE
RETROCOMPATIBILITE, pas une quantite de code — c'est pourquoi il est
distinct des 1 500 endpoints internes, qui eux se refactorent librement.

**Registre en memoire, declare depuis `apps.py::ready()`**, comme les
rapports, les anomalies, les commandes periodiques et les adaptateurs. Une
operation publique est un artefact de LIVRAISON : la stocker en base
permettrait a une ligne de production de designer une operation absente de
la version deployee.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class PublicOperation:
    """Une operation publique declaree.

    `permission` est le codename Django que le porteur du jeton doit
    detenir. C'est LUI qui tient API-1 — « un jeton client ne peut obtenir
    aucune donnee qu'un utilisateur du role correspondant ne pourrait
    consulter » — parce qu'il fait passer l'appel public par exactement le
    meme controle que l'interface. Le cahier le dit sans detour : « le
    controle est celui de la Phase 1 pour le copilote, reutilise SANS
    MODIFICATION ».

    `deprecated_since` porte la politique de depreciation : une operation
    publiee ne disparait pas, elle se marque. Vide tant qu'elle est
    courante."""

    code: str
    label: str
    permission: str
    description: str = ""
    deprecated_since: str = ""


_OPERATIONS: dict[str, PublicOperation] = {}


def register_public_operation(operation: PublicOperation) -> None:
    """Declare une operation publique. Idempotent sur le code.

    Refuse un code deja pris par une DECLARATION DIFFERENTE : deux modules
    qui publieraient le meme nom pour deux contrats distincts rendraient la
    portee d'un jeton ambigue, et l'ambiguite se resoudrait selon l'ordre
    de chargement des applications."""
    existante = _OPERATIONS.get(operation.code)
    if existante is not None and existante != operation:
        raise ValidationError(
            _(
                "L'opération publique « %(code)s » est déjà déclarée avec un autre "
                "contrat. Un même nom pour deux contrats rendrait la portée d'un "
                "jeton dépendante de l'ordre de chargement des applications."
            )
            % {"code": operation.code}
        )
    _OPERATIONS[operation.code] = operation


def get_public_operation(code: str) -> PublicOperation | None:
    return _OPERATIONS.get(code)


def list_public_operations() -> list[PublicOperation]:
    return [_OPERATIONS[code] for code in sorted(_OPERATIONS)]


def public_operation_codes() -> frozenset[str]:
    return frozenset(_OPERATIONS)


def validate_scopes(scopes: object) -> None:
    """Validateur de portee pour `FlwApiKey.scopes`.

    Refuse ce qui n'est pas une liste, ce qui contient un doublon, et ce
    qui nomme une operation NON DECLAREE. Le dernier point est celui qui
    compte : une portee qui nommerait n'importe quoi laisserait croire a un
    droit qui n'existe pas — et le jour ou l'operation serait declaree, le
    jeton l'obtiendrait sans que personne ne l'ait decide."""
    if not isinstance(scopes, list):
        raise ValidationError(
            _("Les portées se déclarent en liste, pas en %(type)s.")
            % {"type": type(scopes).__name__}
        )
    connues = public_operation_codes()
    inconnues = [code for code in scopes if code not in connues]
    if inconnues:
        raise ValidationError(
            _(
                "Portée(s) inconnue(s) : %(inconnues)s. Une portée nomme une "
                "opération publique DÉCLARÉE, jamais une table ni un endpoint."
            )
            % {"inconnues": ", ".join(map(str, inconnues))}
        )
    if len(set(scopes)) != len(scopes):
        raise ValidationError(_("Une portée déclarée deux fois : %(liste)s.") % {"liste": scopes})


__all__ = [
    "PublicOperation",
    "get_public_operation",
    "list_public_operations",
    "public_operation_codes",
    "register_public_operation",
    "validate_scopes",
]
