"""WA-5 (cahier Phase 2 §13.4) : plafond de cout mensuel PAR TENANT — meme
patron « fallback-first » que `apps.ai.services.usage_budget.check_budget`/
`get_budget_gated_provider` (AI1), applique ici au canal WhatsApp plutot
qu'aux fournisseurs IA. Les plafonds eux-memes vivent sur `core.Tenant`
(4 champs `whatsapp_*`, cf. docstring `apps.whatsapp.models`), jamais un
modele `WaUsageLimit` dedie.

**Deux plafonds, deux objets proteges** (L10). Le plafond mensuel de cout
protege la FACTURE du tenant ; la limite de frequence par destinataire
protege UNE PERSONNE. Le premier n'implique pas le second : cent messages
adresses au meme numero coutent exactement autant que cent messages
adresses a cent numeros, et c'est le premier cas qui est un harcelement.
Seule la premiere jambe existait avant L10."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


def messages_sent_to_recipient_today(tenant: Tenant, phone_number: str) -> int:
    """Nombre de messages SORTANTS deja adresses a ce numero sur les
    24 dernieres heures glissantes.

    Fenetre GLISSANTE, pas la journee civile : une journee civile se
    reinitialise a minuit, ce qui laisse une boucle emettre son quota deux
    fois a quelques minutes d'intervalle de part et d'autre de minuit —
    exactement le scenario que cette limite existe pour arreter.

    Compte les LIGNES du journal, jamais un compteur en cache. Le cache
    (`apps.core.throttling`) est le bon outil pour une limite de debit HTTP
    ou une perte de compteur ne coute qu'une requete supplementaire
    autorisee ; ici, la ligne perdue serait un message REELLEMENT parti
    vers une personne, hors de toute trace. Un plafond anti-boucle doit
    etre auditable a posteriori : `WhatsAppMessage` l'est, Redis non.

    `STATUS_PENDING` est compte comme les autres : un message en file est
    un message qui PARTIRA. L'exclure laisserait mettre en file cent
    messages d'un coup, tous conformes a la limite au moment de leur mise
    en file, et tous envoyes ensuite."""
    since = datetime.now(tz=UTC) - timedelta(days=1)
    return WhatsAppMessage.objects.filter(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        phone_number=phone_number,
        created_at__gte=since,
    ).count()


def check_recipient_rate_limit(tenant: Tenant, phone_number: str) -> bool:
    """WA-5, seconde jambe : `True` si un message supplementaire vers CE
    destinataire reste autorise.

    Distincte de `check_budget` : le plafond mensuel protege la facture du
    tenant, celui-ci protege une personne. Cent messages a un seul numero
    coutent exactement autant que cent messages a cent numeros — le premier
    ne les distingue donc pas, et c'est le premier cas qui est un
    harcelement.

    Un tenant sans limite configuree (`None`) n'est jamais bloque, meme
    discipline que `check_budget` : l'absence de configuration ne doit
    jamais bloquer l'utilisateur."""
    cap = tenant.whatsapp_max_messages_per_recipient_per_day
    if cap is None:
        return True
    return messages_sent_to_recipient_today(tenant, phone_number) < cap


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
    "check_recipient_rate_limit",
    "current_month_cost_ariary",
    "is_alert_threshold_exceeded",
    "messages_sent_to_recipient_today",
    "remaining_budget_ariary",
]
