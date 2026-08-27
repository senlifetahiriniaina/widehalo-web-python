"""Resolution du tenant courant pour les vues HTML par session (distinct de
`TenantMiddleware`, qui ne resout que pour l'API JWT) — meme logique que
`apps.partners.views._resolve_tenant`, partagee ici pour les modules
metier du Lot 2 (accounting/crm/mrp/patronage) afin de ne pas la dupliquer
quatre fois."""

from __future__ import annotations

from django.http import HttpRequest

from apps.core.models.tenant import Tenant


def resolve_tenant(request: HttpRequest) -> Tenant:
    tenant_id = request.headers.get("X-Tenant-Id") or request.session.get("tenant_id") or ""
    return Tenant.objects.get(id=tenant_id)
