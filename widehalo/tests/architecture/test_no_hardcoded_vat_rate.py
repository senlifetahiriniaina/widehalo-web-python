"""Garde-fou bloquant (SAL-5) : le taux de TVA est une donnee du tenant, pas
une constante du code.

Le taux vit dans `AccTax.rate` — une table par tenant, avec ses dates de
validite (`valid_from`/`valid_to`) — et n'est lu que par
`apps.accounting.services.taxes` et `public.get_default_sale_tax`. La cible
etait donc deja propre : la garde rend opposable un invariant respecte,
plutot que de corriger un defaut.

Ce qu'elle protege : un taux ecrit en Python survit a la loi de finances qui
le change. Le jour ou le taux malgache bouge, la correction doit etre une
ligne de table dataee, applicable par le comptable, pas une livraison — et
surtout pas une livraison qui reecrirait retroactivement des factures
emises sous l'ancien taux.

**Ce que la garde ne couvre pas, et qui est plus grave** : SAL-5 porte sur
l'ORIGINE du taux, pas sur son application. `apps.sales.services.orders`
pose `amount_tax = Decimal(0)` — le module Sales ne calcule aucune taxe, et
seul le POS applique `get_default_sale_tax`. Le critere reste satisfait au
sens strict, l'ecart fonctionnel est reel, et il est signale au maitre
d'ouvrage plutot que dissimule derriere une garde verte.

**Limite assumee** : detection d'un litteral au voisinage d'un mot « TVA ».
Un taux stocke dans une constante nommee neutralement, loin de tout indice,
echapperait au motif. L'indice est volontairement etroit (« tva »/« vat »,
jamais « rate » seul) : le mot « rate » apparait partout, et l'elargir
ferait remonter l'IRCM — une retenue a la source sur revenus de capitaux
mobiliers a 20 %, qui n'est pas une TVA et dont le taux legal est
explicitement documente dans `apps.accounting.services.ircm`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.architecture._ast_utils import APPS_DIR, iter_app_python_files

SCRUTINISED_APPS = ("accounting", "sales", "pos", "purchase")

# `\b` ne convient pas : `_` est un caractere de mot, donc `\btva\b` ne
# verrait pas `TAUX_TVA_PAR_DEFAUT` — exactement la forme qu'on cherche.
_VAT_HINT = re.compile(
    r"(?<![A-Za-z])(tva|vat|taxe sur la valeur|sale_tax|default_tax)(?![A-Za-z])",
    re.IGNORECASE,
)
# Deux indices independants sont exiges : le sujet (TVA, au voisinage) et la
# nature du litteral (un taux, sur sa propre ligne). Un seul des deux suffirait
# a produire du bruit — `vat_line_index = len(lines) - 1` porte le sujet sans
# etre un taux, `dt.date(year, 2, 15)` porte des entiers sans etre un taux.
_RATE_TOKEN = re.compile(r"(rate|taux|pct|percent)", re.IGNORECASE)
_HINT_PROXIMITY_LINES = 3
# Un taux, sous les trois ecritures possibles : pourcentage entier, decimal,
# ou fraction. Bornes larges (1 a 40 %) : le but est d'attraper un taux
# plausible, pas de deviner lequel.
_RATE_PERCENT = re.compile(r"^(?:[1-9]|[12]\d|3\d|40)(?:\.\d+)?$")
_RATE_FRACTION = re.compile(r"^0\.(?:0[1-9]|[1-3]\d|40)\d*$")

_ALLOWLIST: dict[str, str] = {
    "accounting/services/ircm.py": (
        "L'IRCM (retenue a la source sur revenus de capitaux mobiliers) n'est "
        "pas une TVA : son taux de 20 % est un taux legal du CGI malgache, "
        "porte comme valeur PAR DEFAUT d'un parametre surchargeable "
        "(`rate_pct`), et deja disclose comme tel. Le fichier n'est ici que "
        "parce que le voisinage y nomme le regime fiscal "
        "`FISCAL_REGIME_REAL_NO_VAT` — l'indice du sujet, pas le taux. "
        "DETTE RECONNUE, hors perimetre de SAL-5 : ce taux gagnerait a "
        "rejoindre `RegulatoryParameter` comme les baremes de paie, avec sa "
        "date d'effet ; c'est un chantier fiscal, pas un chantier TVA."
    ),
}


def _is_rate_literal(node: ast.AST) -> bool:
    if not isinstance(node, ast.Constant):
        return False
    if isinstance(node.value, bool):
        return False
    # Les flottants sont compares numeriquement : `str(0.20)` vaut "0.2", et
    # un motif textuel manquerait la forme la plus courante d'un taux ecrit
    # en fraction.
    if isinstance(node.value, float):
        return 0.01 <= node.value <= 0.40 or 1 <= node.value <= 40
    if isinstance(node.value, int):
        return 1 <= node.value <= 40
    if isinstance(node.value, str):
        return bool(_RATE_PERCENT.match(node.value) or _RATE_FRACTION.match(node.value))
    return False


def _line_looks_like_a_rate(line: str) -> bool:
    return bool(_RATE_TOKEN.search(line))


def _findings_in(path: Path, source: str) -> list[str]:
    relative = str(path.relative_to(APPS_DIR))
    if relative in _ALLOWLIST:
        return []
    lines = source.splitlines()
    hint_lines = {number for number, line in enumerate(lines, start=1) if _VAT_HINT.search(line)}
    if not hint_lines:
        return []
    tree = ast.parse(source, filename=str(path))
    findings = []
    for node in ast.walk(tree):
        if not _is_rate_literal(node):
            continue
        excerpt = lines[node.lineno - 1].strip()[:80]
        if not _line_looks_like_a_rate(excerpt):
            continue
        if any(abs(node.lineno - hint) <= _HINT_PROXIMITY_LINES for hint in hint_lines):
            findings.append(f"{relative}:{node.lineno} : {node.value!r} — {excerpt}")
    return findings


def _all_findings() -> list[str]:
    findings: list[str] = []
    for app in SCRUTINISED_APPS:
        for path in iter_app_python_files(app):
            findings.extend(_findings_in(path, path.read_text(encoding="utf-8")))
    return findings


def test_no_vat_rate_is_written_in_the_code() -> None:
    findings = _all_findings()
    assert not findings, (
        "Taux de TVA potentiellement ecrit en dur — le taux est une ligne "
        "`AccTax` datee, par tenant :\n" + "\n".join(f"  - {line}" for line in findings)
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    obsolete = [name for name in _ALLOWLIST if not (APPS_DIR / name).exists()]
    assert not obsolete, f"Exception(s) sans fichier correspondant : {obsolete}"


def test_every_exception_is_motivated() -> None:
    thin = [name for name, motive in _ALLOWLIST.items() if len(motive.strip()) < 40]
    assert not thin, f"Exception(s) sans motif utilisable : {thin}"


def test_the_detector_catches_a_hardcoded_rate() -> None:
    """Auto-test du detecteur — sans quoi le garde-fou serait un theatre de
    securite (`test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    source = 'TAUX_TVA_PAR_DEFAUT = "20"\nTAUX_TVA_FRACTION = 0.20\n'
    findings = _findings_in(APPS_DIR / "sales" / "_detecteur_factice.py", source)
    assert len(findings) == 2, findings


def test_the_detector_ignores_a_rate_far_from_any_vat_word() -> None:
    """Le taux de l'IRCM (retenue a la source sur revenus de capitaux
    mobiliers) est un taux legal documente, pas une TVA : le confondre serait
    le faux positif qui ferait desactiver la garde."""
    source = "# IRCM : retenue a la source\nRATE_IRCM = 20\n"
    assert _findings_in(APPS_DIR / "accounting" / "_detecteur_factice.py", source) == []
