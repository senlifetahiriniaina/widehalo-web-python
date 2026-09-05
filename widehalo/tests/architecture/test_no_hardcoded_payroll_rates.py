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
d'heures supplémentaires (`"1.30"`, `"1.50"`, `"2.00"`...).

**Extension L2-4 — les montants et les bornes de tranches.** La version
initiale de ce fichier annonçait elle-même cette extension : les montants
IRSA/SME (`"300000"`, `"3000"`) et les bornes de tranches (`"350001"`,
`"4000000"`) n'utilisaient pas la forme « N,NN » et échappaient donc au
motif. Ils sont désormais couverts par un second motif (`^\\d{3,9}$` en
littéral chaîne). Le durcissement est **à coût nul** : les seules
occurrences vivent dans `services/seed.py`, déjà sur la liste d'exception
comme foyer légitime — la garde passe verte sans autre modification. C'est
le bon moment pour la poser : elle ne coûte rien aujourd'hui et interdit
demain un barème IRSA recopié dans un calcul.

**Angle mort ferme au passage** : `management/` était exclu du scan, comme
il l'était pour la garde des numéros de compte avant D10-6. Un barème écrit
dans une commande de chargement y aurait échappé. Le répertoire est
désormais scruté ; il ne contient aujourd'hui aucun littéral, l'exclusion
ne protégeait donc rien — seulement un futur oubli.

**Limite assumée** : le motif des montants ne distingue pas un barème d'un
nombre à trois chiffres qui n'en est pas un (un identifiant, un code). Le
périmètre étroit — `apps/payroll` hors migrations, tests et fixtures — rend
ce risque acceptable, et la liste d'exception documentée reste la soupape.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PAYROLL_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "payroll"

_PAYROLL_RATE_PATTERN = re.compile(r"^\d{1,2}\.\d{2}$")
# L2-4 : montants (SME, minimum IRSA) et bornes de tranches, la moitie du
# bareme que le motif des taux ne voyait pas.
_PAYROLL_AMOUNT_PATTERN = re.compile(r"^\d{3,9}$")

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

# `management` N'EST PLUS exclu (L2-4) : une commande de chargement est un
# endroit aussi plausible qu'un autre pour recopier un bareme, et l'exclure
# revenait a ne pas regarder la ou l'on ecrit precisement des donnees de
# reference. Meme correction que celle apportee a la garde ACC-2 en D10-6.
_EXCLUDED_DIR_NAMES = {"migrations", "tests", "fixtures", "__pycache__"}


def _payroll_source_files() -> list[Path]:
    files = []
    for path in PAYROLL_DIR.rglob("*.py"):
        relative_parts = path.relative_to(PAYROLL_DIR).parts
        if any(part in _EXCLUDED_DIR_NAMES for part in relative_parts):
            continue
        files.append(path)
    return files


def _hardcoded_rate_literals(path: Path) -> list[tuple[int, str]]:
    return _findings_in_source(path.read_text(encoding="utf-8"), filename=str(path))


def _findings_in_source(source: str, *, filename: str = "<source>") -> list[tuple[int, str]]:
    tree = ast.parse(source, filename=filename)
    findings: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if _PAYROLL_RATE_PATTERN.match(node.value) or _PAYROLL_AMOUNT_PATTERN.match(node.value):
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


def test_the_detector_catches_a_rate_and_a_bracket_bound() -> None:
    """Auto-test du detecteur, ajoute avec L2-4 : sans quoi le garde-fou
    serait un theatre de securite (meme discipline que
    `test_module_boundaries.py::test_forbidden_import_is_detected`).

    Les deux formes doivent etre vues : le taux, que la version initiale
    couvrait deja, et la borne de tranche, qui lui echappait."""
    source = 'CNAPS = Decimal("0.13")\nTRANCHE_IRSA = {"min": "350001", "max": "400000"}\n'
    findings = _findings_in_source(source)
    values = {value for _lineno, value in findings}
    assert "0.13" in values, findings
    assert {"350001", "400000"} <= values, findings
