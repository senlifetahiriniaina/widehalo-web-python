"""Ecrans HTMX du module `presence` (§5.9.5) : kiosque de pointage plein
ecran, calendrier d'equipe, demande d'absence (3 champs), tableau de bord
RH. Meme patron que `apps.logistics.views` : session-authentifie
(`@login_required`), appel direct aux `services/*` de `presence`, jamais
l'API JWT interne.

**"Mes validations en attente"** (§5.9.5) n'a PAS de nouvel ecran ici :
c'est l'ecran generique transversal deja construit au Lot 1 (etape 8,
`core.views` — content-type generique), verifie sans modification
necessaire pour les `ApprovalRequest` d'absence (meme discipline que le
chantier RG-QUALIF, cf. plan)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from apps.core.views.tenant_web import resolve_tenant
from apps.presence.models import PrsAbsence, PrsAbsenceType, PrsAttendance, PrsEmployee
from apps.presence.services.absences import create_absence, submit_absence
from apps.presence.services.attendance import check_in


@login_required
def kiosk(request: HttpRequest) -> HttpResponse:
    """Kiosque de pointage plein ecran (RG-PRS-1, mode "kiosque") — un
    employe s'identifie par son matricule (`reference`), pas de saisie de
    mot de passe (poste partage)."""
    message = ""
    if request.method == "POST":
        reference = request.POST.get("reference", "").strip()
        tenant = resolve_tenant(request)
        employee = PrsEmployee.objects.filter(
            tenant=tenant, reference=reference, is_active=True
        ).first()
        if employee is None:
            message = "employee_not_found"
        else:
            try:
                check_in(employee, mode=PrsAttendance.MODE_KIOSK)
                message = "checked_in"
            except ValidationError as exc:
                message = "; ".join(exc.messages)
    return render(request, "presence/kiosk.html", {"message": message})


@login_required
def team_calendar(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    date_param = request.GET.get("date", "")
    date = parse_date(date_param) or dt.date.today()

    absences = PrsAbsence.objects.filter(
        tenant=tenant,
        is_active=True,
        date_from__lte=date,
        date_to__gte=date,
        state__in=[PrsAbsence.STATE_VALIDATED, PrsAbsence.STATE_IN_PROGRESS],
    ).select_related("employee", "type")
    attendances = PrsAttendance.objects.filter(
        tenant=tenant, is_active=True, date=date
    ).select_related("employee")

    return render(
        request,
        "presence/team_calendar.html",
        {"date": date, "absences": absences, "attendances": attendances},
    )


@login_required
def absence_request(request: HttpRequest) -> HttpResponse:
    """Demande d'absence "en trois champs" (§5.9.5) : type, date de debut,
    date de fin — la demi-journee/le motif restent des champs avances non
    exposes sur cet ecran minimal (creation directe possible via l'API
    pour les cas plus riches)."""
    tenant = resolve_tenant(request)
    employee = PrsEmployee.objects.filter(tenant=tenant, user=request.user, is_active=True).first()
    error = ""
    if request.method == "POST" and employee is not None:
        absence_type = get_object_or_404(PrsAbsenceType, id=request.POST.get("type_id"))
        date_from = parse_date(request.POST.get("date_from", ""))
        date_to = parse_date(request.POST.get("date_to", ""))
        if date_from is None or date_to is None:
            error = "dates_invalides"
        else:
            try:
                absence = create_absence(
                    tenant,
                    employee=employee,
                    absence_type=absence_type,
                    date_from=date_from,
                    date_to=date_to,
                )
                submit_absence(absence, request.user)
                return redirect("presence:absence_request")
            except ValidationError as exc:
                error = "; ".join(exc.messages)

    types = PrsAbsenceType.objects.filter(tenant=tenant, is_active=True).order_by("name")
    default_type = types.first()
    my_absences = (
        PrsAbsence.objects.filter(tenant=tenant, employee=employee, is_active=True).order_by(
            "-date_from"
        )[:20]
        if employee is not None
        else []
    )
    return render(
        request,
        "presence/absence_request.html",
        {
            "types": types,
            "default_type_id": default_type.id if default_type else None,
            "employee": employee,
            "error": error,
            "my_absences": my_absences,
        },
    )


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Tableau de bord RH (§5.9.5) : taux de presence, absenteisme, heures
    sup, soldes de conges a risque d'expiration."""
    tenant = resolve_tenant(request)
    today = dt.date.today()

    total_employees = PrsEmployee.objects.filter(tenant=tenant, is_active=True).count()
    present_today = (
        PrsAttendance.objects.filter(tenant=tenant, is_active=True, date=today)
        .values("employee_id")
        .distinct()
        .count()
    )
    absent_today = (
        PrsAbsence.objects.filter(
            tenant=tenant,
            is_active=True,
            date_from__lte=today,
            date_to__gte=today,
            state__in=[PrsAbsence.STATE_VALIDATED, PrsAbsence.STATE_IN_PROGRESS],
        )
        .values("employee_id")
        .distinct()
        .count()
    )
    presence_rate = (
        (Decimal(present_today) / Decimal(total_employees) * 100) if total_employees else Decimal(0)
    )
    absenteeism_rate = (
        (Decimal(absent_today) / Decimal(total_employees) * 100) if total_employees else Decimal(0)
    )

    from apps.presence.models import PrsLeaveBalance, PrsOvertime

    overtime_hours_month = PrsOvertime.objects.filter(
        tenant=tenant,
        is_active=True,
        state=PrsOvertime.STATE_VALIDATED,
        date__year=today.year,
        date__month=today.month,
    )
    total_overtime = sum((o.hours for o in overtime_hours_month), Decimal(0))

    at_risk_balances = PrsLeaveBalance.objects.filter(
        tenant=tenant,
        is_active=True,
        expiry_date__isnull=False,
        expiry_date__lte=today + dt.timedelta(days=60),
    ).select_related("employee", "type")

    return render(
        request,
        "presence/dashboard.html",
        {
            "presence_rate": presence_rate.quantize(Decimal("0.1")),
            "absenteeism_rate": absenteeism_rate.quantize(Decimal("0.1")),
            "total_overtime": total_overtime,
            "at_risk_balances": at_risk_balances,
        },
    )
