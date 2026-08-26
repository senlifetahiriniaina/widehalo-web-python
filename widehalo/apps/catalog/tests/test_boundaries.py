from __future__ import annotations

from tests.architecture._ast_utils import discover_apps, extract_imports, iter_app_python_files


def test_catalog_never_imports_partners_models() -> None:
    """Verification specifique demandee par le cahier des charges : le
    garde-fou generique (test_module_boundaries.py) couvre deja ce cas,
    mais on le reaffirme explicitement ici pour ce couple d'apps precis."""
    assert "catalog" in discover_apps()
    for file in iter_app_python_files("catalog"):
        for record in extract_imports(file):
            assert not record.module.startswith("apps.partners.models"), (
                f"{record.file} importe {record.module} — interdit, "
                "catalog ne doit connaitre partners que par UUID + services.public"
            )
