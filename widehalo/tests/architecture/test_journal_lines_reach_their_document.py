"""Garde T8 (bloc H, CON-1) : une ligne de journal mene a sa piece.

**Le critere** : « Depuis toute piece metier, l'etat de ses echanges est
atteignable en un clic, **et reciproquement depuis toute ligne du
journal**. »

**Ce que cette garde empeche, et qui ne se verrait pas autrement.** Le
journal resout le lien par le registre `core.services.document_screens`, que
chaque module metier alimente depuis son `apps.py::ready()`. Un module qui
emettrait un echange sans declarer son ecran produirait des lignes de
journal SANS lien — et rien ne le signalerait : `resolve_document_url` rend
`None`, l'ecran affiche le libelle sans lien, et tout a l'air normal. Le
critere serait faux pour ce type de piece, en silence.

**La liste litterale n'est pas redondante.** Elle est INDEPENDANTE du
registre qu'elle surveille — lecon F60 du lot T6, ou une falsification
n'avait pas mordu parce que le test comparait un jeu ferme a sa propre
source. Ici : si `register_document_screens` cessait d'etre appelee dans
`ready()`, le registre serait vide, une garde qui se contenterait de
« chaque code declare a une route » passerait triomphalement sur zero code,
et le journal n'aurait plus un seul lien.
"""

from __future__ import annotations

import pytest
from apps.core.db.uuid7 import uuid7
from apps.core.services.document_screens import (
    document_label,
    document_screen_codes,
    resolve_document_url,
)
from django.urls import NoReverseMatch, reverse

#: Ecrit a la main. Ce sont les `document_type` que du code de PRODUCTION
#: ecrit reellement sur un echange (mesure T8), plus les pieces liables
#: declarees au lot T0 — un module qui declare une piece liable finira par
#: emettre un echange pour elle.
#:
#:   accounting.AccMove      `einvoice_submission.DOCUMENT_TYPE`, et les
#:                           encaissements (`payment_settlement`)
#:   partners.Partner        `fiscal_verification.DOCUMENT_TYPE` (OP8)
#:   sales.SalesOrder        piece liable declaree (T0), emise par declencheur
#:   sales.SalesQuotation    idem
#:   crm.CrmLead             idem
PIECES_QUI_ECHANGENT = {
    "accounting.AccMove",
    "partners.Partner",
    "sales.SalesOrder",
    "sales.SalesQuotation",
    "crm.CrmLead",
}


def test_every_document_type_that_exchanges_has_a_screen() -> None:
    """Sans ecran declare, la ligne existe et ne mene nulle part."""
    manquants = PIECES_QUI_ECHANGENT - document_screen_codes()
    assert not manquants, (
        f"Ces pieces emettent des echanges et n'ont pas d'ecran declare : "
        f"{sorted(manquants)}. Le journal les affichera sans lien, et CON-1 "
        "sera faux pour elles sans que rien ne le dise. A declarer dans "
        "`apps/<module>/services/document_screen_registration.py`."
    )


@pytest.mark.django_db
def test_every_declared_screen_actually_resolves_to_a_url() -> None:
    """Une route declaree mais introuvable est pire qu'aucune route : le
    registre affirme que la piece est atteignable, et le clic ne mene nulle
    part.

    Le test resout REELLEMENT l'URL au lieu de verifier que le nom de route
    ressemble a quelque chose — c'est la seule facon de detecter un
    renommage de route dans un module metier."""
    identifiant = uuid7()
    for code in sorted(document_screen_codes()):
        url = resolve_document_url(code, identifiant)
        assert url, (
            f"L'ecran declare pour « {code} » ne se resout pas : la route a "
            "probablement ete renommee ou son parametre a change de nom."
        )
        assert str(identifiant) in url, (
            f"L'URL rendue pour « {code} » ne porte pas l'identifiant de la piece : {url}"
        )


def test_a_line_without_a_document_yields_no_link_instead_of_a_dead_one() -> None:
    """**Toutes les lignes ne menent pas a une piece, et ce n'est pas un
    defaut.**

    Une publication planifiee — un jeu de donnees, une disponibilite de
    boutique (COM-3) — ne designe aucun document : `scheduling.py` ecrit
    `document_type=""`. « Chaque ligne mene a sa piece » se lit donc :
    chaque ligne QUI EN DESIGNE UNE.

    Sans ce test, la garde precedente passerait en ne regardant que les
    lignes commodes."""
    assert resolve_document_url("", uuid7()) is None
    assert resolve_document_url("accounting.AccMove", None) is None
    assert resolve_document_url("un.ModeleInconnu", uuid7()) is None


def test_each_piece_has_a_human_label_and_not_a_class_name() -> None:
    """§10.3 : le vocabulaire technique n'est jamais remonte tel quel.

    Une colonne « Piece » qui afficherait `accounting.AccMove` serait
    exactement ce que le cahier appelle « la maniere la plus sure de rendre
    la console inutilisable »."""
    for code in sorted(PIECES_QUI_ECHANGENT):
        libelle = document_label(code)
        assert libelle != code, f"« {code} » n'a pas de libellé lisible."
        assert "." not in libelle, (
            f"Le libellé de « {code} » ressemble encore à un nom de classe : {libelle}"
        )


def test_the_journal_route_exists() -> None:
    """Le fragment pose sur chaque piece pointe cette route. Si elle
    disparaissait, les quatre ecrans leveraient `NoReverseMatch` au rendu —
    c'est-a-dire un 500 sur la fiche d'une facture."""
    try:
        assert reverse("flows:journal")
    except NoReverseMatch as exc:  # pragma: no cover - le message importe
        pytest.fail(f"La route du journal des échanges n'existe plus : {exc}")
