"""Scope N3 : « ses scénarios » (cahier §13.6 : « personnels ou partagés »
— docs/RBAC.md §5.5bis). Un scénario NON partagé (`is_shared=False`) n'est
visible/modifiable que par son `owner` ; un scénario PARTAGÉ est visible
par tout utilisateur autorisé du tenant mais reste modifiable/archivable
uniquement par son `owner` ou par un rôle transverse (`admin`/`direction`,
même discipline que `apps.pos.services.scoping`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.services.permissions import user_role_codes

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.core.models.user import User
    from apps.simulation.models import SimScenario

_TRANSVERSE_ROLES = {"admin", "direction"}


def visible_scenarios(queryset: QuerySet[SimScenario], user: User) -> QuerySet[SimScenario]:
    """SIM-9 : « un utilisateur ne peut simuler que sur le périmètre de
    données que son rôle l'autorise à consulter » — appliqué ici au niveau
    N3 (quels SCÉNARIOS, une fois l'accès au module lui-même déjà accordé
    en N2 par `require_permission`) : ses propres scénarios + les
    scénarios partagés du tenant. `admin`/`direction` voient tout, même
    discipline transverse que le reste du dépôt."""
    if getattr(user, "is_superuser", False) or user_role_codes(user) & _TRANSVERSE_ROLES:
        return queryset
    return queryset.filter(Q(owner_id=getattr(user, "id", None)) | Q(is_shared=True))


def assert_can_view_scenario(scenario: SimScenario, user: User) -> None:
    """Même règle que `visible_scenarios` mais pour un accès direct par
    identifiant (`GET /simulation/scenarios/{id}`) — un scénario non
    partagé d'un autre utilisateur reste invisible même en connaissant son
    UUID (SIM-9)."""
    if getattr(user, "is_superuser", False) or user_role_codes(user) & _TRANSVERSE_ROLES:
        return
    if scenario.owner_id == getattr(user, "id", None) or scenario.is_shared:
        return
    raise PermissionDenied(_("Vous n'avez pas accès à ce scénario."))


def assert_can_manage_scenario(scenario: SimScenario, user: User) -> None:
    """Lève `PermissionDenied` si `user` n'est ni le propriétaire du
    scénario, ni admin/direction, ni superutilisateur — un scénario
    PARTAGÉ reste en lecture seule pour tout autre utilisateur que son
    propriétaire (cf. docstring de tête)."""
    if getattr(user, "is_superuser", False):
        return
    if scenario.owner_id == getattr(user, "id", None):
        return
    if user_role_codes(user) & _TRANSVERSE_ROLES:
        return
    raise PermissionDenied(_("Vous ne pouvez gérer que vos propres scénarios."))
