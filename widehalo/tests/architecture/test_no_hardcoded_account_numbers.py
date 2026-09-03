"""Garde-fou bloquant : cahier des charges WideHalo v3, Phase 1, §13.3
(ACC-2) — « Un test vérifie qu'aucun numéro de compte ni structure d'état
financier n'est écrit en dur dans le code applicatif. » Ecart confirme par
l'audit (docs/audit/2026-09-cahier-des-charges-v3-audit.md, ACC-2) : ce
test n'existait pas.

**Etat reel du depot au moment de ce correctif** (a ne pas travestir) :
la resolution des comptes par defaut utilises par les automatismes
(client, vente, TVA, stock...) se fait deja proprement, via
`AccAccount.type` (`apps.accounting.services.public.
create_customer_invoice_from_source` et consorts, `AccAccount.objects.
filter(tenant=..., type=AccAccount.TYPE_RECEIVABLE/...)`) — AUCUN numero
de compte litteral dans ce chemin. Les deux seuls foyers reels de numeros
PCG 2005 codes en dur sont documentes et confines a `ACCOUNTING_FILES_
ALLOWED_TO_HARDCODE_PCG_CODES` ci-dessous ; l'abstraction complete
(table de comptes par defaut versionnee, a la maniere de
`core_regulatory_parameter`) reste un chantier plus large que cette
correction ponctuelle (cf. §11 recommandation de l'audit) — ce test ne
pretend PAS le resoudre, il EMPECHE la dispersion de nouveaux numeros
codes en dur ailleurs dans le module pendant que ce chantier plus large
n'est pas encore engage."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ACCOUNTING_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "accounting"

_PCG_ACCOUNT_CODE_PATTERN = re.compile(r"^\d{3,6}$")

# Chaque entree DOIT rester documentee dans le fichier lui-meme (pas
# seulement ici) — cf. `SUSPENSE_ACCOUNT_CODE`/table `_DEFAULT_JOURNALS` de
# `chart_of_accounts.py`, la table de classification de
# `reports.py::income_statement_by_function`, et l'exemple illustratif de
# `views_imports.py::download_chart_of_accounts_template`/
# `download_cash_journal_template` (une valeur d'EXEMPLE affichee dans un
# modele XLSX telechargeable pour guider l'utilisateur qui le remplit —
# jamais lue ni utilisee par un automatisme, contrairement aux deux autres
# entrees de ce registre).
ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES = {
    "services/chart_of_accounts.py",
    "services/reports.py",
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
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _PCG_ACCOUNT_CODE_PATTERN.match(node.value):
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

    assert not stale, "Entrée(s) obsolète(s) dans ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES : " + ", ".join(
        stale
    )
