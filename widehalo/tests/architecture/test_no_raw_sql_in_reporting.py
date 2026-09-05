"""Garde-fou bloquant (BI-2) : « Aucune requete SQL brute n'est acceptee en
entree d'un rapport ; les indicateurs sont construits par l'ORM sur des
donnees deja isolees par tenant. »

L'enjeu n'est pas la lisibilite mais l'isolation. Le socle multi-tenant
repose sur la Row-Level Security de PostgreSQL, dont le predicat est arme
par `SET LOCAL app.tenant_id` (`apps.core.middleware`/`tenant_context`). Un
`cursor.execute()` avec interpolation de chaine dans un chemin de rapport
rouvre les deux portes d'un coup : l'injection SQL, et la fuite inter-tenant
si la requete atteint une table dont la politique n'est pas activee.

Trois modules sont scrutes : `bi`, `analytics` et `reporting` — les trois
qui construisent des indicateurs a partir de saisies utilisateur (filtres,
dimensions, definitions d'indicateur). Aucun n'en contient aujourd'hui : la
garde rend opposable ce que le code fait deja, plutot que de corriger un
defaut. C'est le moment ou une regle coute le moins cher a poser.

**Limite assumee** : detection syntaxique. Un appel construit dynamiquement
(`getattr(qs, "ra" + "w")`) echapperait au motif — hors du modele de menace,
qui vise l'ajout distrait d'une requete brute, pas son maquillage.

Les usages legitimes du socle (`apply_rls` pour le DDL d'activation de la
RLS, `middleware`/`tenant_context` pour le `SET LOCAL` parametre,
`api_health` pour un `SELECT 1`) vivent tous dans `apps/core` et ne sont
donc pas dans le perimetre scrute : ils n'ont pas besoin d'exception, et
leur donner une exception ici laisserait croire que ce fichier les couvre.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.architecture._ast_utils import APPS_DIR, iter_app_python_files

SCRUTINISED_APPS = ("analytics", "bi", "reporting")

# Appels interdits dans le chemin des rapports. `RawSQL` est une expression
# et non un appel de methode : il est detecte par son nom seul.
_FORBIDDEN_ATTRIBUTES = {"raw", "extra", "execute", "executemany"}
_FORBIDDEN_NAMES = {"RawSQL", "RawQuery"}

# Exceptions motivees. Vide a dessein : aucune requete brute n'existe
# aujourd'hui dans ces trois modules, et la premiere qui voudrait y entrer
# doit etre discutee, pas ajoutee ici par reflexe.
_ALLOWLIST: dict[str, str] = {}


def _findings() -> list[str]:
    findings: list[str] = []
    for app in SCRUTINISED_APPS:
        for path in iter_app_python_files(app):
            findings.extend(_findings_in(path))
    return findings


def _findings_in(path: Path) -> list[str]:
    relative = str(path.relative_to(APPS_DIR))
    if relative in _ALLOWLIST:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_ATTRIBUTES:
            findings.append(f"{relative}:{node.lineno} : appel a `.{func.attr}(`")
        elif isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
            findings.append(f"{relative}:{node.lineno} : appel a `{func.id}(`")
    return findings


def test_no_raw_sql_in_the_reporting_path() -> None:
    findings = _findings()
    assert not findings, (
        "SQL brut dans le chemin des rapports (bi/analytics/reporting) — "
        "l'isolation par tenant repose sur la RLS armee par l'ORM :\n"
        + "\n".join(f"  - {line}" for line in findings)
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    obsolete = [name for name in _ALLOWLIST if not (APPS_DIR / name).exists()]
    assert not obsolete, f"Exception(s) sans fichier correspondant : {obsolete}"


def test_the_detector_catches_a_raw_query() -> None:
    """Auto-test du detecteur — sans quoi le garde-fou serait un theatre de
    securite (`test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    offender = APPS_DIR / "bi" / "_detecteur_factice.py"
    offender.write_text(
        "from django.db.models.expressions import RawSQL\n"
        "def leak(cursor, qs, tenant_id):\n"
        "    cursor.execute(f'SELECT * FROM bi_report WHERE tenant_id = {tenant_id}')\n"
        "    qs.raw('SELECT 1')\n"
        "    return RawSQL('SELECT 1', [])\n",
        encoding="utf-8",
    )
    try:
        findings = _findings_in(offender)
    finally:
        offender.unlink()
    assert len(findings) == 3, findings
    assert any(".execute(" in line for line in findings)
    assert any(".raw(" in line for line in findings)
    assert any("RawSQL(" in line for line in findings)
