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

_EXCLUDED_DIR_NAMES = {"migrations", "tests", "fixtures", "management", "__pycache__"}


def _accounting_source_files() -> list[Path]:
    files = []
    for path in ACCOUNTING_DIR.rglob("*.py"):
        relative_parts = path.relative_to(ACCOUNTING_DIR).parts
        if any(part in _EXCLUDED_DIR_NAMES for part in relative_parts):
            continue
        files.append(path)
    return files


def _hardcoded_pcg_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _PCG_ACCOUNT_CODE_PATTERN.match(node.value)
        ):
            findings.append((node.lineno, node.value))
    return findings


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
