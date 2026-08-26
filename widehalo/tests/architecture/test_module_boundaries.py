"""Garde-fou bloquant : une app metier ne doit jamais importer les modeles
d'une autre app metier — uniquement `core` et les services publics
(`apps.<module>.services.public`) des autres apps.

Ne JAMAIS desactiver ou affaiblir ce test pour contourner un blocage
ponctuel (cf. CONTRIBUTING.md).
"""

from __future__ import annotations

import importlib

import pytest

from tests.architecture._ast_utils import discover_apps, extract_imports, iter_app_python_files

ALWAYS_ALLOWED = {"core"}


def _is_violation(current_app: str, imported_module: str) -> str | None:
    if not imported_module.startswith("apps."):
        return None
    parts = imported_module.split(".")
    if len(parts) < 2:
        return None
    target_app = parts[1]
    if target_app == current_app or target_app in ALWAYS_ALLOWED:
        return None
    # Autorise uniquement apps.<module>.services.public (ou un sous-attribut
    # de ce module), jamais apps.<module>.models ni tout autre sous-module.
    if len(parts) >= 4 and parts[2] == "services" and parts[3] == "public":
        return None
    return (
        f"{current_app} importe '{imported_module}' "
        "(interdit : seule surface autorisee = services.public)"
    )


def test_no_cross_app_model_imports() -> None:
    violations: list[str] = []
    for app in discover_apps():
        for file in iter_app_python_files(app):
            for record in extract_imports(file):
                violation = _is_violation(app, record.module)
                if violation:
                    violations.append(f"{record.file}: {violation}")
    assert not violations, "Violations de couplage inter-modules :\n" + "\n".join(violations)


def test_declared_dependencies_match_module_spec() -> None:
    """Verifie que chaque app declare bien, dans ModuleSpec.dependencies,
    les autres apps dont elle consomme reellement services.public."""
    for app in discover_apps():
        try:
            module_py = importlib.import_module(f"apps.{app}.module")
        except ModuleNotFoundError:
            pytest.fail(f"apps/{app}/module.py manquant (ModuleSpec obligatoire).")
            continue
        spec = module_py.MODULE
        declared = set(spec.dependencies)

        used: set[str] = set()
        for file in iter_app_python_files(app):
            for record in extract_imports(file):
                if not record.module.startswith("apps."):
                    continue
                parts = record.module.split(".")
                if len(parts) >= 4 and parts[2] == "services" and parts[3] == "public":
                    used.add(parts[1])

        undeclared = used - declared - ALWAYS_ALLOWED
        assert not undeclared, (
            f"apps/{app}/module.py : dependances utilisees mais non declarees : {undeclared}"
        )


def test_forbidden_import_is_detected() -> None:
    """Auto-test du garde-fou lui-meme : un import de modeles cross-app doit
    bien etre detecte comme violation (sans quoi le garde-fou serait un
    theatre de securite)."""
    assert _is_violation("catalog", "apps.partners.models.partner") is not None
    assert _is_violation("catalog", "apps.partners.services.public") is None
    assert _is_violation("catalog", "apps.core.models.base") is None
    assert _is_violation("catalog", "apps.catalog.models.variant") is None
