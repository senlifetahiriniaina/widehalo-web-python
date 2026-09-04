"""Garde-fou bloquant : Bloc E, E2 (plan Phase 3, §Bloc E — « Garde CI
paie (pas de barème en dur) ») — miroir structurel de
`test_no_hardcoded_account_numbers.py` (ACC-2), applique aux barèmes de
paie plutôt qu'aux numéros de compte PCG.

**Motivation directe** : E1 vient de retirer `apps.payroll.services.expr.
DEFAULT_OVERTIME_MULTIPLIERS` (un dict de multiplicateurs codé en dur),
remplacé par le `RegulatoryParameter` versionné `payroll.
overtime_multipliers`, même patron que les 9 autres barèmes/taux du
module (IRSA, CNaPS, OSTIE, FMFP, SME...). Ce test empêche la régression
de cette classe précise de bug : un taux/multiplicateur qui réapparaît en
dur ailleurs dans `apps.payroll`, contournant silencieusement le verrou
de validation OECFM (ACC-9, `apps.core.services.regulatory_governance`)
qui ne porte QUE sur les valeurs réellement stockées en base.

**Forme du motif, DÉLIBÉRÉMENT différente de `_PCG_ACCOUNT_CODE_PATTERN`**
(un numéro de compte n'a pas de sens en paie) : tous les taux/
multiplicateurs actuellement seedés par `apps.payroll.services.seed`
partagent la même forme littérale « N,NN » à deux décimales — les taux
CNaPS/OSTIE/FMFP (`"0.13"`, `"0.01"`, `"0.05"`...) et les multiplicateurs
d'heures supplémentaires (`"1.30"`, `"1.50"`, `"2.00"`...). Les montants
IRSA/SME (`"300000"`, `"3000"`...) et les bornes de tranches IRSA
n'utilisent PAS cette forme et ne sont donc pas ciblés ici — un futur
sprint qui constaterait un autre foyer de littéraux en dur pourra étendre
ce motif, pas seulement l'allowlist."""

from __future__ import annotations

import ast
import re
from pathlib import Path

PAYROLL_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "payroll"

_PAYROLL_RATE_PATTERN = re.compile(r"^\d{1,2}\.\d{2}$")

# Chaque entree DOIT rester documentee dans le fichier lui-meme (meme
# discipline que ACCOUNTING_FILES_ALLOWED_TO_HARDCODE_PCG_CODES) :
# - "services/seed.py" : la table de reference elle-meme
#   (`seed_payroll_regulatory_params`) — foyer LEGITIME et UNIQUE de ces
#   valeurs, jamais lue directement par un calcul (cf. `apps.payroll.
#   services.params.resolve_params`, qui passe TOUJOURS par
#   `RegulatoryParameter`).
# - "services/projection.py" : `project_payroll_mass.employer_charge_rate`
#   par defaut a `Decimal("0.18")` — approximation ASSUMEE et DEJA
#   disclosee dans la docstring de la fonction (« calculateur simple »,
#   §5.10.11 : CNaPS+OSTIE = 13%+5% approxime SANS re-derouler le moteur
#   de regles complet ni le plafonnement 8xSME) — une vraie resolution
#   via `resolve_params` a une date precise reste hors perimetre de ce
#   calculateur volontairement simplifie.
PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES = {
    "services/seed.py",
    "services/projection.py",
}

_EXCLUDED_DIR_NAMES = {"migrations", "tests", "fixtures", "management", "__pycache__"}


def _payroll_source_files() -> list[Path]:
    files = []
    for path in PAYROLL_DIR.rglob("*.py"):
        relative_parts = path.relative_to(PAYROLL_DIR).parts
        if any(part in _EXCLUDED_DIR_NAMES for part in relative_parts):
            continue
        files.append(path)
    return files


def _hardcoded_rate_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _PAYROLL_RATE_PATTERN.match(node.value)
        ):
            findings.append((node.lineno, node.value))
    return findings


def test_no_hardcoded_payroll_rate_outside_the_documented_allowlist() -> None:
    violations: list[str] = []

    for path in _payroll_source_files():
        relative = str(path.relative_to(PAYROLL_DIR))
        findings = _hardcoded_rate_literals(path)
        if not findings:
            continue
        if relative in PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES:
            continue
        for lineno, value in findings:
            violations.append(f"{relative}:{lineno} -> {value!r}")

    assert not violations, (
        "Taux/multiplicateur de paie codé en dur hors de "
        "PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES (Bloc E, E2) — utiliser un "
        "RegulatoryParameter versionné (apps.payroll.services.seed) à la place :\n"
        + "\n".join(sorted(violations))
    )


def test_allowlisted_files_still_exist_and_still_need_the_exemption() -> None:
    # Registre a jour : un fichier qui ne contient plus AUCUN taux en dur
    # (refactor vers `RegulatoryParameter`) doit sortir de l'allowlist, pas
    # y rester comme une exemption fantome qui masquerait un futur oubli
    # sur le meme nom de fichier.
    stale = []
    for relative in PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES:
        path = PAYROLL_DIR / relative
        if not path.exists():
            stale.append(f"{relative} (fichier introuvable)")
            continue
        if not _hardcoded_rate_literals(path):
            stale.append(f"{relative} (ne contient plus aucun taux en dur)")

    assert not stale, (
        "Entrée(s) obsolète(s) dans PAYROLL_FILES_ALLOWED_TO_HARDCODE_RATES : " + ", ".join(stale)
    )
