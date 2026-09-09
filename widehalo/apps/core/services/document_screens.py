"""T8 (bloc H, CON-1) — de quelle piece un echange parle, et ou la voir.

**Le critere, dans son sens reciproque** : « Depuis toute piece metier,
l'etat de ses echanges est atteignable en un clic, **et reciproquement
depuis toute ligne du journal**. »

**Pourquoi ce registre existe, et pourquoi il vit dans `core`.** Un echange
designe sa piece par un couple `(document_type, document_id)` OPAQUE — c'est
la decision structurante n°2 du cahier, et `apps/flows/module.py` la tient
litteralement : `dependencies=("core",)`. L'ecran de journal ne peut donc ni
importer `accounting`, ni `reverse("accounting:detail")` en dur : le jour ou
il le ferait, le socle cesserait d'etre un socle et deviendrait un neuvieme
module couple aux huit autres.

Le sens de la declaration est donc le meme que partout ailleurs dans ce
depot : **c'est le module metier qui se declare**, depuis son
`apps.py::ready()`, exactement comme il declare ses rapports, ses anomalies,
ses outils de copilote et ses schemas de sortie.

**Pourquoi pas le registre de T0.** `OutboundDocument`
(`core.services.outbound_schemas`) porte deja un code `app.Modele` et
paraissait le support naturel. Il ne l'est pas : les echanges portent aussi
`partners.Partner` (l'operation OP8, verification d'identifiant fiscal), qui
n'est PAS une piece sortante et n'a aucun champ a emettre. L'y greffer
obligerait `partners` a declarer un schema de sortie fictif pour obtenir un
lien d'ecran. Deux registres, deux questions distinctes.

**Ce que ce registre ne promet pas.** Toutes les lignes du journal ne
designent pas une piece : `document_type` vaut `""` pour une publication
planifiee (un jeu de donnees, une disponibilite de boutique). « Chaque ligne
mene a sa piece » se lit donc : chaque ligne QUI EN DESIGNE UNE. L'ecran dit
l'autre cas plutot que de rendre un lien mort.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class DocumentScreen:
    """L'ecran de detail d'une piece liable.

    `code` s'ecrit `app_label.NomDeModele` — la meme clef que celle que
    `workflow.transitioned` porte sous `model` et que les echanges stockent
    dans `document_type`, pour qu'aucune table de correspondance
    supplementaire ne soit necessaire.

    `label` existe parce que `accounting.AccMove` n'est pas un mot de la
    langue d'un comptable. Le §10.3 refuse de remonter le vocabulaire
    technique tel quel — « la maniere la plus sure de rendre la console
    inutilisable » — et une colonne « Piece » qui afficherait le nom de
    classe serait exactement cela."""

    code: str
    label: str
    url_name: str
    kwarg: str

    def __post_init__(self) -> None:
        if self.code.count(".") != 1 or not all(self.code.split(".")):
            raise ValidationError(
                _("Le code d'une piece s'ecrit « app.Modele » — recu « %(code)s ».")
                % {"code": self.code}
            )
        if ":" not in self.url_name:
            raise ValidationError(
                _(
                    "« %(url)s » n'est pas une route nommee d'application "
                    "(« app:nom ») : le journal ne pourrait pas la resoudre."
                )
                % {"url": self.url_name}
            )


_SCREENS: dict[str, DocumentScreen] = {}


def register_document_screen(screen: DocumentScreen) -> None:
    """Declare ou est visible une piece. Idempotent sur le code.

    Refuse un code deja pris par une AUTRE route : deux declarations pour le
    meme modele rendraient la destination du lien dependante de l'ordre de
    chargement des applications — c'est-a-dire qu'un clic mènerait ailleurs
    selon `INSTALLED_APPS`."""
    existant = _SCREENS.get(screen.code)
    if existant is not None and existant != screen:
        raise ValidationError(
            _(
                "La piece « %(code)s » est deja rattachee a « %(vieux)s » ; "
                "« %(neuf)s » la rattacherait ailleurs. Le lien du journal "
                "dependrait alors de l'ordre de chargement des applications."
            )
            % {"code": screen.code, "vieux": existant.url_name, "neuf": screen.url_name}
        )
    _SCREENS[screen.code] = screen


def document_screen_codes() -> frozenset[str]:
    return frozenset(_SCREENS)


def document_label(document_type: str) -> str:
    """Le nom lisible d'une piece, ou le code brut a defaut.

    Rendre le code plutot que rien : une ligne de journal dont la piece
    n'est pas declaree reste consultable, et le code brut dit au moins a
    l'exploitant du produit ce qu'il faut declarer."""
    screen = _SCREENS.get(document_type)
    return screen.label if screen is not None else document_type


def resolve_document_url(document_type: str, document_id: UUID | str | None) -> str | None:
    """L'URL de la piece designee, ou `None`.

    Rend `None` — jamais une exception — dans les trois cas ou il n'y a
    legitimement rien a montrer : l'echange ne designe aucune piece
    (publication planifiee), le module de la piece n'a pas d'ecran de
    detail, ou la route a change de forme. Une console qui tomberait sur une
    ligne mal formee cesserait d'afficher les mille autres."""
    if not document_type or document_id is None:
        return None
    screen = _SCREENS.get(document_type)
    if screen is None:
        return None
    try:
        return reverse(screen.url_name, kwargs={screen.kwarg: document_id})
    except NoReverseMatch:
        return None


__all__ = [
    "DocumentScreen",
    "document_label",
    "document_screen_codes",
    "register_document_screen",
    "resolve_document_url",
]
