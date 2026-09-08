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

**`ValidationError` plutôt qu'un repli sur `None`.** Traiter un
identifiant illisible comme « pas d'identifiant » crée un document orphelin
au lieu de refuser une saisie fausse — une erreur silencieuse qu'un
comptable découvrira des semaines plus tard, sur une facture sans client.

**Et `ValidationError` plutôt que `BadRequest`, ce qui n'est pas un
détail.** La première rédaction levait `BadRequest`, et le test SAL-7
`test_a_validation_error_no_longer_empties_the_form` l'a refusée sur-le-
champ : les vues de formulaire rattrapent `ValidationError` pour re-rendre
la page AVEC la saisie de l'utilisateur, et `BadRequest` traverse ce
`try` pour produire une page 400 nue. C'est-à-dire qu'elle rouvrait le
défaut que le lot SAL-7 avait précisément fermé — un formulaire vidé par
une erreur de validation.

`ValidationError` est le bon niveau sur les deux surfaces : les vues qui
re-rendent le rattrapent déjà, et côté API le gestionnaire livré par T1
(`apps.core.errors.on_domain_validation_error`) le traduit en 422 qui
nomme le champ. `BadRequest` reste juste là où rien ne rattrape et où il
n'y a pas de saisie à préserver — la lecture d'un paramètre de rapport
dans une barre d'adresse, ce que fait `parse_report_format`.
"""

from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
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
        raise ValidationError(_("Le champ « %(champ)s » est obligatoire.") % {"champ": champ})
    try:
        return UUID(brut)
    except (ValueError, AttributeError, TypeError) as refus:
        raise ValidationError(
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
