"""WA-1/WA-3/WA-4/WA-5/WA-6/WA-7 (cahier Phase 2 §13.4) : point d'entrée
UNIQUE d'envoi gouverné — toute fonction future qui envoie un message
WhatsApp business-initiated doit passer par `send_governed_template_message`
ci-dessous, jamais appeler `apps.core.services.notifications.
send_whatsapp_notification`/`apps.core.services.whatsapp.get_whatsapp_client`
directement (même discipline « point d'entrée unique » que `apps.ai.
services.usage_budget.get_budget_gated_provider`, AI1)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.notification import WhatsAppMessage
from apps.core.services.notifications import send_whatsapp_notification
from apps.whatsapp.services.consent import get_or_create_conversation, has_active_consent
from apps.whatsapp.services.templates import get_approved_template, render_body
from apps.whatsapp.services.usage import check_budget

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

# WA-7 : nombre maximal de tentatives avant qu'un message en echec ne soit
# plus jamais represente automatiquement (reste visible en base, `status=
# failed`, mais `retry_failed_messages` l'ignore desormais) — decision de
# conception PRISE ICI (non specifiee au cadrage, disclosed), coherente
# avec la pratique usuelle "3 tentatives" plutot qu'une boucle infinie.
MAX_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = [timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2)]


def send_governed_template_message(
    tenant: Tenant,
    *,
    phone_number: str,
    template_code: str,
    variables: dict[str, Any],
    user: User,
) -> WhatsAppMessage:
    """Envoi « business-initiated » (campagne, relance...) — TOUJOURS
    gouverné par les 3 garde-fous du cahier, dans cet ordre : modèle
    approuvé (WA-3), consentement actif (WA-1/WA-2), plafond de coût non
    dépassé (WA-5). Un échec de garde-fou lève `ValidationError`, jamais un
    envoi silencieusement dégradé."""
    template = get_approved_template(tenant, template_code)
    if template is None:
        raise ValidationError(
            _("Modèle inconnu ou non approuvé : %(code)s") % {"code": template_code}
        )
    if not has_active_consent(tenant, phone_number):
        raise ValidationError(
            _("Aucun consentement actif pour %(phone)s : envoi refusé.") % {"phone": phone_number}
        )
    if not check_budget(tenant, additional_cost_ariary=template.estimated_cost_ariary):
        raise ValidationError(_("Plafond de coût WhatsApp mensuel atteint pour ce tenant."))

    conversation = get_or_create_conversation(tenant, phone_number)
    message = send_whatsapp_notification(
        user,
        phone_number,
        template.code,
        {"body": [{"type": "text", "text": str(v)} for v in variables.values()]},
        tenant_id=str(tenant.id),
    )
    message.conversation_id = conversation.id
    message.category = template.category
    message.variables = variables
    message.cost_ariary = template.estimated_cost_ariary
    message.body = render_body(template, variables)
    message.save(update_fields=["conversation_id", "category", "variables", "cost_ariary", "body"])

    conversation.last_outbound_at = timezone.now()
    conversation.save(update_fields=["last_outbound_at", "updated_at"])
    return message


def retry_failed_messages(tenant: Tenant) -> list[WhatsAppMessage]:
    """WA-7 : « reprise dédiée au canal WhatsApp » — relance les messages
    SORTANTS en échec de ce tenant, sous `MAX_RETRY_ATTEMPTS`, en
    respectant un délai croissant entre tentatives (`next_retry_at`,
    jamais une re-tentative immédiate en boucle). Retourne les messages
    dont la relance a RÉUSSI (statut passé à `sent`) — un message toujours
    en échec après relance reste `status=failed`, visible tel quel."""
    from apps.core.services.whatsapp import get_whatsapp_client

    now = timezone.now()
    candidates = WhatsAppMessage.objects.filter(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        status=WhatsAppMessage.STATUS_FAILED,
        retry_count__lt=MAX_RETRY_ATTEMPTS,
    ).exclude(next_retry_at__gt=now)

    client = get_whatsapp_client()
    retried: list[WhatsAppMessage] = []
    for message in candidates:
        result = client.send_template(message.phone_number, message.template_name, {"body": []})
        message.retry_count += 1
        if result.status == "sent":
            message.status = WhatsAppMessage.STATUS_SENT
            message.provider_message_id = result.provider_message_id
            message.next_retry_at = None
            retried.append(message)
        else:
            backoff = _RETRY_BACKOFF[min(message.retry_count - 1, len(_RETRY_BACKOFF) - 1)]
            message.next_retry_at = now + backoff
        message.save(
            update_fields=["retry_count", "status", "provider_message_id", "next_retry_at"]
        )
    return retried


__all__ = ["MAX_RETRY_ATTEMPTS", "retry_failed_messages", "send_governed_template_message"]
