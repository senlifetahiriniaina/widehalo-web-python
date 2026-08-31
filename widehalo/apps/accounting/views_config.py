"""Ecrans de configuration/master-data du module `accounting` (U3),
regroupes sous le hub "Parametres" plutot que sous le prefixe
transactionnel `/accounting/` (cf. decision de placement, plan Lot 2).
Une seule page liste+creation par entite simple, meme patron que
`apps.accounting.views` (formulaire simple, pas d'API ninja)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccPaymentTerm,
    AccPaymentTermLine,
    AccPeriod,
    AccTax,
)
from apps.core.views.tenant_web import resolve_tenant


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "accounting/config_index.html", {})


@login_required
def config_fiscal_years(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            AccFiscalYear.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                date_start=date.fromisoformat(request.POST.get("date_start", "")),
                date_end=date.fromisoformat(request.POST.get("date_end", "")),
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    fiscal_years = AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start")
    return render(
        request,
        "accounting/config_fiscal_years.html",
        {"fiscal_years": fiscal_years, "error": error},
    )


@login_required
def config_periods(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    fiscal_years = AccFiscalYear.objects.filter(tenant=tenant).order_by("-date_start")
    error = None

    if request.method == "POST":
        try:
            fiscal_year = fiscal_years.get(id=request.POST.get("fiscal_year_id"))
            AccPeriod.objects.create(
                tenant=tenant,
                fiscal_year=fiscal_year,
                code=request.POST.get("code", ""),
                date_start=date.fromisoformat(request.POST.get("date_start", "")),
                date_end=date.fromisoformat(request.POST.get("date_end", "")),
            )
        except AccFiscalYear.DoesNotExist:
            error = _("Exercice introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    periods = AccPeriod.objects.filter(tenant=tenant).order_by("-date_start")
    default_fiscal_year = fiscal_years.first()
    return render(
        request,
        "accounting/config_periods.html",
        {
            "periods": periods,
            "fiscal_years": fiscal_years,
            "default_fiscal_year_id": default_fiscal_year.id if default_fiscal_year else None,
            "error": error,
        },
    )


@login_required
def config_journals(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            default_account_id = request.POST.get("default_account_id") or None
            default_account = accounts.get(id=default_account_id) if default_account_id else None
            AccJournal.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                type=request.POST.get("type", AccJournal.TYPE_MISC),
                default_account=default_account,
                sequence_prefix=request.POST.get("sequence_prefix", ""),
                currency=request.POST.get("currency") or "MGA",
            )
        except AccAccount.DoesNotExist:
            error = _("Compte par defaut introuvable.")
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    journals = AccJournal.objects.filter(tenant=tenant).order_by("code")
    return render(
        request,
        "accounting/config_journals.html",
        {
            "journals": journals,
            "accounts": accounts,
            "type_choices": AccJournal.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def config_accounts(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant).order_by("code")
    error = None

    if request.method == "POST":
        try:
            parent_id = request.POST.get("parent_id") or None
            parent = accounts.get(id=parent_id) if parent_id else None
            AccAccount.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                account_class=int(request.POST.get("account_class") or 0),
                parent=parent,
                type=request.POST.get("type", AccAccount.TYPE_EXPENSE),
                reconcilable=bool(request.POST.get("reconcilable")),
                currency=request.POST.get("currency") or "MGA",
                analytic_required=bool(request.POST.get("analytic_required")),
            )
        except AccAccount.DoesNotExist:
            error = _("Compte parent introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    accounts = AccAccount.objects.filter(tenant=tenant).order_by("code")
    return render(
        request,
        "accounting/config_accounts.html",
        {
            "accounts": accounts,
            "type_choices": AccAccount.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def config_taxes(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            collected_id = request.POST.get("account_collected_id") or None
            deductible_id = request.POST.get("account_deductible_id") or None
            AccTax.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                type=request.POST.get("type", AccTax.TYPE_SALE),
                rate=Decimal(request.POST.get("rate") or "0"),
                is_included=bool(request.POST.get("is_included")),
                account_collected=accounts.get(id=collected_id) if collected_id else None,
                account_deductible=accounts.get(id=deductible_id) if deductible_id else None,
                valid_from=(
                    date.fromisoformat(request.POST["valid_from"])
                    if request.POST.get("valid_from")
                    else None
                ),
                valid_to=(
                    date.fromisoformat(request.POST["valid_to"])
                    if request.POST.get("valid_to")
                    else None
                ),
            )
        except AccAccount.DoesNotExist:
            error = _("Compte introuvable.")
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    taxes = AccTax.objects.filter(tenant=tenant).order_by("code")
    return render(
        request,
        "accounting/config_taxes.html",
        {
            "taxes": taxes,
            "accounts": accounts,
            "type_choices": AccTax.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def config_payment_terms(request: HttpRequest) -> HttpResponse:
    """Formulaire minimal : une condition de paiement creee avec une seule
    ligne (le multi-lignes reste accessible via l'API pour les besoins
    avances — meme simplification que `apps.accounting.views::invoice_create`)."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            term = AccPaymentTerm.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
            )
            AccPaymentTermLine.objects.create(
                tenant=tenant,
                term=term,
                sequence=0,
                value_type=request.POST.get("value_type", AccPaymentTermLine.VALUE_TYPE_BALANCE),
                days=int(request.POST.get("days") or 0),
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    payment_terms = AccPaymentTerm.objects.filter(tenant=tenant).prefetch_related("lines")
    return render(
        request,
        "accounting/config_payment_terms.html",
        {
            "payment_terms": payment_terms,
            "value_type_choices": AccPaymentTermLine.VALUE_TYPE_CHOICES,
            "error": error,
        },
    )
