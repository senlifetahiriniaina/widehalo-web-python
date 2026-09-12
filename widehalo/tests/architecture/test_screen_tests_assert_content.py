"""E-6 — un test d'ecran ne se contente jamais d'un code de statut.

**Ce que la classe a coute, mesure sur ce seul cycle.** Un
`assert status_code == 302` a laisse passer une redirection vers `/mfa/`
prise pour une redirection de succes : le POST n'ecrivait rien, et le test
etait vert. Un `assert status_code == 200` laisse passer un gabarit vide,
une liste qui a perdu ses lignes, une colonne qui rend un UUID. Et
`assert X or status_code == 200` est vrai QUOI QU'IL ARRIVE — la liste des
factures en portait un.

Un code de statut dit que la ROUTE existe. `test_all_pages_smoke.py` le
verifie deja, pour les 45 routes, et c'est son role. Un test d'ECRAN doit
dire ce que l'ecran montre.

**La dette est declaree, nommee, et doit retrecir.** Elle n'est pas un
cimetiere : trois gardes l'en empechent — une entree inconnue fait echouer,
une entree qui a ete corrigee fait echouer, et le total ne peut pas monter.
"""

from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: Les fichiers de tests d'ecran des quatre modules prioritaires.
#:
#: **H-2b : ce tuple en comptait QUATRE, et les modules en ont HUIT.**
#: `crm` et `accounting` ont chacun trois fichiers d'ecran — l'ecran
#: principal, la configuration, les rapports. La garde ne regardait donc
#: qu'une moitie du perimetre qu'elle pretend gouverner, et cinq tests
#: muets vivaient dans l'angle mort sans figurer dans `DETTE`. Le chiffre
#: publie en 0.1.9 (« 9 tests muets ») valait pour la liste declaree, pas
#: pour la mesure : elle en donne 14.
#:
#: C'est la meme famille d'erreur que la docstring ci-dessus decrit — un
#: instrument dont le corpus est plus etroit que son objet. Elle s'est
#: produite ICI, dans la garde ecrite pour s'en premunir.
FICHIERS = (
    "ui/test_sales_screens.py",
    "ui/test_crm_screens.py",
    "ui/test_crm_config_screens.py",
    "ui/test_crm_reports_screens.py",
    "ui/test_accounting_screens.py",
    "ui/test_accounting_config_screens.py",
    "ui/test_accounting_reports_screens.py",
    "ui/test_logistics_screens.py",
)

#: Dette declaree au 11/09/2026, apres la correction de neuf tests muets.
#: Chaque entree est un test qui n'assere encore qu'un code de statut. Cette
#: liste doit RETRECIR ; elle ne peut jamais s'allonger.
DETTE: frozenset[str] = frozenset(
    {
        "ui/test_sales_screens.py::test_quotation_create_screen",
        "ui/test_sales_screens.py::test_order_create_screen",
        "ui/test_sales_screens.py::test_reports_index_renders",
        "ui/test_sales_screens.py::test_config_recurrences_screen_renders",
        "ui/test_logistics_screens.py::test_trip_list_and_create_screens",
        "ui/test_logistics_screens.py::test_trip_template_list_screen_create",
        "ui/test_logistics_screens.py::test_config_screens_render_and_create",
        "ui/test_logistics_screens.py::test_reports_screen_and_downloads",
    }
)


def _tests_muets() -> set[str]:
    """Les tests dont TOUTES les assertions portent sur un code de statut."""
    muets: set[str] = set()
    for relatif in FICHIERS:
        chemin = RACINE / relatif
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if not (isinstance(noeud, ast.FunctionDef) and noeud.name.startswith("test_")):
                continue
            assertions = [a for a in ast.walk(noeud) if isinstance(a, ast.Assert)]
            if not assertions:
                continue
            if all("status_code" in ast.dump(a.test) for a in assertions):
                muets.add(f"{relatif}::{noeud.name}")
    return muets


def test_la_mesure_voit_encore_des_tests_d_ecran() -> None:
    """Auto-test : un chemin faux rendrait zero test, et la garde
    declarerait tout le depot sain. Trois instruments de cette vague se sont
    trompes exactement ainsi."""
    total = 0
    for relatif in FICHIERS:
        arbre = ast.parse((RACINE / relatif).read_text(encoding="utf-8"))
        total += sum(
            1
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        )
    # Plancher recalcule sur le corpus REEL de huit fichiers : 79 tests
    # mesures au 12/09. A 45, il restait celui des quatre fichiers et ne
    # protegeait plus rien — un fichier entier pouvait sortir du tuple sans
    # qu'il bronche.
    assert total >= 70, f"{total} tests d'ecran trouves — l'instrument ne mesure plus rien."


def test_aucun_test_d_ecran_neuf_ne_se_contente_d_un_statut() -> None:
    neufs = sorted(_tests_muets() - DETTE)
    assert not neufs, (
        "Ces tests d'ecran n'assertent qu'un code de statut :\n  "
        + "\n  ".join(neufs)
        + "\n\nUn code de statut dit que la route existe — `test_all_pages_smoke.py` "
        "le verifie deja. Un test d'ecran doit dire ce que l'ecran MONTRE : "
        "relisez l'objet en base apres un POST, ou cherchez dans le rendu la "
        "valeur que la page est censee porter."
    )


def test_la_dette_declaree_ne_contient_aucune_entree_perimee() -> None:
    """Anti-cimetiere : une entree corrigee doit SORTIR de la liste, sinon
    la dette ne retrecit jamais et le chiffre publie devient faux."""
    muets = _tests_muets()
    perimees = sorted(DETTE - muets)
    assert not perimees, (
        "Ces entrees de la dette ne sont plus muettes (corrigees, renommees "
        "ou supprimees) — retirez-les de `DETTE` :\n  " + "\n  ".join(perimees)
    )
