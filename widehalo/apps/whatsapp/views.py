"""Ecrans HTMX minimaux du module `whatsapp` (cahier Phase 2 §13.4) — deux
ecrans seulement (`conversations`/`config`), meme discipline budget que
`apps.strategy.views::pilotage` (un seul ecran a onglets plutot qu'un
ecran par capacite) : le plafond `tests/architecture/test_budget.py`
laissait tres peu de marge avant ce chantier (cf. docstring `models.py`)."""

from __future__ import annotations

import contextlib
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.notification import WhatsAppMessage
from apps.core.views.tenant_web import resolve_tenant
from apps.whatsapp.models import WaConversation, WaMessageTemplate
from apps.whatsapp.services.consent import grant_consent, revoke_consent
from apps.whatsapp.services.messaging import (
    queue_governed_template_message,
    retry_failed_messages,
)
from apps.whatsapp.services.templates import (
    approve_template,
    create_template,
    reject_template,
    submit_for_review,
)
from apps.whatsapp.services.usage import current_month_cost_ariary, remaining_budget_ariary


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def conversations(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm("whatsapp.view_waconversation"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    phone_number = request.GET.get("phone", "")
    context = {
        "error": request.GET.get("error", ""),
        "conversations": WaConversation.objects.filter(tenant=tenant, is_active=True),
        "templates": WaMessageTemplate.objects.filter(
            tenant=tenant, status=WaMessageTemplate.STATUS_APPROVED
        ),
        "failed_messages": WhatsAppMessage.objects.filter(
            tenant_id=tenant.id,
            direction=WhatsAppMessage.DIRECTION_OUTBOUND,
            status=WhatsAppMessage.STATUS_FAILED,
        )[:20],
        "can_manage": request.user.has_perm("whatsapp.add_waconversation"),
        "can_retry": request.user.has_perm("whatsapp.run_message_retry"),
    }
    if phone_number:
        selected = WaConversation.objects.filter(tenant=tenant, phone_number=phone_number).first()
        context["selected"] = selected
        if selected is not None:
            context["messages"] = WhatsAppMessage.objects.filter(
                tenant_id=tenant.id, phone_number=phone_number
            ).order_by("-created_at")[:50]
    return render(request, "whatsapp/conversations.html", context)


@login_required
def consent_grant(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.add_waconversation"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    phone_number = request.POST.get("phone_number", "")
    try:
        grant_consent(
            tenant,
            phone_number=phone_number,
            source=request.POST.get("source", ""),
            granted_by=request.user,
        )
    except ValidationError as exc:
        from urllib.parse import quote

        target = f"/whatsapp/?phone={quote(phone_number)}&error={quote(_error_message(exc))}"
        return redirect(target)
    return redirect(f"/whatsapp/?phone={phone_number}")


@login_required
def consent_revoke(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_waconversation"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    phone_number = request.POST.get("phone_number", "")
    revoke_consent(tenant, phone_number=phone_number)
    return redirect(f"/whatsapp/?phone={phone_number}")


@login_required
def send_message(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.add_waconversation"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    phone_number = request.POST.get("phone_number", "")
    try:
        # WA-7 (L10) : MISE EN FILE, plus envoi synchrone. Les garde-fous
        # sont appliques tout de suite — un refus reste immediat et
        # affiche — mais un canal indisponible ne fait plus perdre le
        # message : il part au prochain passage de `run_whatsapp_queue`.
        queue_governed_template_message(
            tenant,
            phone_number=phone_number,
            template_code=request.POST.get("template_code", ""),
            variables={},
            user=request.user,
        )
    except ValidationError as exc:
        from urllib.parse import quote

        target = f"/whatsapp/?phone={quote(phone_number)}&error={quote(_error_message(exc))}"
        return redirect(target)
    return redirect(f"/whatsapp/?phone={phone_number}")


@login_required
def messages_retry(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.run_message_retry"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    retry_failed_messages(tenant)
    return redirect("/whatsapp/")


@login_required
def config(request: HttpRequest) -> HttpResponse:
    """WA-10 : ecran de configuration enonçant les donnees sortantes
    (plafond de cout, bibliotheque de modeles avec leur statut) — jamais
    juste `WHATSAPP_ENABLED` comme seule gouvernance visible."""
    if not request.user.has_perm("whatsapp.view_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    can_manage = request.user.has_perm("whatsapp.change_wamessagetemplate")
    context = {
        "error": request.GET.get("error", ""),
        "can_manage": can_manage,
        "tenant": tenant,
        "current_month_cost": current_month_cost_ariary(tenant),
        "remaining_budget": remaining_budget_ariary(tenant),
        "templates": WaMessageTemplate.objects.filter(tenant=tenant, is_active=True),
    }
    return render(request, "whatsapp/config.html", context)


@login_required
def cost_cap_update(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    raw_cap = request.POST.get("monthly_cost_cap_ariary", "").strip()
    with contextlib.suppress(InvalidOperation):
        tenant.whatsapp_monthly_cost_cap_ariary = Decimal(raw_cap) if raw_cap else None
        tenant.whatsapp_cost_cap_hard_stop = bool(request.POST.get("hard_stop"))
        tenant.full_clean()
        tenant.save(
            update_fields=["whatsapp_monthly_cost_cap_ariary", "whatsapp_cost_cap_hard_stop"]
        )
    return redirect("/whatsapp/config/")


@login_required
def recipient_limit_update(request: HttpRequest) -> HttpResponse:
    """WA-5, seconde jambe : la limite de frequence par destinataire devient
    reglable depuis le produit. Sans cet ecran elle ne serait editable que
    par `/admin/` — c'est-a-dire, en pratique, jamais reglee, comme le
    regime fiscal l'etait avant L17."""
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    raw = request.POST.get("max_messages_per_recipient_per_day", "").strip()
    with contextlib.suppress(ValueError):
        tenant.whatsapp_max_messages_per_recipient_per_day = int(raw) if raw else None
        tenant.full_clean()
        tenant.save(update_fields=["whatsapp_max_messages_per_recipient_per_day"])
    return redirect("/whatsapp/config/")


@login_required
def phone_number_update(request: HttpRequest) -> HttpResponse:
    """WA-10 : rattache un numero WhatsApp Business a CETTE societe.

    `full_clean()` avant `save()` n'est pas decoratif ici : c'est lui qui
    fait remonter la contrainte d'unicite (`uniq_tenant_whatsapp_phone_
    number_id`) comme une erreur affichable plutot qu'une `IntegrityError`
    500. Deux societes qui revendiquent le meme numero, c'est un webhook
    qui choisirait en silence a laquelle livrer."""
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    tenant.whatsapp_phone_number_id = request.POST.get("whatsapp_phone_number_id", "").strip()
    try:
        tenant.full_clean()
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/whatsapp/config/?error={quote(_error_message(exc))}")
    tenant.save(update_fields=["whatsapp_phone_number_id"])
    return redirect("/whatsapp/config/")


@login_required
def template_create(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.add_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    try:
        create_template(
            tenant,
            code=request.POST.get("code", ""),
            name=request.POST.get("name", ""),
            category=request.POST.get("category", WaMessageTemplate.CATEGORY_UTILITY),
            body_text=request.POST.get("body_text", ""),
            created_by=request.user,
        )
    except ValidationError as exc:
        from urllib.parse import quote

        return redirect(f"/whatsapp/config/?error={quote(_error_message(exc))}")
    return redirect("/whatsapp/config/")


@login_required
def template_submit(request: HttpRequest, template_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    template = get_object_or_404(WaMessageTemplate, tenant=tenant, id=template_id)
    with contextlib.suppress(ValidationError):
        submit_for_review(template)
    return redirect("/whatsapp/config/")


@login_required
def template_approve(request: HttpRequest, template_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    template = get_object_or_404(WaMessageTemplate, tenant=tenant, id=template_id)
    with contextlib.suppress(ValidationError):
        approve_template(template, user=request.user)
    return redirect("/whatsapp/config/")


@login_required
def template_reject(request: HttpRequest, template_id: str) -> HttpResponse:
    if request.method != "POST" or not request.user.has_perm("whatsapp.change_wamessagetemplate"):
        return HttpResponse(status=403)
    tenant = resolve_tenant(request)
    template = get_object_or_404(WaMessageTemplate, tenant=tenant, id=template_id)
    with contextlib.suppress(ValidationError):
        reject_template(template, user=request.user, reason=request.POST.get("reason", ""))
    return redirect("/whatsapp/config/")
