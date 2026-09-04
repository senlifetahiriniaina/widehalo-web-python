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

from django.contrib.auth.signals import user_logged_in, user_login_failed
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


def _on_regulatory_parameter_save(
    sender: type, instance: Any, created: bool, **kwargs: Any
) -> None:
    # RegulatoryParameter n'herite PAS de BaseModel (son `tenant` doit
    # rester nullable — nul = valeur globale, cf. sa docstring — ce que
    # BaseModel interdit) donc `_on_save` ci-dessus ne le journalise
    # jamais : cahier des charges Phase 1 §6.5 exige explicitement la
    # tracabilite de toute modification de parametre reglementaire
    # (ACC-8) — connecte separement ici plutot que forcer un heritage
    # incompatible.
    from apps.core.services.audit import log_action

    log_action(
        AuditLog.ACTION_CREATED if created else AuditLog.ACTION_UPDATED,
        actor=instance.valide_par
        if instance.statut_validation != instance.STATUS_NON_VALIDE
        else None,
        obj=instance,
        changes={
            "code": instance.code,
            "version": instance.version,
            "statut_validation": instance.statut_validation,
            "valid_from": str(instance.valid_from),
            "valid_to": str(instance.valid_to) if instance.valid_to else None,
        },
    )


def _on_regulatory_parameter_delete(sender: type, instance: Any, **kwargs: Any) -> None:
    from apps.core.services.audit import log_action

    log_action(AuditLog.ACTION_DELETED, obj=instance, changes={"code": instance.code})


def _client_ip(request: Any) -> str:
    if request is None:
        return ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _on_user_logged_in(sender: type, request: Any, user: Any, **kwargs: Any) -> None:
    # Cahier des charges Phase 1 §6.5 : "toute connexion et tout echec
    # d'authentification" doit etre journalise. Ecart confirme par l'audit
    # (docs/audit/2026-09-cahier-des-charges-v3-audit.md, §9) :
    # ACTION_LOGIN/ACTION_LOGIN_FAILED existaient comme constantes mais
    # n'avaient encore aucun point d'appel — corrige ici en un seul
    # endroit pour les DEUX flux de connexion (session `login_view` ET API
    # JWT `apps.core.services.auth.login`/`complete_mfa_login`, cf. leurs
    # commentaires respectifs sur l'envoi explicite de ce signal standard
    # Django cote JWT).
    from apps.core.services.audit import log_action

    log_action(
        AuditLog.ACTION_LOGIN,
        actor=user,
        obj=user,
        metadata={"ip": _client_ip(request)},
    )


def _on_user_login_failed(
    sender: type, credentials: dict[str, Any], request: Any = None, **kwargs: Any
) -> None:
    # `credentials` est deja assaini par Django (jamais le mot de passe en
    # clair, cf. `django.contrib.auth.authenticate`) — ne contient au plus
    # que le champ `username` (ici l'email saisi) tel que passe par
    # `authenticate(request, username=..., password=...)`.
    from apps.core.services.audit import log_action

    log_action(
        AuditLog.ACTION_LOGIN_FAILED,
        metadata={"ip": _client_ip(request), "attempted_username": credentials.get("username", "")},
    )


def connect_audit_signals() -> None:
    post_save.connect(_on_save, weak=False)
    post_delete.connect(_on_delete, weak=False)

    from apps.core.models.regulatory import RegulatoryParameter

    post_save.connect(_on_regulatory_parameter_save, sender=RegulatoryParameter, weak=False)
    post_delete.connect(_on_regulatory_parameter_delete, sender=RegulatoryParameter, weak=False)

    user_logged_in.connect(_on_user_logged_in, weak=False)
    user_login_failed.connect(_on_user_login_failed, weak=False)
