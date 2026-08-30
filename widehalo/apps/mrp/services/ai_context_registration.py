"""AI2 : auto-enregistrement de la guidance statique du module `mrp` dans
`core.services.ai_context_registry`, appele depuis `apps.py::ready()` —
meme patron que `reports_registration.register_reports()`/
`automation_registration.register_actions()` deja etablis dans ce module.

Demonstration optionnelle d'un `context_builder` (cf. cadrage AI2, "un ou
deux modules" a titre d'exemple) : `get_total_workshop_capacity`, deja
expose par `apps.mrp.services.public`, est une agregation triviale
(Sum SQL) donc peu couteuse a inclure dans le prompt LLM."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.core.models.tenant import Tenant
from apps.core.services.ai_context_registry import register_context
from apps.mrp.services.public import get_total_workshop_capacity

_GUIDANCE_FR = (
    "Production : ordres de fabrication, nomenclatures (BOM) et gammes "
    "operatoires, capacite des ateliers et evaluation fournisseur "
    "(qualite/cout/delai). Alimente la capacite de charge a 90 jours "
    "(module `strategy`) et le calcul de facturation a l'avancement "
    "(module `sales`)."
)
_GUIDANCE_EN = (
    "Production: manufacturing orders, bills of materials (BOM) and "
    "routings, workshop capacity and supplier evaluation (quality/cost/"
    "lead time). Feeds the 90-day workload outlook (`strategy` module) "
    "and progress-based invoicing (`sales` module)."
)


def _build_context(tenant_id: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=tenant_id)
    capacity: Decimal = get_total_workshop_capacity(tenant)
    return {"total_workshop_capacity_hours_per_day": str(capacity)}


def register_ai_context() -> None:
    register_context(
        "mrp",
        static_guidance_fr=_GUIDANCE_FR,
        static_guidance_en=_GUIDANCE_EN,
        context_builder=_build_context,
    )
