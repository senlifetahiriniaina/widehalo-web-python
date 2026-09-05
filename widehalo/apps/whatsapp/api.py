"""API django-ninja du module `whatsapp` (gouvernance, cahier Phase 2
§13.4). Le webhook entrant (`whatsapp_webhook_verify`/`whatsapp_webhook_
receive`) reste public (verifie par jeton, pas par JWT applicatif — c'est
Meta qui l'appelle), meme discipline que `apps.core.api_notifications`,
dont le webhook EXISTANT reste inchange (backward-compat, cf. docstring
`services/inbound.py`) : celui-ci est le webhook GOUVERNE a configurer
desormais cote Meta pour beneficier de WA-6/WA-8."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from ninja import Router, Schema

from apps.core.models.tenant import Tenant
from apps.core.services.permissions import require_permission
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent, revoke_consent
from apps.whatsapp.services.inbound import handle_inbound_message
from apps.whatsapp.services.messaging import retry_failed_messages, send_governed_template_message
from apps.whatsapp.services.templates import (
    approve_template,
    create_template,
    reject_template,
    submit_for_review,
)

router = Router(tags=["whatsapp"])


class TemplateIn(Schema):
    code: str
    name: str
    category: str
    body_text: str
    language: str = "fr"
    variables: list[str] = []
    estimated_cost_ariary: Decimal = Decimal(0)


class ConsentIn(Schema):
    phone_number: str
    source: str = ""


class SendMessageIn(Schema):
    phone_number: str
    template_code: str
    variables: dict[str, Any] = {}


def _serialize_template(template: WaMessageTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "code": template.code,
        "name": template.name,
        "category": template.category,
        "status": template.status,
        "estimated_cost_ariary": str(template.estimated_cost_ariary),
    }


def _serialize_conversation(conversation: WaConversation) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "phone_number": conversation.phone_number,
        "intent_state": conversation.intent_state,
        "has_active_consent": conversation.has_active_consent(),
        "is_service_window_open": conversation.is_service_window_open(),
        "last_inbound_at": conversation.last_inbound_at,
        "last_outbound_at": conversation.last_outbound_at,
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT rester le decorateur
# EXTERNE et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`) — meme piege deja documente dans tous les autres `api.py`.
@router.get("/whatsapp/templates")
@require_permission("whatsapp.view_wamessagetemplate")
def list_templates_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    templates = WaMessageTemplate.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_template(t) for t in templates]}


@router.post("/whatsapp/templates")
@require_permission("whatsapp.add_wamessagetemplate")
def create_template_endpoint(request: Any, payload: TemplateIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        template = create_template(
            tenant,
            code=payload.code,
            name=payload.name,
            category=payload.category,
            body_text=payload.body_text,
            language=payload.language,
            variables=payload.variables,
            estimated_cost_ariary=payload.estimated_cost_ariary,
            created_by=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_template(template)


@router.post("/whatsapp/templates/{template_id}/submit")
@require_permission("whatsapp.change_wamessagetemplate")
def submit_template_endpoint(request: Any, template_id: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    template = WaMessageTemplate.objects.get(tenant=tenant, id=template_id)
    try:
        submit_for_review(template)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_template(template)


@router.post("/whatsapp/templates/{template_id}/approve")
@require_permission("whatsapp.change_wamessagetemplate")
def approve_template_endpoint(request: Any, template_id: str) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    template = WaMessageTemplate.objects.get(tenant=tenant, id=template_id)
    try:
        approve_template(template, user=request.auth)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_template(template)


class RejectIn(Schema):
    reason: str


@router.post("/whatsapp/templates/{template_id}/reject")
@require_permission("whatsapp.change_wamessagetemplate")
def reject_template_endpoint(request: Any, template_id: str, payload: RejectIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    template = WaMessageTemplate.objects.get(tenant=tenant, id=template_id)
    try:
        reject_template(template, user=request.auth, reason=payload.reason)
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_template(template)


@router.get("/whatsapp/conversations")
@require_permission("whatsapp.view_waconversation")
def list_conversations_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    conversations = WaConversation.objects.filter(tenant=tenant, is_active=True)
    return {"results": [_serialize_conversation(c) for c in conversations]}


@router.post("/whatsapp/consent/grant")
@require_permission("whatsapp.add_waconversation")
def grant_consent_endpoint(request: Any, payload: ConsentIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        conversation = grant_consent(
            tenant,
            phone_number=payload.phone_number,
            source=payload.source,
            granted_by=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return _serialize_conversation(conversation)


@router.post("/whatsapp/consent/revoke")
@require_permission("whatsapp.change_waconversation")
def revoke_consent_endpoint(request: Any, payload: ConsentIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    conversation = revoke_consent(tenant, phone_number=payload.phone_number)
    return _serialize_conversation(conversation)


@router.post("/whatsapp/send")
@require_permission("whatsapp.add_waconversation")
def send_message_endpoint(request: Any, payload: SendMessageIn) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        message = send_governed_template_message(
            tenant,
            phone_number=payload.phone_number,
            template_code=payload.template_code,
            variables=payload.variables,
            user=request.auth,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {"id": str(message.id), "status": message.status}


@router.post("/whatsapp/messages/retry")
@require_permission("whatsapp.run_message_retry")
def retry_messages_endpoint(request: Any) -> dict[str, Any]:
    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    retried = retry_failed_messages(tenant)
    return {"retried_count": len(retried)}


@router.get("/whatsapp/webhook", auth=None)
def whatsapp_webhook_verify(request: Any) -> HttpResponse:
    """Poignee de main de verification exigee par Meta — meme logique que
    `apps.core.api_notifications.whatsapp_webhook_verify`."""
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token")
    challenge = request.GET.get("hub.challenge", "")
    if mode == "subscribe" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        return HttpResponse(challenge)
    return HttpResponse(status=403)


@router.post("/whatsapp/webhook", auth=None)
def whatsapp_webhook_receive(request: Any) -> dict[str, Any]:
    """Webhook GOUVERNE (WA-6/WA-8) : journalise (reutilise `core.services.
    notifications.record_inbound_whatsapp_message`, jamais duplique) PUIS
    fait progresser la conversation/le menu d'intentions borne — cf.
    docstring de module pour la distinction avec l'ancien webhook `core`,
    laisse inchange.

    Le webhook n'est jamais atteint par `TenantMiddleware` (endpoint
    public `auth=None`, sans `X-Tenant-Id` — Meta n'en envoie pas) : le
    contexte tenant (contextvar + session Postgres pour la RLS, cf.
    `apps.core.tenant_context.activate_tenant`) n'est donc JAMAIS actif
    par defaut ici, contrairement a une requete web normale — sans
    l'activer explicitement, toute ecriture sur `WaConversation`/
    `ChatChannel` (proteges par RLS) echouerait."""
    from apps.core.services.notifications import record_inbound_whatsapp_message
    from apps.core.tenant_context import activate_tenant

    tenant = None
    tenant_id = getattr(settings, "WHATSAPP_DEFAULT_TENANT_ID", "")
    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id).first()

    body = json.loads(request.body or b"{}")
    entries = body.get("entry", [])
    processed = 0

    for entry in entries:
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                phone_number = message.get("from", "")
                text = message.get("text", {}).get("body", "")
                # L10 : le tenant est resolu quelques lignes plus haut — le
                # passer ici est ce qui rend le message entrant VISIBLE sur
                # l'ecran de conversation, qui filtre par tenant.
                record_inbound_whatsapp_message(
                    phone_number=phone_number,
                    body=text,
                    provider_message_id=message.get("id", ""),
                    tenant_id=tenant.id if tenant is not None else None,
                )
                if tenant is not None:
                    with activate_tenant(tenant.id):
                        handle_inbound_message(tenant, phone_number=phone_number, body=text)
                processed += 1

    return {"status": "ok", "processed": processed, "governed": tenant is not None}
