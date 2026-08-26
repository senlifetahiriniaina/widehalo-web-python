"""Helpers de test reutilisables pour activer un tenant (contexte applicatif
+ session Postgres), en dehors du cycle de requete HTTP normalement gere par
TenantMiddleware."""

from __future__ import annotations

from contextlib import contextmanager

from django.db import connection

from apps.core.context import clear_current_tenant, set_current_tenant


@contextmanager
def use_tenant(tenant_id):
    set_current_tenant(str(tenant_id))
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.tenant_id = %s", [str(tenant_id)])
    try:
        yield
    finally:
        clear_current_tenant()
