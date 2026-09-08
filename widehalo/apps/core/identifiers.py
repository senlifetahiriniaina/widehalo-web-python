"""T4bis — lire un identifiant venu d'un formulaire, sans rendre 500.

**Le défaut fermé, mesuré par AST sur l'arbre entier.** 63 appels
`uuid.UUID()` portaient sur une valeur d'entrée non typée. `uuid.UUID` lève
`ValueError` sur une chaîne mal formée, et AUCUN gestionnaire du dépôt ne
rattrape `ValueError` : elle tombe dans le gestionnaire générique, qui rend
**500**. Un utilisateur dont le presse-papier a tronqué un identifiant, ou
un intégrateur qui envoie `partner_id=""`, obtenait « une erreur inattendue
est survenue » pour une saisie simplement invalide.

Le critère de la Phase 4 est explicite : le système tiers « ne lit aucune
documentation contextuelle, ne devine rien, ne pardonne rien » et attend
« des codes d'erreur explicites ». Un 500 sur un identifiant malformé n'en
est pas un.

**Deux surfaces, deux remèdes, et le TYPE d'abord.** Côté API, la bonne
réponse n'est pas cette fonction : c'est de déclarer le champ `UUID` dans
le schéma, ce qui fait rejeter la valeur par django-ninja — 422 avec le nom
du champ, avant que le moindre service ne tourne, et visible dans
l'OpenAPI. Cette fonction sert la SECONDE surface, celle qui n'a pas de
validation de schéma : les vues d'écran, qui lisent `request.POST.get(...)`
et n'ont rien pour les arrêter. C'est exactement la répartition que le lot
T1 a établie entre `ReportFormat` (le type, côté API) et
`parse_report_format` (la fonction, côté écran).

**`BadRequest` plutôt qu'un repli sur `None`.** Traiter un identifiant
illisible comme « pas d'identifiant » crée un document orphelin au lieu de
refuser une saisie fausse — une erreur silencieuse qu'un comptable
découvrira des semaines plus tard, sur une facture sans client.
"""

from __future__ import annotations

from uuid import UUID

from django.core.exceptions import BadRequest
from django.utils.translation import gettext as _


def parse_uuid(valeur: str | None, *, champ: str) -> UUID:
    """L'identifiant demandé, ou un 400 qui NOMME le champ.

    `champ` porte le libellé lisible — « client », « produit » — et non le
    nom technique : c'est ce qui distingue un message utile d'un code
    d'erreur. Le critère EFA-1 tient le même raisonnement pour les mentions
    obligatoires, et il vaut partout : désigner ce qui ne va pas est la
    moitié du travail d'un refus."""
    brut = (valeur or "").strip()
    if not brut:
        raise BadRequest(_("Le champ « %(champ)s » est obligatoire.") % {"champ": champ})
    try:
        return UUID(brut)
    except (ValueError, AttributeError, TypeError) as refus:
        raise BadRequest(
            _(
                "Identifiant illisible pour le champ « %(champ)s ». Sélectionnez "
                "une valeur dans la liste plutôt que de la saisir à la main."
            )
            % {"champ": champ}
        ) from refus


def parse_optional_uuid(valeur: str | None, *, champ: str) -> UUID | None:
    """Même chose, mais l'absence est admise.

    Distingue deux situations que `parse_uuid` confond volontairement :
    « rien n'a été choisi », qui est légitime pour un champ facultatif, et
    « quelque chose a été saisi mais c'est illisible », qui reste un refus.
    Les confondre laisserait passer une saisie fausse sous couvert
    d'optionnalité."""
    brut = (valeur or "").strip()
    if not brut:
        return None
    return parse_uuid(brut, champ=champ)


__all__ = ["parse_optional_uuid", "parse_uuid"]
