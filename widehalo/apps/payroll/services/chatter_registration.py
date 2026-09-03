"""Gap détecté lors de la révision complète Sprints 0-9 (cf.
docs/planning/2026-refonte-ux-sprints.md) : le chatter générique
(`apps.core.views.chatter`) n'appliquait aucune autorisation par objet au
départ, seulement le filtre tenant. Enregistre RG-PAY-9 ("un bulletin
n'est visible que par son propre employé ou par le staff RH") comme garde
chatter pour `payroll.PayPayslip`, au cas où `<c-chatter>` serait un jour
câblé sur l'écran de détail du bulletin — réutilise intégralement
`_can_view_payslip` (`apps/payroll/views.py`), jamais une réimplémentation,
même discipline que `services/reports_registration.py`/
`services/ai_context_registration.py` (auto-enregistrement depuis
`apps.py::ready()`, jamais un import direct par `apps.core`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from apps.core.services.chatter_guard_registry import register_object_guard

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.core.models.base import BaseModel


def register_chatter_guards() -> None:
    from apps.payroll.models import PayPayslip
    from apps.payroll.views import _can_view_payslip

    def _guard(request: HttpRequest, instance: BaseModel) -> bool:
        return _can_view_payslip(request, cast(PayPayslip, instance))

    register_object_guard("payroll", "paypayslip", _guard)
