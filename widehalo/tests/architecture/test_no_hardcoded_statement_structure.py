"""Garde-fou bloquant : cahier des charges WideHalo v3, Phase 1, §13.3
(ACC-2) — « Un test vérifie qu'aucun numéro de compte **ni structure d'état
financier** n'est écrit en dur dans le code applicatif », et §13.3 encore :
« Les états financiers sont produits selon la structure du référentiel actif
du tenant, jamais selon une structure codée en dur. »

La moitie « numero de compte » est couverte par
`test_no_hardcoded_account_numbers.py`. Celle-ci couvre la seconde moitie,
qui n'avait aucune garde et qui etait le foyer principal : jusqu'au sprint
D10-3, `apps/accounting/services/reports.py` portait

- `_CR_NATURE_MAPPING` — 12 postes du compte de resultat et 61 prefixes de
  compte, « retranscrits VERBATIM depuis l'Annexe II du PCG 2005 » ;
- la cascade des neuf soldes intermediaires I a IX, ecrite en Python ;
- `_ASSET_TYPE_ORDER`/`_LIABILITY_TYPE_ORDER`, l'ordre de presentation du
  bilan.

Tout cela vit desormais dans `AccFramework.statement_structure`. Ce test
empeche la reintroduction des deux formes, plutot que de constater apres coup
qu'un referentiel a ete recode.

**Limite assumee** : ce test reconnait les deux FORMES qui existaient, il ne
prouve pas qu'aucune structure ne puisse jamais etre exprimee autrement. Un
garde-fou syntaxique ne remplace pas la revue ; il rend le retour en arriere
bruyant.
"""

from __future__ import annotations

import ast
from pathlib import Path

ACCOUNTING_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "accounting"

_EXCLUDED_DIR_NAMES = {"migrations", "tests", "fixtures", "__pycache__"}

# Une entree de table de passage compte -> poste d'etat financier : un
# dictionnaire qui nomme un poste ET dit comment l'agreger.
_POSTE_KEYS = {"label"}
_AGGREGATION_KEYS = {"additive", "subtractive", "natural"}


def _accounting_source_files() -> list[Path]:
    return [
        path
        for path in ACCOUNTING_DIR.rglob("*.py")
        if not any(part in _EXCLUDED_DIR_NAMES for part in path.relative_to(ACCOUNTING_DIR).parts)
    ]


def _dict_string_keys(node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _statement_structure_findings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = _dict_string_keys(node)
            if keys >= _POSTE_KEYS and keys & _AGGREGATION_KEYS:
                findings.append(
                    f"{path.name}:{node.lineno} — table de passage compte -> poste "
                    f"d'etat financier ({sorted(keys & (_POSTE_KEYS | _AGGREGATION_KEYS))})"
                )
                continue
            # Ordre de presentation du bilan : {AccAccount.TYPE_X: 0, ...}
            type_keys = [
                key
                for key in node.keys
                if isinstance(key, ast.Attribute) and key.attr.startswith("TYPE_")
            ]
            int_values = [
                value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, int)
            ]
            if len(type_keys) >= 2 and len(int_values) == len(node.values):
                findings.append(
                    f"{path.name}:{node.lineno} — ordre de presentation par type de compte"
                )
    return findings


def test_no_financial_statement_structure_is_written_in_python() -> None:
    violations: list[str] = []
    for path in _accounting_source_files():
        violations.extend(_statement_structure_findings(path))

    assert not violations, (
        "Structure d'etat financier codee en dur (cahier Phase 1 §13.3, ACC-2) — "
        "elle doit vivre dans `AccFramework.statement_structure`, pas dans le "
        "code :\n" + "\n".join(sorted(violations))
    )


def _findings_for_source(tmp_path: Path, source: str) -> list[str]:
    module = tmp_path / "sample.py"
    module.write_text(source, encoding="utf-8")
    return _statement_structure_findings(module)


def test_the_detector_sees_a_reintroduced_mapping_table(tmp_path: Path) -> None:
    """Auto-test — sans quoi le garde-fou serait un theatre de securite.

    Forme exacte de l'ancien `_CR_NATURE_MAPPING`."""
    source = (
        "_CR = [\n"
        '    {"label": "Chiffre d\'affaires", "natural": "credit",\n'
        '     "additive": ("701", "702"), "subtractive": ()},\n'
        "]\n"
    )
    assert _findings_for_source(tmp_path, source)


def test_the_detector_sees_a_reintroduced_presentation_order(tmp_path: Path) -> None:
    """Forme exacte des anciens `_ASSET_TYPE_ORDER`/`_LIABILITY_TYPE_ORDER`."""
    source = "_ORDER = {\n    AccAccount.TYPE_ASSET: 0,\n    AccAccount.TYPE_STOCK: 1,\n}\n"
    assert _findings_for_source(tmp_path, source)


def test_an_ordinary_dictionary_is_not_a_violation(tmp_path: Path) -> None:
    """La borne du detecteur : un dictionnaire qui porte un libelle sans dire
    comment agreger des comptes n'est pas une structure d'etat financier."""
    assert _findings_for_source(tmp_path, '_ROWS = [{"label": "Total", "amount": 0}]\n') == []
