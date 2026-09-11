"""D-0bis — un en-tete de colonne est du texte affiche, donc traduisible.

**Pourquoi une garde, et pas seulement une correction.** Depuis D-0, la
premiere ligne d'un CSV et d'un XLSX porte `column.label` — le meme texte
que l'en-tete du tableau a l'ecran. Une colonne ajoutee demain avec
`label="Reference"` reintroduirait d'un coup trois defauts : un en-tete non
accentue a l'ecran, le meme dans deux formats d'export, et un texte que
`makemessages` ne verra jamais.

**Le jeu ferme se verifie contre une liste INDEPENDANTE** (lecon F60) : les
noms des quatre modules sont ecrits ici, pas lus d'un registre.

**Le plancher n'est pas decoratif.** Trois instruments de cette vague ont
declare un systeme sain en ne mesurant rien : filtre par fichier avant de
deballer `__wrapped__` (C-1c), racine avec un `/widehalo` de trop (D-0),
recherche limitee aux noms de routes (T10). Si cette garde cesse de voir des
colonnes, elle doit tomber au lieu de passer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Ecrits ici, jamais lus d'un registre du code teste.
MODULES_GARDES = ("sales", "crm", "accounting", "logistics")

#: Plancher mesure le 11/09/2026 : 79 colonnes dans les quatre modules. Il
#: peut monter ; s'il s'effondre, c'est l'instrument qui est casse.
PLANCHER = 60

RACINE = Path(__file__).resolve().parents[2] / "apps"


def _colonnes_du_module(module: str) -> list[tuple[str, int, ast.Call]]:
    trouvees: list[tuple[str, int, ast.Call]] = []
    for chemin in sorted((RACINE / module).rglob("*.py")):
        if "/migrations/" in str(chemin) or "/tests/" in str(chemin):
            continue
        arbre = ast.parse(chemin.read_bytes())
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Call) and getattr(noeud.func, "id", "") == "Column":
                trouvees.append((str(chemin.relative_to(RACINE.parent)), noeud.lineno, noeud))
    return trouvees


def test_la_mesure_voit_encore_des_colonnes() -> None:
    """L'auto-test de l'instrument : sans lui, un chemin faux rendrait zero
    colonne et la garde declarerait tout le depot sain."""
    total = sum(len(_colonnes_du_module(module)) for module in MODULES_GARDES)
    assert total >= PLANCHER, (
        f"{total} colonnes trouvees dans {MODULES_GARDES} — plancher {PLANCHER}. "
        "L'instrument ne mesure plus ce qu'il croit mesurer."
    )


@pytest.mark.parametrize("module", MODULES_GARDES)
def test_chaque_entete_de_colonne_est_traduisible(module: str) -> None:
    fautives = []
    for fichier, ligne, appel in _colonnes_du_module(module):
        libelle = next((mc.value for mc in appel.keywords if mc.arg == "label"), None)
        if libelle is None:
            fautives.append(f"{fichier}:{ligne} — aucun `label=`")
            continue
        enveloppe = isinstance(libelle, ast.Call) and getattr(libelle.func, "id", "") in {
            "_",
            "gettext_lazy",
            "pgettext_lazy",
        }
        if not enveloppe:
            rendu = getattr(libelle, "value", "<expression>")
            fautives.append(
                f"{fichier}:{ligne} — label={rendu!r} n'est pas traduisible ; "
                'ecrire label=_("…") avec `gettext_lazy as _` (une liste de '
                "colonnes est evaluee A L'IMPORT, jamais par requete)"
            )
    assert not fautives, "\n".join(fautives)
