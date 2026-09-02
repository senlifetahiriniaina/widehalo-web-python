"""Journalisation automatique de toute creation/modification/suppression
d'une entite heritant de BaseModel — connecte une fois pour toutes ici,
aucun module metier futur n'a besoin d'appeler explicitement
`log_action()` pour ce cas de base (il reste disponible pour les actions
qui ne correspondent pas a un save()/delete() : connexions, exports...).

Simplification assumee pour ce lot : la modification ("updated") ne
journalise pas de diff champ-par-champ par defaut (couteux a calculer
generiquement sans etat pre-save) — seulement le fait qu'une modification
a eu lieu. Un modele qui a besoin d'un diff precis peut poser un
attribut optionnel `_audit_diff` (dict, cf.
`apps.core.services.audit.compute_field_diff`) sur l'instance juste
avant `.save()` — lu ici de facon additive et retrocompatible
(chantier "fiche partenaire a onglets par role", PT11) : aucun
changement de comportement pour les ~250 modeles existants qui ne
posent jamais cet attribut (`changes` reste `{}` comme avant)."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save

from apps.core.models.audit import AuditLog
from apps.core.models.base import BaseModel


def _on_save(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    if not issubclass(sender, BaseModel):
        return
    from apps.core.services.audit import log_action

    log_action(
        AuditLog.ACTION_CREATED if created else AuditLog.ACTION_UPDATED,
        actor=getattr(instance, "updated_by", None) or getattr(instance, "created_by", None),
        obj=instance,
        changes=getattr(instance, "_audit_diff", None) or {},
    )


def _on_delete(sender: type, instance: Any, **kwargs: Any) -> None:
    if not issubclass(sender, BaseModel):
        return
    from apps.core.services.audit import log_action

    log_action(AuditLog.ACTION_DELETED, obj=instance)


def connect_audit_signals() -> None:
    post_save.connect(_on_save, weak=False)
    post_delete.connect(_on_delete, weak=False)
