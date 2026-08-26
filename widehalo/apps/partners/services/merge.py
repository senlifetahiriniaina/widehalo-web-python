from __future__ import annotations

from typing import Any

from apps.partners.models import Partner


def merge_partners(*, primary: Partner, duplicate: Partner) -> int:
    """Fusionne `duplicate` dans `primary` : reassigne generiquement, PAR
    INTROSPECTION du graphe de FK Django (`Partner._meta.related_objects`),
    toute reference pointant vers `duplicate` — y compris depuis de futurs
    modules metier qui referenceront `Partner` (ventes, achats...), sans que
    ce code ait besoin d'etre mis a jour a chaque nouveau module. Chaque
    reassignation passe par `save()` individuel (jamais `update()` en masse)
    pour que le signal d'audit transversal (etape 10) journalise chaque
    changement. `duplicate` est ensuite marque `merged_into` et soft-supprime
    (jamais de suppression physique — trace conservee pour l'audit)."""
    reassigned = 0

    # `include_hidden=True` est indispensable : les FK avec `related_name="+"`
    # (dont `DuplicateAlert.partner`/`duplicate_of`) sont exclues de la liste
    # par defaut (`Partner._meta.related_objects`), alors qu'elles doivent
    # elles aussi etre reassignees lors d'une fusion.
    for field in Partner._meta.get_fields(include_hidden=True):
        rel: Any = field
        if not (getattr(rel, "auto_created", False) and not rel.concrete):
            continue
        if rel.many_to_many:
            continue
        related_model = rel.related_model
        fk_name = rel.field.name

        for obj in related_model._default_manager.filter(**{fk_name: duplicate}):
            setattr(obj, fk_name, primary)
            obj.save()
            reassigned += 1

    duplicate.merged_into = primary
    duplicate.save(update_fields=["merged_into"])
    duplicate.soft_delete()

    return reassigned
