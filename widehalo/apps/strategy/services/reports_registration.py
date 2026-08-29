"""§5.11 reporting : enregistrement des rapports `strategy` dans le registre
partage `core.services.reports_registry`, appele depuis `apps.py::ready()` —
meme patron que `apps.accounting.services.reports_registration`/
`apps.payroll.services.reports_registration`.

`STRATEGY-BP` (rapport business plan, `services/business_plan.py`) est
`render_pdf`-only (pas de `render_rows` — document composite multi-sections,
pas un tableau, cf. docstring `business_plan.py`), meme patron que
ACC-FAC/PAY-BULL."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from apps.core.context import get_current_tenant_id
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.reports_registry import register_report


def _adapter_business_plan_pdf(params: dict[str, Any], actor: User | None) -> bytes:
    del actor  # non utilise : agrege des donnees tenant, pas de scoping N3 par acteur
    from apps.strategy.services.business_plan import generate_business_plan_pdf

    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise ValueError(
            _("aucun tenant actif : STRATEGY-BP ne peut pas etre genere hors contexte tenant")
        )
    tenant = Tenant.objects.get(id=tenant_id)
    return generate_business_plan_pdf(tenant, params["period"], params.get("lang", "fr"))


def register_reports() -> None:
    register_report(
        code="STRATEGY-BP",
        module="strategy",
        label="Business plan",
        permission="strategy.view_stgobjective",
        render_pdf=_adapter_business_plan_pdf,
    )
