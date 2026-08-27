"""Helpers de test reutilisables pour activer un tenant (contexte applicatif
+ session Postgres), en dehors du cycle de requete HTTP normalement gere par
TenantMiddleware. Alias de `apps.core.tenant_context.activate_tenant` — les
tests l'utilisent sous le nom historique `use_tenant`."""

from django.contrib.auth.models import Group

from apps.core.models.user import User
from apps.core.services.rbac_policy import sync_group_permissions
from apps.core.tenant_context import activate_tenant as use_tenant

__all__ = ["grant_role", "use_tenant"]


def grant_role(user: User, role_code: str) -> Group:
    """Attribue a `user` le role `role_code` (ex. "comptable") avec les
    permissions Django reellement synchronisees selon
    `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS` — a utiliser dans
    tout test qui appelle un endpoint API protege par `require_permission()`,
    plutot que de recreer un Group/Permission ad hoc par test."""
    group, _ = Group.objects.get_or_create(name=role_code)
    sync_group_permissions(group, role_code)
    user.groups.add(group)
    return group
