"""Contexte du tenant courant, accessible depuis les managers d'ORM sans
avoir a se propager la requete HTTP explicitement (TenantManager en a
besoin, cf. apps/core/models/base.py, etape 3)."""

from __future__ import annotations

from contextvars import ContextVar, Token

_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)


def set_current_tenant(tenant_id: str | None) -> Token[str | None]:
    """Active une societe et REND LE JETON qui permet de revenir en
    arriere.

    Le jeton n'est pas decoratif : c'est la seule facon de retablir la
    valeur PRECEDENTE plutot que de remettre a zero. `activate_tenant`
    s'en sert, et le motif est ecrit la-bas — un imbriquement qui remet a
    zero laisse l'appelant sans societe, ou `TenantManager` ne renvoie
    plus rien du tout, en silence."""
    return _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> str | None:
    return _current_tenant_id.get()


def reset_current_tenant(token: Token[str | None]) -> None:
    """Retablit la valeur qui precedait le `set_current_tenant` du jeton."""
    _current_tenant_id.reset(token)


def clear_current_tenant() -> None:
    """Sort de toute societe. A n'employer que quand il n'y a rien a
    retablir — la fin d'une requete HTTP, par exemple. Au milieu d'un
    traitement, c'est `reset_current_tenant` qu'il faut."""
    _current_tenant_id.set(None)
