"""Ecrans HTMX du module `payroll` (§5.10.11, "Envoi multicanal du
bulletin" — mise a disposition en libre-service). Meme patron que
`apps.presence.views` : session-authentifie (`@login_required`), appel
direct aux `services/*`, jamais l'API JWT interne."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

import apps.presence.services.public as presence_public
from apps.core.services.permissions import user_role_codes
from apps.core.views.tenant_web import resolve_tenant
from apps.payroll.models import PayPayslip, PayPeriod
from apps.payroll.services.pdf import payslip_pdf

_STAFF_ROLES = {"rh", "admin", "direction"}


def _can_view_payslip(request: HttpRequest, payslip: PayPayslip) -> bool:
    """RG-PAY-9 : un bulletin n'est visible que par son propre employe ou
    par le staff RH — jamais un collegue, meme dans le meme tenant."""
    if user_role_codes(request.user) & _STAFF_ROLES:  # type: ignore[arg-type]
        return True
    tenant = resolve_tenant(request)
    employee_id = presence_public.get_employee_id_for_user(tenant, request.user)  # type: ignore[arg-type]
    return employee_id is not None and payslip.employee_id == employee_id


@login_required
def my_payslips(request: HttpRequest) -> HttpResponse:
    """Libre-service : un employe authentifie voit UNIQUEMENT ses propres
    bulletins (RG-PAY-9) — jamais un montant d'un collegue."""
    tenant = resolve_tenant(request)
    employee_id = presence_public.get_employee_id_for_user(tenant, request.user)  # type: ignore[arg-type]
    payslips = (
        PayPayslip.objects.filter(tenant=tenant, employee_id=employee_id, is_active=True).order_by(
            "-date_from"
        )
        if employee_id
        else PayPayslip.objects.none()
    )
    return render(request, "payroll/my_payslips.html", {"payslips": payslips})


@login_required
def hr_dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord RH : liste des periodes de paie et leur etat — les
    montants agreges (`SENSITIVE_FIELDS`) restent masques a tout role hors
    `rh`/`direction`/`admin`/`collaborateur` (RG-PAY-9), coherent avec le
    masquage deja applique cote API."""
    tenant = resolve_tenant(request)
    role_codes = user_role_codes(request.user)  # type: ignore[arg-type]
    periods = PayPeriod.objects.filter(tenant=tenant, is_active=True).order_by("-date_from")
    return render(
        request,
        "payroll/hr_dashboard.html",
        {
            "periods": periods,
            "can_see_amounts": bool(role_codes & (_STAFF_ROLES | {"collaborateur"})),
        },
    )


@login_required
def payslip_detail(request: HttpRequest, payslip_id: str) -> HttpResponse:
    """X3 refonte UX (Sprint 8 / L5, cf.
    docs/planning/2026-refonte-ux-sprints.md §5 -- "Bulletin de paie
    Madagascar") : le calcul (IRSA/CNaPS/OSTIE) existait deja
    integralement (`services.payslip.compute_payslip`) mais aucun ecran de
    detail n'exposait le resultat ligne par ligne -- seule la liste
    (`my_payslips.html`) existait, sans le detail que ce chantier ajoute."""
    payslip = get_object_or_404(PayPayslip, id=payslip_id)
    if not _can_view_payslip(request, payslip):
        return HttpResponse(status=403)
    return render(
        request,
        "payroll/payslip_detail.html",
        {"payslip": payslip, "lines": payslip.lines.select_related("rule").all()},
    )


@login_required
def payslip_download(request: HttpRequest, payslip_id: str) -> HttpResponse:
    """Corrige un lien mort (`my_payslips.html` pointait vers lui-meme) :
    `services.pdf.payslip_pdf` existait deja, seule cette route manquait
    pour le rendre accessible."""
    payslip = get_object_or_404(PayPayslip, id=payslip_id)
    if not _can_view_payslip(request, payslip):
        return HttpResponse(status=403)
    pdf_bytes = payslip_pdf(payslip)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{payslip.reference}.pdf"'
    return response
