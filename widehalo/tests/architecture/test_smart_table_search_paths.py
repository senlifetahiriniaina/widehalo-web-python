"""Garde-fou bloquant (L4) : une colonne cherchable de SmartTable ne pointe
jamais sur une relation.

**Le defaut qu'elle ferme.** `_apply_search` construit un `__icontains` sur
la cle de chaque colonne `searchable`. Quand cette cle designe une
RELATION, PostgreSQL n'a rien a comparer et Django leve `FieldError:
Unsupported lookup 'icontains' for ForeignKey` — c'est-a-dire un 500 des la
premiere frappe dans la barre de recherche.

C'etait le cas de la colonne « Etape » de la liste des opportunites
(`crm.views.COLUMNS`), et d'elle seule dans tout le depot : la recherche y
etait purement et simplement inutilisable, et aucun test ne la touchait. Le
correctif est `Column.search_key` (chercher `stage__name` tout en affichant
`stage`) ; cette garde empeche la prochaine colonne d'oublier de le poser.

**Ce que la garde ne couvre pas** : elle inspecte les listes de `Column`
declarees au niveau MODULE d'un `views.py`/`views_config.py`. Une liste
construite dynamiquement dans le corps d'une vue lui echapperait. Le depot
n'en contient aucune aujourd'hui, et le test d'obsolescence ci-dessous
signalerait un module qui n'en declarerait plus.
"""

from __future__ import annotations

import importlib
import pkgutil

import apps as apps_package
from apps.core.views.smart_table import Column
from django.apps import apps as django_apps

# Modules qui declarent des colonnes — recalcule, jamais recopie.
_VIEW_MODULE_SUFFIXES = ("views", "views_config")


def _relation_field_names(app_label: str) -> dict[str, set[str]]:
    try:
        app_config = django_apps.get_app_config(app_label)
    except LookupError:
        return {}
    relations: dict[str, set[str]] = {}
    for model in app_config.get_models():
        for field in model._meta.get_fields():
            if getattr(field, "is_relation", False) and getattr(field, "name", None):
                relations.setdefault(field.name, set()).add(model.__name__)
    return relations


def _column_groups(module) -> list[tuple[str, list[Column]]]:
    groups = []
    for attribute in dir(module):
        value = getattr(module, attribute)
        if isinstance(value, list) and value and all(isinstance(c, Column) for c in value):
            groups.append((attribute, value))
    return groups


def _findings() -> list[str]:
    findings: list[str] = []
    for module_info in pkgutil.iter_modules(apps_package.__path__):
        app_label = module_info.name
        relations = _relation_field_names(app_label)
        if not relations:
            continue
        for suffix in _VIEW_MODULE_SUFFIXES:
            module_name = f"apps.{app_label}.{suffix}"
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                continue
            for attribute, columns in _column_groups(module):
                for column in columns:
                    path = column.search_key or column.key
                    if column.searchable and "__" not in path and path in relations:
                        findings.append(
                            f"{module_name}.{attribute} : colonne {column.key!r} cherchable "
                            f"sur la relation {path!r} ({', '.join(sorted(relations[path]))}) — "
                            f'poser `search_key="{path}__<champ texte>"` ou `searchable=False`'
                        )
    return findings


def test_no_searchable_column_points_at_a_relation() -> None:
    findings = _findings()
    assert not findings, (
        "Colonne(s) SmartTable dont la recherche leverait FieldError (500 a la "
        "premiere frappe) :\n" + "\n".join(f"  - {line}" for line in findings)
    )


def test_at_least_one_column_group_is_inspected() -> None:
    """Sans cette assertion, la garde passerait sur zero colonne le jour ou
    la decouverte des modules casserait — meme precaution que
    `test_ai_tools_are_read_only`, dont la docstring rappelle qu'une garde
    qui n'inspecte rien est verte par construction."""
    inspected = 0
    for module_info in pkgutil.iter_modules(apps_package.__path__):
        for suffix in _VIEW_MODULE_SUFFIXES:
            try:
                module = importlib.import_module(f"apps.{module_info.name}.{suffix}")
            except ModuleNotFoundError:
                continue
            inspected += len(_column_groups(module))
    assert inspected >= 15, f"Seulement {inspected} groupes de colonnes inspectes"


def test_the_detector_catches_a_relation_column() -> None:
    """Auto-test du detecteur — sans quoi le garde-fou serait un theatre de
    securite (`test_module_boundaries.py::test_forbidden_import_is_detected`)."""
    relations = _relation_field_names("crm")
    assert "stage" in relations, "La FK `CrmLead.stage` doit exister pour cet auto-test"

    faulty = Column(key="stage", label="Etape")
    path = faulty.search_key or faulty.key
    assert faulty.searchable and "__" not in path and path in relations

    fixed = Column(key="stage", label="Etape", search_key="stage__name")
    fixed_path = fixed.search_key or fixed.key
    assert "__" in fixed_path
