"""WA-5 (cahier Phase 2 §13.4) : plafond de cout mensuel PAR TENANT — meme
patron « fallback-first » que `apps.ai.services.usage_budget.check_budget`/
`get_budget_gated_provider` (AI1), applique ici au canal WhatsApp plutot
qu'aux fournisseurs IA. Le plafond lui-meme vit sur `core.Tenant` (3
champs `whatsapp_*`, cf. docstring `apps.whatsapp.models`), jamais un
modele `WaUsageLimit` dedie."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Sum

from apps.core.models.notification import WhatsAppMessage

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def _current_month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now


def current_month_cost_ariary(tenant: Tenant) -> Decimal:
    """Somme des `cost_ariary` des messages SORTANTS de ce mois civil pour
    ce tenant — `None` (cout non estime, cf. `WaMessageTemplate.
    estimated_cost_ariary`) compte pour 0, jamais une exception."""
    start, end = _current_month_bounds()
    total = WhatsAppMessage.objects.filter(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        created_at__gte=start,
        created_at__lte=end,
    ).aggregate(total=Sum("cost_ariary"))["total"]
    return total or Decimal(0)


def check_budget(tenant: Tenant, *, additional_cost_ariary: Decimal = Decimal(0)) -> bool:
    """`True` si un envoi supplementaire de cout `additional_cost_ariary`
    reste autorise ce mois-ci pour ce tenant. Ne fait JAMAIS d'appel
    reseau — une simple lecture/agregation locale. Un tenant SANS plafond
    configure (`whatsapp_monthly_cost_cap_ariary is None`) n'est jamais
    bloque — absence de configuration != consommation illimitee autorisee
    PAR DEFAUT dans l'absolu, mais ce module ne l'INTERDIT pas non plus tant
    qu'aucun plafond n'a ete explicitement choisi (meme discipline
    `AiUsageLimit`/AI1 : l'absence de configuration ne doit jamais bloquer
    l'utilisateur)."""
    cap = tenant.whatsapp_monthly_cost_cap_ariary
    if cap is None or not tenant.whatsapp_cost_cap_hard_stop:
        return True
    return (current_month_cost_ariary(tenant) + additional_cost_ariary) <= cap


def remaining_budget_ariary(tenant: Tenant) -> Decimal | None:
    """`None` si aucun plafond n'est configure (illimite) — jamais un
    nombre negatif silencieusement tronque a 0 : un depassement reel doit
    rester visible tel quel sur l'ecran de configuration (WA-10)."""
    cap = tenant.whatsapp_monthly_cost_cap_ariary
    if cap is None:
        return None
    return cap - current_month_cost_ariary(tenant)


def is_alert_threshold_exceeded(tenant: Tenant) -> bool:
    cap = tenant.whatsapp_monthly_cost_cap_ariary
    if cap is None or cap <= 0:
        return False
    usage_pct = (current_month_cost_ariary(tenant) / cap) * 100
    return usage_pct >= tenant.whatsapp_cost_alert_threshold_pct


__all__ = [
    "check_budget",
    "current_month_cost_ariary",
    "is_alert_threshold_exceeded",
    "remaining_budget_ariary",
]
