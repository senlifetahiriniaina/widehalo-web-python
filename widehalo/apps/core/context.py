"""Contexte du tenant courant, accessible depuis les managers d'ORM sans
avoir a se propager la requete HTTP explicitement (TenantManager en a
besoin, cf. apps/core/models/base.py, etape 3)."""

from __future__ import annotations

from contextvars import ContextVar

_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)


def set_current_tenant(tenant_id: str | None) -> None:
    _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> str | None:
    return _current_tenant_id.get()


def clear_current_tenant() -> None:
    _current_tenant_id.set(None)
