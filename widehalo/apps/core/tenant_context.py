"""Activation explicite du contexte tenant (contextvar applicatif + session
Postgres pour la Row-Level Security) en dehors du cycle de requete HTTP
normalement gere par `TenantMiddleware` — necessaire pour les operations
administratives inter-tenant (sandbox, migrations de donnees, commandes de
management) qui doivent ecrire dans un tenant precis sans passer par une
requete web."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db import connection

from apps.core.context import clear_current_tenant, set_current_tenant


@contextmanager
def activate_tenant(tenant_id: Any) -> Iterator[None]:
    set_current_tenant(str(tenant_id))
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
    try:
        yield
    finally:
        clear_current_tenant()
