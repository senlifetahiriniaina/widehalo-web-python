"""Helpers de test reutilisables pour activer un tenant (contexte applicatif
+ session Postgres), en dehors du cycle de requete HTTP normalement gere par
TenantMiddleware. Alias de `apps.core.tenant_context.activate_tenant` — les
tests l'utilisent sous le nom historique `use_tenant`."""

from apps.core.tenant_context import activate_tenant as use_tenant

__all__ = ["use_tenant"]
