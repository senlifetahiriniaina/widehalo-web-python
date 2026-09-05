"""Garde-fou bloquant (FOR-5) : « le calendrier applique jours ouvres/feries
malgaches lus en table de reference ; un test verifie qu'aucune date feriee
n'est ecrite dans le code ».

Le critere nommait ce test ; il n'existait pas. La cible, elle, etait deja
propre : `apps.forecast.services.calendar` ne code que la regle du week-end
et lit tout le reste dans `ForHoliday`, `apps.presence.services.calendar`
passe par `RegulatoryParameter`. La garde rend donc opposable ce que le code
fait deja — le moment ou une regle coute le moins cher a poser.

Ce qu'elle protege est concret : un jour ferie ecrit en Python est un jour
ferie que l'exploitant ne peut pas corriger. Le calendrier malgache ajoute
des journees chomees ponctuelles (scrutin, deuil national) qui ne figurent
dans aucune liste livree ; elles doivent pouvoir entrer par un ecran, pas
par une livraison logicielle.

**Deux detecteurs, parce qu'une date feriee se cache de deux facons :**

1. une date litterale a PROXIMITE (quatre lignes) d'un mot qui parle de
   jours feries — meme patron d'indice contextuel que
   `test_no_hardcoded_account_numbers.py::_ACCOUNT_NAME_HINT`, mais borne a
   un voisinage : l'indice cherche a l'echelle du fichier entier produisait
   un faux positif reel (`payroll/services/seed.py` contient le multiplicatif
   d'heure supplementaire « ferie » a la ligne 124 et des dates d'effet
   reglementaires a la ligne 25 — deux sujets sans rapport) ;
2. une collection d'au moins trois dates litterales, ou de trois couples
   (mois, jour) — trois dates groupees sont un calendrier, quel que soit le
   nom du fichier.

**Limite assumee** : une date construite dynamiquement
(`dt.date(year, MONTH, DAY)` avec des constantes nommees ailleurs) echappe
au premier detecteur si le fichier ne porte aucun indice, et au second si
elle est seule. Le modele de menace vise la liste de jours feries recopiee
dans le code, pas son camouflage.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.architecture._ast_utils import APPS_DIR, discover_apps, iter_app_python_files

_HOLIDAY_HINT = re.compile(
    r"(ferie|férié|feries|fériés|holiday|jour[s]?[ _-]chome|paque|pâque|pentecote|"
    r"pentecôte|toussaint|assomption|ascension|independance|indépendance|armistice)",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Distance en lignes entre l'indice et la date pour que le rapprochement ait
# un sens. Assez large pour couvrir une entree de liste sur plusieurs lignes,
# assez etroite pour qu'un mot present ailleurs dans un gros fichier ne
# contamine pas tout.
_HINT_PROXIMITY_LINES = 4
_DAY_MONTH = re.compile(r"^\d{1,2}[-/]\d{1,2}$")

# Exceptions motivees, avec test d'obsolescence ci-dessous.
_ALLOWLIST: dict[str, str] = {
    "accounting/services/tax_calendar.py": (
        "Echeances DECLARATIVES de la DGI (IRSA, TVA, IS, IR, IRCM, DCOM, "
        "TVM, IFT, IFPB, depot des etats financiers) — des dates limites de "
        "depot, jamais des jours chomes. Les confondre avec des jours feries "
        "serait le faux positif exact que ce fichier doit eviter : elles ne "
        "rendent aucun jour non ouvre, et un jour ferie ne decale aucune "
        "d'entre elles. Elles portent deja leur propre reserve de mise a "
        "jour (communique DGI) en tete de module."
    ),
}


def _is_literal_date_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in {"date", "datetime"} or len(node.args) < 2:
        return False
    return all(isinstance(arg, ast.Constant) and isinstance(arg.value, int) for arg in node.args)


def _is_literal_date_string(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and bool(_ISO_DATE.match(node.value) or _DAY_MONTH.match(node.value))
    )


def _is_month_day_pair(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Tuple)
        and len(node.elts) == 2
        and all(isinstance(e, ast.Constant) and isinstance(e.value, int) for e in node.elts)
    )


def _findings_in(path: Path, source: str) -> list[str]:
    relative = str(path.relative_to(APPS_DIR))
    if relative in _ALLOWLIST:
        return []
    tree = ast.parse(source, filename=str(path))
    findings: list[str] = []
    hint_lines = {
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if _HOLIDAY_HINT.search(line)
    }

    def near_a_hint(lineno: int) -> bool:
        return any(abs(lineno - hint) <= _HINT_PROXIMITY_LINES for hint in hint_lines)

    for node in ast.walk(tree):
        # 1. date litterale au voisinage d'un mot qui parle de jours feries
        if (_is_literal_date_call(node) or _is_literal_date_string(node)) and near_a_hint(
            node.lineno
        ):
            findings.append(
                f"{relative}:{node.lineno} : date litterale au voisinage d'un jour ferie"
            )
        # 2. collection d'au moins trois dates ou couples (mois, jour)
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            literal_dates = [
                element
                for element in node.elts
                if _is_literal_date_call(element)
                or _is_literal_date_string(element)
                or _is_month_day_pair(element)
            ]
            if len(literal_dates) >= 3:
                count = len(literal_dates)
                findings.append(
                    f"{relative}:{node.lineno} : collection de {count} dates litterales"
                )
    return findings


def _all_findings() -> list[str]:
    findings: list[str] = []
    for app in discover_apps():
        for path in iter_app_python_files(app):
            findings.extend(_findings_in(path, path.read_text(encoding="utf-8")))
    return findings


def test_no_holiday_date_is_written_in_the_code() -> None:
    findings = _all_findings()
    assert not findings, (
        "Date(s) feriee(s) potentiellement ecrite(s) en dur — un jour ferie "
        "n'existe QUE via une ligne `ForHoliday`, chargeable par "
        "`manage.py load_mg_holidays` et corrigeable a l'ecran :\n"
        + "\n".join(f"  - {line}" for line in findings)
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    obsolete = [name for name in _ALLOWLIST if not (APPS_DIR / name).exists()]
    assert not obsolete, f"Exception(s) sans fichier correspondant : {obsolete}"


def test_every_exception_is_motivated() -> None:
    thin = [name for name, motive in _ALLOWLIST.items() if len(motive.strip()) < 40]
    assert not thin, f"Exception(s) sans motif utilisable : {thin}"


def test_the_detector_catches_a_holiday_table(tmp_path: Path) -> None:
    """Auto-test du detecteur — sans quoi le garde-fou serait un theatre de
    securite (`test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    source = (
        "import datetime as dt\n"
        "JOURS_FERIES = [\n"
        "    dt.date(2026, 1, 1),\n"
        "    dt.date(2026, 6, 26),\n"
        "    dt.date(2026, 12, 25),\n"
        "]\n"
    )
    findings = _findings_in(APPS_DIR / "forecast" / "_detecteur_factice.py", source)
    assert findings, "Une liste de trois jours feries doit etre detectee."
    assert any("collection" in line for line in findings)
    assert any("voisinage d'un jour ferie" in line for line in findings)


def test_the_detector_catches_a_month_day_table() -> None:
    """Le camouflage le plus naturel : des couples (mois, jour) sans annee,
    dans un fichier qui ne dit jamais le mot « ferie »."""
    source = "FIXES = [(1, 1), (5, 1), (6, 26), (12, 25)]\n"
    findings = _findings_in(APPS_DIR / "forecast" / "_detecteur_factice.py", source)
    assert any("collection de 4" in line for line in findings), findings
