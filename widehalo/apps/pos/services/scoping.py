"""Scope N3 : « sa session » (cahier §3, persona Caissier — docs/RBAC.md
§2/§5). Un `caissier` n'agit que sur SA PROPRE session de caisse ; `admin`/
`direction` (pilotage transverse, même discipline que le reste du dépôt —
cf. `crm.services.scoping`/`strategy.services.scoping`) et un superutilisateur
voient/gèrent tout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.core.services.permissions import user_role_codes

if TYPE_CHECKING:
    from apps.core.models.user import User
    from apps.pos.models import PosSession

_TRANSVERSE_ROLES = {"admin", "direction"}


def assert_can_manage_session(session: PosSession, user: User) -> None:
    """Lève `PermissionDenied` (convertie en 403 par
    `apps.core.errors.register_exception_handlers` côté API ninja, et par
    le gestionnaire d'erreurs standard de Django côté écrans HTMX — aucune
    conversion manuelle nécessaire dans les deux cas) si `user` n'est ni
    le titulaire de la session, ni admin/direction, ni superutilisateur."""
    if getattr(user, "is_superuser", False):
        return
    if session.cashier_id == getattr(user, "id", None):
        return
    if user_role_codes(user) & _TRANSVERSE_ROLES:
        return
    raise PermissionDenied(_("Vous ne pouvez gérer que votre propre session de caisse."))
