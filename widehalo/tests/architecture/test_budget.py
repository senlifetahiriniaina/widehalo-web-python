"""Garde-fou bloquant : plafonds fonctionnels V1 imposes par le cahier des
charges (180 modeles, 600 endpoints, 90 ecrans) pour eviter de reconstruire,
module apres module, le systeme volumineux que l'on cherche a alleger.

Ne JAMAIS relever ces plafonds sans une decision explicite du commanditaire.
"""

from __future__ import annotations

from pathlib import Path

from django.apps import apps
from django.conf import settings

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _counted_models() -> list[str]:
    """Modeles reellement livres (exclut les modeles de test dedies aux
    tests d'architecture/isolation, jamais exposes en API ni en ecran)."""
    widehalo_app_labels = {
        a.split(".")[-1] for a in settings.INSTALLED_APPS if a.startswith("apps.")
    }
    names = []
    for model in apps.get_models():
        if ".tests." in model.__module__:
            continue
        if model._meta.app_label not in widehalo_app_labels:
            continue
        names.append(f"{model._meta.app_label}.{model.__name__}")
    return names


def _counted_endpoints() -> int:
    """Compte les endpoints reellement enregistres sur l'API django-ninja
    (une PathView par chemin, potentiellement plusieurs operations/verbes)."""
    from config.api import api

    count = 0
    for _prefix, router in api._routers:
        for path_view in router.path_operations.values():
            count += len(path_view.operations)
    return count


def _counted_screens() -> int:
    if not TEMPLATES_DIR.exists():
        return 0
    return sum(
        1
        for path in TEMPLATES_DIR.rglob("*.html")
        if not path.name.startswith("_")
        and "components" not in path.parts
        and "layout" not in path.parts
    )


def test_model_budget_not_exceeded() -> None:
    models = _counted_models()
    assert len(models) <= settings.BUDGET_MAX_MODELS, (
        f"Plafond de modeles depasse : {len(models)}/{settings.BUDGET_MAX_MODELS}. "
        f"Modeles : {models}"
    )


def test_endpoint_budget_not_exceeded() -> None:
    count = _counted_endpoints()
    assert count <= settings.BUDGET_MAX_ENDPOINTS, (
        f"Plafond d'endpoints depasse : {count}/{settings.BUDGET_MAX_ENDPOINTS}"
    )


def test_screen_budget_not_exceeded() -> None:
    count = _counted_screens()
    assert count <= settings.BUDGET_MAX_SCREENS, (
        f"Plafond d'ecrans depasse : {count}/{settings.BUDGET_MAX_SCREENS}"
    )
