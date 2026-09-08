"""Le vocabulaire des formats d'export de rapport — partagé, fermé, défini
ICI.

**Le défaut fermé, et il touchait 41 endpoints.** Chaque endpoint de
rapport déclarait son paramètre `format: str`. Django-ninja acceptait donc
n'importe quelle chaîne, la passait au `rows_to_bytes` du module, qui
levait `ValueError("Format d'export non supporté")` — ou, quand la valeur
traversait jusqu'au dictionnaire de types MIME, un `KeyError` sec. Dans les
deux cas : **500**. Un utilisateur qui tape `?format=pdf` sur un rapport
qui ne fait pas de PDF obtenait « une erreur inattendue est survenue »,
alors que sa demande était simplement hors du menu.

Le critère de la Phase 4 ne laisse pas d'échappatoire là-dessus : le
système tiers « ne lit aucune documentation contextuelle, ne devine rien,
ne pardonne rien » et attend « des codes d'erreur explicites ». Un 500 sur
un paramètre hors énumération n'en est pas un.

**Le type, pas une garde.** Déclarer `format: ReportFormat` fait rejeter la
valeur par la validation de schéma de django-ninja — donc 422 avec le nom
du paramètre et les valeurs admises, AVANT que le moindre service ne
tourne. Une garde applicative dans chaque endpoint aurait dû être écrite
41 fois et oubliée à la 42ᵉ ; le type se déclare une fois et se voit dans
l'OpenAPI, ce qui est précisément ce dont l'intégrateur a besoin.

**Pourquoi dans `core`.** Dix modules portent leur propre `rows_to_bytes`
(une duplication antérieure à ce lot, et qu'il ne corrige pas), tous avec
le même trio json/csv/xlsx. Le vocabulaire doit être unique : deux menus
divergents produiraient un OpenAPI qui promet un format qu'un module ne
sert pas. `core` est le seul endroit que les dix peuvent atteindre.

**`pdf` n'est PAS dans ce jeu**, et c'est délibéré. Aucun `rows_to_bytes`
ne rend de PDF : le PDF de ce dépôt est produit par des services dédiés
(`quotation_pdf`, `generate_liasse_is`…) sur des gabarits, pas par
tabulation de lignes. L'inclure ici promettrait dans l'OpenAPI un format
que chaque endpoint refuserait ensuite — exactement le défaut qu'on
ferme. Le moteur de rapports générique (`apps.reporting`), lui, sait
vraiment produire un PDF et garde donc son propre jeu, plus large.
"""

from __future__ import annotations

from typing import Literal

from django.core.exceptions import BadRequest
from django.utils.translation import gettext as _

#: Les trois formats que tout `rows_to_bytes` de ce dépôt sait produire.
ReportFormat = Literal["json", "csv", "xlsx"]

#: Le type MIME de chacun. Partagé pour la même raison que le vocabulaire :
#: quatre modules en portaient chacun une copie, et une copie qui diverge
#: sert un tableur en `text/csv`.
REPORT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def parse_report_format(valeur: str | None) -> str:
    """Le format demandé par une requête d'ÉCRAN, ou un 400 explicite.

    **Le même défaut que côté API, sur l'autre surface.** Les neuf modules
    à écrans de rapport lisent `request.GET.get("format", "json")` et
    passent la valeur telle quelle à `_CONTENT_TYPES[format]` — un
    `KeyError`, donc un 500, pour un utilisateur qui a simplement tapé
    `?format=pdf` dans la barre d'adresse. Les vues Django n'ont pas de
    validation de schéma pour les arrêter : il leur faut cette fonction.

    `BadRequest` plutôt qu'un repli silencieux sur `json` : servir du JSON
    à qui a demandé un tableur est une réponse fausse présentée comme
    juste. Django la traduit en 400 sans middleware supplémentaire.

    Casse et espaces tolérés — `?format=CSV` est une demande parfaitement
    claire, et la refuser serait du pédantisme sans bénéfice."""
    format_demande = (valeur or "json").strip().lower()
    if format_demande not in REPORT_CONTENT_TYPES:
        raise BadRequest(
            _("Format d'export inconnu : « %(recu)s ». Formats disponibles : %(menu)s.")
            % {"recu": valeur, "menu": ", ".join(sorted(REPORT_CONTENT_TYPES))}
        )
    return format_demande


__all__ = [
    "REPORT_CONTENT_TYPES",
    "ReportFormat",
    "parse_report_format",
]
