"""Garde-fou bloquant : cahier des charges WideHalo v3, Phase 1, §13.3
(ACC-2) — « Un test vérifie qu'aucun numéro de compte ni structure d'état
financier n'est écrit en dur dans le code applicatif. » Ecart confirme par
l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md, ACC-2) : ce
test n'existait pas.

**Etat du depot depuis le sprint D10-3** : la structure des etats
financiers a quitte le code. `services/reports.py` portait la table de
passage `_CR_NATURE_MAPPING` (12 postes, 61 prefixes de compte
« retranscrits verbatim de l'Annexe II du PCG 2005 ») et la cascade des
neuf soldes intermediaires ; l'une et l'autre sont desormais des donnees
du referentiel (`AccFramework.statement_structure`), lues par
`income_statement`. **Son exemption est donc retiree de la liste
ci-dessous** — c'est precisement ce que le test d'obsolescence a signale
des que la table a disparu.

La resolution des comptes par defaut, elle, passe depuis D10-2 par le
registre `AccTenantDefaultAccount` puis, a defaut, par `AccAccount.type` :
aucun numero litteral dans ce chemin non plus.

Ce test ne pretend toujours pas couvrir tout ACC-2 a lui seul — il
n'inspecte que les litteraux CHAINE de 3 a 6 chiffres de `apps/accounting`,
hors `migrations/`, `tests/`, `fixtures/` et `management/`. Trois angles
morts subsistent et sont traites au sprint D10-6 : les codes a 1-2
chiffres (les prefixes « 76 »/« 77 » de `services/ircm.py`), les litteraux
ENTIERS (`account_class=6`), et le repertoire `management/`, ou
`seed_accounting.py` cree encore des comptes par leur numero."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ACCOUNTING_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "accounting"

_PCG_ACCOUNT_CODE_PATTERN = re.compile(r"^\d{3,6}$")

# Chaque entree DOIT rester documentee dans le fichier lui-meme (pas
# seulement ici) — cf. l'exemple illustratif de
# `views_imports.py::download_chart_of_accounts_template`/
# `download_cash_journal_template` (une valeur d'EXEMPLE affichee dans un
# modele XLSX telechargeable pour guider l'utilisateur qui le remplit —
# jamais lue ni utilisee par un automatisme, contrairement a l'autre
# entree de ce registre).
#
# `services/reports.py` a quitte cette liste au sprint D10-3 (la structure des
# etats financiers est portee par `AccFramework`) et
# `services/chart_of_accounts.py` au sprint D10-4 (compte d'attente et
# prefixes des journaux de tresorerie idem). Les deux fois, c'est le test
# d'obsolescence ci-dessous qui l'a signale des que les litteraux ont disparu.
ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES = {
    "views_imports.py",
}

# D10-6 : `management/` n'est plus exclu. Le repertoire etait un angle mort —
# `seed_accounting.py` y CREAIT des comptes par leur numero, donc sans plan
# rattache. Seuls les jeux de demonstration (`seed_*.py`) restent exemptes :
# une commande qui fabrique des donnees de demonstration connait legitimement
# les codes de la fixture qu'elle illustre, contrairement a une commande de
# chargement, qui doit passer par le referentiel.
_EXCLUDED_DIR_NAMES = {"migrations", "tests", "fixtures", "__pycache__"}
_EXCLUDED_FILE_PREFIXES = ("seed_",)


def _accounting_source_files() -> list[Path]:
    files = []
    for path in ACCOUNTING_DIR.rglob("*.py"):
        relative_parts = path.relative_to(ACCOUNTING_DIR).parts
        if any(part in _EXCLUDED_DIR_NAMES for part in relative_parts):
            continue
        if path.name.startswith(_EXCLUDED_FILE_PREFIXES):
            continue
        files.append(path)
    return files


_SHORT_PREFIX_PATTERN = re.compile(r"^\d{1,2}$")
# Un nom qui annonce qu'il porte des codes ou des prefixes de compte. Sert a
# reperer les prefixes courts sans noyer le test de faux positifs : "76" est
# un prefixe PCG dans `_FINANCIAL_INCOME_PREFIXES`, c'est un entier anodin
# partout ailleurs.
_ACCOUNT_NAME_HINT = re.compile(r"(ACCOUNT|COMPTE|PCG|PREFIX)", re.IGNORECASE)


def _short_prefix_findings(tree: ast.AST) -> list[tuple[int, str]]:
    """Angle mort n°1 : les prefixes de compte a un ou deux chiffres.

    `ircm.py` portait `_FINANCIAL_INCOME_PREFIXES = ("76", "77")` — en dur,
    hors liste d'exception, et invisible pour le motif a 3-6 chiffres."""
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(_ACCOUNT_NAME_HINT.search(name) for name in names):
            continue
        for child in ast.walk(node.value):
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and _SHORT_PREFIX_PATTERN.match(child.value)
            ):
                findings.append((child.lineno, child.value))
    return findings


def _account_class_findings(tree: ast.AST) -> list[tuple[int, str]]:
    """Angle mort n°2 : les litteraux ENTIERS de classe de compte.

    `account__account_class=6`, `account_class=4`, `account.account_class == 2`
    echappaient au test, qui n'inspecte que les chaines. La classe est une
    propriete du referentiel (`AccFramework.account_classes`), pas du code."""
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg and node.arg.endswith("account_class"):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                findings.append((node.value.lineno, f"{node.arg}={node.value.value}"))
        elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
            if node.left.attr != "account_class":
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, int):
                    findings.append((comparator.lineno, f"account_class == {comparator.value}"))
    return findings


def _hardcoded_pcg_literals(path: Path) -> list[tuple[int, str]]:
    """Numeros, prefixes et classes de compte ecrits en dur dans un fichier.

    Couvre depuis D10-6 les trois angles morts de la version initiale : les
    codes a 1-2 chiffres, les litteraux entiers de classe, et le repertoire
    `management/`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _PCG_ACCOUNT_CODE_PATTERN.match(node.value)
        ):
            findings.append((node.lineno, node.value))
    findings.extend(_short_prefix_findings(tree))
    findings.extend(_account_class_findings(tree))
    return sorted(set(findings))


def test_no_hardcoded_pcg_account_number_outside_the_documented_allowlist() -> None:
    violations: list[str] = []

    for path in _accounting_source_files():
        relative = str(path.relative_to(ACCOUNTING_DIR))
        findings = _hardcoded_pcg_literals(path)
        if not findings:
            continue
        if relative in ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES:
            continue
        for lineno, value in findings:
            violations.append(f"{relative}:{lineno} -> {value!r}")

    assert not violations, (
        "Numéro(s) de compte PCG 2005 codé(s) en dur hors de "
        "ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES (cahier Phase 1 §13.3, "
        "ACC-2) :\n" + "\n".join(sorted(violations))
    )


def test_allowlisted_files_still_exist_and_still_need_the_exemption() -> None:
    # Registre a jour : un fichier qui ne contient plus AUCUN numero en dur
    # (refactor vers la table de comptes par defaut) doit sortir de
    # l'allowlist, pas y rester comme une exemption fantome qui masquerait
    # un futur oubli sur le meme nom de fichier.
    stale = []
    for relative in ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES:
        path = ACCOUNTING_DIR / relative
        if not path.exists():
            stale.append(f"{relative} (fichier introuvable)")
            continue
        if not _hardcoded_pcg_literals(path):
            stale.append(f"{relative} (ne contient plus aucun numéro en dur)")

    assert not stale, (
        "Entrée(s) obsolète(s) dans ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES : "
        + ", ".join(stale)
    )


def _findings_for_source(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    module = tmp_path / "sample.py"
    module.write_text(source, encoding="utf-8")
    return _hardcoded_pcg_literals(module)


def test_the_detector_sees_a_plain_account_number(tmp_path: Path) -> None:
    """Auto-test du garde-fou — sans quoi il serait un theatre de securite
    (meme discipline que `test_module_boundaries.py`)."""
    findings = _findings_for_source(tmp_path, 'SUSPENSE = "471"\n')
    assert findings == [(1, "471")]


def test_the_detector_sees_a_short_prefix(tmp_path: Path) -> None:
    """Angle mort n°1 avant D10-6 : `ircm.py` portait
    `_FINANCIAL_INCOME_PREFIXES = ("76", "77")`, invisible pour le motif a
    3-6 chiffres."""
    findings = _findings_for_source(tmp_path, '_FINANCIAL_INCOME_PREFIXES = ("76", "77")\n')
    assert {value for _, value in findings} == {"76", "77"}


def test_a_short_number_outside_an_account_context_is_not_a_violation(tmp_path: Path) -> None:
    """Le motif court ne se declenche que sur un nom qui annonce des comptes :
    sans cette borne, tout `RETRY = "3"` du depot deviendrait un faux positif."""
    assert _findings_for_source(tmp_path, 'MAX_RETRIES = "3"\n') == []


def test_the_detector_sees_an_integer_account_class(tmp_path: Path) -> None:
    """Angle mort n°2 : `account_class=4` et `account__account_class=6`
    echappaient au test, qui n'inspectait que les chaines."""
    findings = _findings_for_source(
        tmp_path,
        "create(account_class=4)\nfilter(account__account_class=6)\n",
    )
    assert {value for _, value in findings} == {"account_class=4", "account__account_class=6"}


def test_the_detector_sees_an_account_class_comparison(tmp_path: Path) -> None:
    findings = _findings_for_source(tmp_path, "x = account.account_class == 2\n")
    assert findings == [(1, "account_class == 2")]


def test_management_commands_are_scanned_except_demonstration_seeds() -> None:
    """Angle mort n°3 : `management/` etait exclu, alors que
    `seed_accounting.py` y creait des comptes par leur numero.

    Les `seed_*` restent exemptes — un jeu de demonstration connait
    legitimement les codes de la fixture qu'il illustre."""
    scanned = {path.name for path in _accounting_source_files()}
    assert "load_chart_of_accounts.py" in scanned
    assert not any(name.startswith("seed_") for name in scanned)
