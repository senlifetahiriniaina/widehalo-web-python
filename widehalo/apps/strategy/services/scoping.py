"""RBAC N3 : portee des `StgObjective` par role, au-dessus de
`core.services.scoping.apply_scope` — meme patron que
`apps.crm.services.scoping` (portee par equipe/departement).

Roles verifies contre `apps.core.services.rbac_policy.ROLE_APP_PERMISSIONS`
(11 roles CDC) : `admin`/`direction` voient/gerent tous les niveaux ;
`resp_commercial`/`resp_production`/`rh`/`acheteur` (responsables de
departement identifies, cf. plan) creent/gerent au niveau departement
SCOPE AU LEUR (departement(s) dont ils sont `manager` cote `presence`) ;
tout autre role (typiquement `collaborateur`) ne voit/modifie que ses
propres objectifs individuels (createur OU owner)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db.models import Q, QuerySet
from django.utils.translation import gettext as _

from apps.core.services.scoping import apply_scope
from apps.presence.services.public import get_department_ids_managed_by
from apps.strategy.models import StgObjective

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

UNRESTRICTED_ROLES = {"admin", "direction"}
# Responsables de departement identifies pour ce chantier (cf. plan :
# "resp_commercial/resp_production/rh/etc." — verifie contre la liste reelle
# des 11 roles CDC, `acheteur` retenu comme le candidat le plus proche d'un
# responsable achats faute d'un role dedie).
DEPARTMENT_HEAD_ROLES = {"resp_commercial", "resp_production", "rh", "acheteur"}


def _role_codes(user: User) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def scope_objectives_for_user(
    queryset: QuerySet[StgObjective], user: User, tenant: Tenant
) -> QuerySet[StgObjective]:
    role_codes = _role_codes(user)

    if role_codes & UNRESTRICTED_ROLES:
        return apply_scope(queryset, user, "global")

    if role_codes & DEPARTMENT_HEAD_ROLES:
        department_ids = get_department_ids_managed_by(tenant, user)
        return queryset.filter(
            Q(department_id__in=department_ids) | Q(owner=user) | Q(created_by=user)
        )

    # Role par defaut (`collaborateur` et tout role sans responsabilite de
    # departement) : uniquement ses propres objectifs individuels, cree par
    # lui OU dont il est `owner` (assignation par son responsable) — jamais
    # ceux d'un collegue.
    return queryset.filter(Q(owner=user) | Q(created_by=user))


def assert_can_manage_level(
    user: User, *, level: str, department_id: object, tenant: Tenant
) -> None:
    """Garde de creation/modification : verifie qu'un role a le droit de
    creer/gerer un objectif du niveau demande, AVANT tout appel a
    `services.objectives.create_objective`. Leve `PermissionDenied` (pas une
    simple restriction de queryset) — coherent avec le reste du projet, qui
    distingue "je ne peux pas VOIR" (queryset filtre) de "je ne peux pas
    AGIR" (403 explicite)."""
    role_codes = _role_codes(user)

    if role_codes & UNRESTRICTED_ROLES:
        return

    if level == StgObjective.LEVEL_COMPANY:
        raise PermissionDenied(_("Seuls direction/admin peuvent créer un objectif d'entreprise."))

    if level == StgObjective.LEVEL_DEPARTMENT:
        if not role_codes & DEPARTMENT_HEAD_ROLES:
            raise PermissionDenied(
                _("Seul un responsable de département peut créer un objectif département.")
            )
        managed_ids = set(get_department_ids_managed_by(tenant, user))
        if department_id is not None and department_id not in managed_ids:
            raise PermissionDenied(_("Vous ne gérez pas ce département."))
        return

    # LEVEL_INDIVIDUAL : tout role authentifie peut creer son propre
    # objectif individuel (le scoping de LECTURE reste la vraie barriere
    # pour les objectifs d'un tiers).
