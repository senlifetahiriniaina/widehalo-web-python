"""Gap détecté lors de la révision complète Sprints 0-9 (cf.
docs/planning/2026-refonte-ux-sprints.md) : le chatter générique
(`apps.core.views.chatter`) n'appliquait aucune autorisation par objet au
départ, seulement le filtre tenant. Enregistre une garde chatter pour
`payroll.PayPayslip`, au cas où `<c-chatter>` serait un jour câblé sur un
écran de bulletin — réservée au staff RH (`rh`/`admin`/`direction`) depuis
le cahier des charges Phase 3 (§6.1, décision D1) : il n'existe plus de
notion d'« employé propriétaire » habilité à consulter son propre bulletin
en self-service (`apps/payroll/views.py::_can_view_payslip`, qui portait
cette règle, a été retiré avec le portail salarié), même discipline que
`services/reports_registration.py`/`services/ai_context_registration.py`
(auto-enregistrement depuis `apps.py::ready()`, jamais un import direct
par `apps.core`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from apps.core.services.chatter_guard_registry import register_object_guard

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.core.models.base import BaseModel

_STAFF_ROLES = {"rh", "admin", "direction"}


def register_chatter_guards() -> None:
    from apps.core.services.permissions import user_role_codes
    from apps.payroll.models import PayPayslip

    def _guard(request: HttpRequest, instance: BaseModel) -> bool:
        cast(PayPayslip, instance)
        return bool(user_role_codes(request.user) & _STAFF_ROLES)  # type: ignore[arg-type]

    register_object_guard("payroll", "paypayslip", _guard)
