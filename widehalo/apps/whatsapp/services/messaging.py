"""WA-1/WA-3/WA-4/WA-5/WA-6/WA-7 (cahier Phase 2 §13.4) : point d'entrée
UNIQUE d'envoi gouverné — toute fonction future qui envoie un message
WhatsApp business-initiated doit passer par `send_governed_template_message`
ci-dessous, jamais appeler `apps.core.services.notifications.
send_whatsapp_notification`/`apps.core.services.whatsapp.get_whatsapp_client`
directement (même discipline « point d'entrée unique » que `apps.ai.
services.usage_budget.get_budget_gated_provider`, AI1).

**WA-7, et ce que « file d'attente » voulait dire jusqu'ici (L10).** Rien.
L'envoi etait SYNCHRONE : `send_governed_template_message` appelait le
client reseau dans le thread de la requete HTTP et n'ecrivait la ligne
qu'apres, statut deja resolu. `STATUS_PENDING` existait sur le modele et
n'etait l'etat d'aucun message reel. Consequence : canal indisponible =
l'utilisateur voit son envoi echouer a l'ecran, et le message n'est repris
que si quelqu'un pense a cliquer « relancer ». Le critere demande
l'inverse — « envois en file avec etat visible et REPRIS AUTOMATIQUEMENT ».

`queue_governed_template_message` ci-dessous met en file sans toucher au
reseau ; `process_outbound_queue` vide la file et relance les echecs ;
la commande `run_whatsapp_queue`, planifiee toutes les heures
(`services/scheduling_registration.py`), est le declencheur automatique
qui manquait — `apps/whatsapp/` n'avait aucun repertoire `management/`,
et le registre d'ordonnancement ne comptait aucune commande WhatsApp."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.notification import WhatsAppMessage
from apps.core.services.notifications import send_whatsapp_notification
from apps.whatsapp.models import WaMessageTemplate
from apps.whatsapp.services.consent import get_or_create_conversation, has_active_consent
from apps.whatsapp.services.templates import get_approved_template, render_body
from apps.whatsapp.services.usage import check_budget, check_recipient_rate_limit

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


def _check_governance(
    tenant: Tenant, *, phone_number: str, template_code: str
) -> WaMessageTemplate:
    """Les QUATRE garde-fous, dans l'ordre — extraits ici parce que la file
    (WA-7) doit les appliquer DEUX FOIS.

    Une fois a la mise en file : un refus doit etre immediat et visible par
    l'utilisateur qui demande l'envoi, pas decouvert une heure plus tard
    dans un journal.

    Une fois de plus a l'envoi reel : entre les deux, le destinataire a pu
    revoquer son consentement — et WA-2 exige que la revocation soit
    « effective immediatement ». Une file qui ne revalide pas transforme
    chaque message en attente en un envoi que plus rien n'autorise. Meme
    raison pour le plafond de cout (WA-5) et pour l'approbation du modele
    (WA-3), qu'un administrateur peut retirer entre-temps.

    Leve `ValidationError`, jamais un envoi silencieusement degrade."""
    template = get_approved_template(tenant, template_code)
    if template is None:
        raise ValidationError(
            _("Modèle inconnu ou non approuvé : %(code)s") % {"code": template_code}
        )
    if not has_active_consent(tenant, phone_number):
        raise ValidationError(
            _("Aucun consentement actif pour %(phone)s : envoi refusé.") % {"phone": phone_number}
        )
    if not check_recipient_rate_limit(tenant, phone_number):
        raise ValidationError(
            _(
                "Limite de fréquence atteinte pour %(phone)s : ce destinataire a déjà reçu "
                "le maximum de messages autorisé sur la période."
            )
            % {"phone": phone_number}
        )
    if not check_budget(tenant, additional_cost_ariary=template.estimated_cost_ariary):
        raise ValidationError(_("Plafond de coût WhatsApp mensuel atteint pour ce tenant."))
    return template


def send_governed_template_message(
    tenant: Tenant,
    *,
    phone_number: str,
    template_code: str,
    variables: dict[str, Any],
    user: User,
) -> WhatsAppMessage:
    """Envoi « business-initiated » IMMÉDIAT — gouverné par les quatre
    garde-fous de `_check_governance` (modèle approuvé WA-3, consentement
    actif WA-1/WA-2, fréquence par destinataire WA-5, plafond de coût
    WA-5). Un échec de garde-fou lève `ValidationError`, jamais un envoi
    silencieusement dégradé.

    Conservée à côté de `queue_governed_template_message` (WA-7) parce que
    les deux ne répondent pas au même besoin : celle-ci fait l'appel réseau
    tout de suite et rend un statut définitif, ce dont un appelant qui doit
    montrer le résultat à l'écran a besoin. La file, elle, garantit qu'un
    canal indisponible ne perd rien. **Les surfaces du produit passent par
    la file** ; cette fonction reste le transport que la file utilise."""
    template = _check_governance(tenant, phone_number=phone_number, template_code=template_code)

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


def queue_governed_template_message(
    tenant: Tenant,
    *,
    phone_number: str,
    template_code: str,
    variables: dict[str, Any],
    user: User,
) -> WhatsAppMessage:
    """WA-7 : met un envoi EN FILE, sans aucun appel reseau.

    Les garde-fous sont appliques ICI, tout de suite : un envoi refuse doit
    l'etre sous les yeux de celui qui le demande, pas une heure plus tard
    dans un journal que personne ne lit. Ils seront reappliques a l'envoi
    reel (cf. `_check_governance`), parce qu'un consentement peut etre
    revoque entre les deux.

    La ligne est ecrite en `STATUS_PENDING` — le premier usage reel de cet
    etat, qui existait sur le modele sans que rien ne l'emette. C'est lui
    qui rend l'etat « visible » que le critere exige : un message en file
    apparait sur l'ecran des conversations comme en attente, pas comme
    disparu.

    La `Notification` applicative est creee des maintenant plutot qu'a
    l'envoi : c'est ici qu'on dispose de l'utilisateur demandeur, et
    `WhatsAppMessage` ne porte aucune reference vers lui. La differer
    obligerait a stocker un utilisateur sur la ligne de file pour le seul
    besoin de la retrouver."""
    from apps.core.models.notification import Notification
    from apps.core.services.notifications import dispatch_notification

    template = _check_governance(tenant, phone_number=phone_number, template_code=template_code)
    conversation = get_or_create_conversation(tenant, phone_number)

    notification = dispatch_notification(
        user,
        f"whatsapp.{template.code}",
        {"body": [{"type": "text", "text": str(v)} for v in variables.values()]},
        tenant_id=str(tenant.id),
        channel=Notification.CHANNEL_WHATSAPP,
    )
    return WhatsAppMessage.objects.create(
        tenant_id=tenant.id,
        notification=notification,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        phone_number=phone_number,
        template_name=template.code,
        status=WhatsAppMessage.STATUS_PENDING,
        conversation_id=conversation.id,
        category=template.category,
        variables=variables,
        cost_ariary=template.estimated_cost_ariary,
        body=render_body(template, variables),
    )


def flush_pending_messages(tenant: Tenant) -> list[WhatsAppMessage]:
    """WA-7 : envoie les messages en file de ce tenant.

    Revalide les garde-fous message par message. Un message dont le
    destinataire a revoque son consentement depuis la mise en file n'est
    PAS envoye et passe en `failed` avec le motif dans `error_message`
    — jamais supprime en silence : « refuse parce que le consentement a ete
    retire » et « jamais parti, on ne sait pas pourquoi » sont deux etats
    qu'un exploitant doit pouvoir distinguer.

    Un refus de garde-fou n'est pas une panne reseau : le message n'entre
    pas dans le cycle de reprise (`next_retry_at` reste nul, `retry_count`
    n'est pas incremente). Le represente automatiquement reviendrait a
    reessayer indefiniment un envoi que la gouvernance interdit."""
    from apps.core.services.whatsapp import get_whatsapp_client

    pending = WhatsAppMessage.objects.filter(
        tenant_id=tenant.id,
        direction=WhatsAppMessage.DIRECTION_OUTBOUND,
        status=WhatsAppMessage.STATUS_PENDING,
    ).order_by("created_at")

    client = get_whatsapp_client()
    now = timezone.now()
    sent: list[WhatsAppMessage] = []
    for message in pending:
        try:
            _check_governance(
                tenant,
                phone_number=message.phone_number,
                template_code=message.template_name,
            )
        except ValidationError as exc:
            message.status = WhatsAppMessage.STATUS_FAILED
            message.error_message = "; ".join(exc.messages)
            message.save(update_fields=["status", "error_message"])
            continue

        result = client.send_template(
            message.phone_number,
            message.template_name,
            {"body": [{"type": "text", "text": str(v)} for v in message.variables.values()]},
        )
        if result.status == "sent":
            message.status = WhatsAppMessage.STATUS_SENT
            message.provider_message_id = result.provider_message_id
            sent.append(message)
        else:
            message.status = WhatsAppMessage.STATUS_FAILED
            message.next_retry_at = now + _RETRY_BACKOFF[0]
        message.save(update_fields=["status", "provider_message_id", "next_retry_at"])

        if message.status == WhatsAppMessage.STATUS_SENT:
            conversation = get_or_create_conversation(tenant, message.phone_number)
            conversation.last_outbound_at = now
            conversation.save(update_fields=["last_outbound_at", "updated_at"])
    return sent


def process_outbound_queue(tenant: Tenant) -> dict[str, int]:
    """WA-7 : le tour complet — vider la file, puis relancer les echecs.

    Dans cet ordre : un message jamais parti attend depuis plus longtemps
    qu'un message dont la premiere tentative vient d'echouer, et le
    backoff de la reprise suppose qu'une premiere tentative a eu lieu.

    Point d'appel unique de la commande periodique `run_whatsapp_queue`."""
    sent = flush_pending_messages(tenant)
    retried = retry_failed_messages(tenant)
    return {"sent": len(sent), "retried": len(retried)}


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


__all__ = [
    "MAX_RETRY_ATTEMPTS",
    "flush_pending_messages",
    "process_outbound_queue",
    "queue_governed_template_message",
    "retry_failed_messages",
    "send_governed_template_message",
]
