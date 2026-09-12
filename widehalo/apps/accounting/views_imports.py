"""Ecrans d'import comptable/caisse (session HTMX, jamais l'API JWT en
interne — meme discipline que le reste des ecrans `accounting`). Regroupes
sous le hub "Parametres" (cf. `views_config.py`) plutot que sous le prefixe
transactionnel `/accounting/`, coherent avec le placement deja acte des
autres ecrans de configuration."""

from __future__ import annotations

import datetime as dt
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.accounting.models import (
    AccAccount,
    AccImportBatch,
    AccImportRow,
    AccInvoiceImportBatch,
    AccInvoiceImportRow,
)
from apps.accounting.services.cash_journal_import import (
    import_cash_journal_xlsx,
    qualify_import_row,
    resolve_import_row,
)
from apps.accounting.services.chart_of_accounts_import import import_chart_of_accounts_xlsx
from apps.accounting.services.invoice_import import import_invoices_xlsx
from apps.accounting.services.invoice_import import (
    qualify_import_row as qualify_invoice_import_row,
)
from apps.accounting.services.invoice_import import (
    resolve_import_row as resolve_invoice_import_row,
)
from apps.core.services.import_xlsx import build_xlsx_template
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.tenant_web import resolve_tenant


def _xlsx_template_response(data: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(
        data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    batches = AccImportBatch.objects.filter(tenant=tenant).order_by("-created_at")[:20]
    return render(request, "accounting/imports/index.html", {"batches": batches})


@login_required
@screen_permission("accounting.view_accaccount")
def download_chart_of_accounts_template(request: HttpRequest) -> HttpResponse:
    data = build_xlsx_template(
        ["Code", "Intitulé", "Classe", "Nature", "Catégorie de caisse"],
        example_row=["601000", "Achats de matières premières", 6, "CHARGE", "Achats matière"],
    )
    return _xlsx_template_response(data, "modele_import_plan_comptable.xlsx")


@login_required
@screen_permission("accounting.view_accjournal")
def download_cash_journal_template(request: HttpRequest) -> HttpResponse:
    data = build_xlsx_template(
        [
            "Date",
            "Caisse",
            "Catégorie",
            "Exclu des totaux",
            "Compte PCG",
            "Libellé",
            "Entrée",
            "Sortie",
        ],
        example_row=[
            dt.date.today(),
            "CAISSE PRINCIPALE",
            "Achats matière",
            "",
            "601000",
            "Achat de tissu",
            "",
            150000,
        ],
    )
    return _xlsx_template_response(data, "modele_import_journal_caisse.xlsx")


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_chart_of_accounts(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accaccount")
        if refus is not None:
            return refus

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_chart_of_accounts_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "accounting/imports/chart_of_accounts.html",
        {"summary": summary, "error": error},
    )


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_cash_journal(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accmove")
        if refus is not None:
            return refus

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_cash_journal_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    return render(
        request,
        "accounting/imports/cash_journal.html",
        {"summary": summary, "error": error},
    )


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_cash_journal_batch_detail(request: HttpRequest, batch_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    batch = get_object_or_404(AccImportBatch, tenant=tenant, id=batch_id)
    rows = batch.rows.order_by("row_number")
    accounts = AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code")
    return render(
        request,
        "accounting/imports/cash_journal_batch_detail.html",
        {"batch": batch, "rows": rows, "accounts": accounts},
    )


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_cash_journal_row_resolve(request: HttpRequest, row_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    row = get_object_or_404(AccImportRow, tenant=tenant, id=row_id)

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.qualify_accimportrow")
        if refus is not None:
            return refus

    if request.method == "POST":
        if request.POST.get("discard"):
            resolve_import_row(row, discard=True)
        else:
            account_id = request.POST.get("account_id") or None
            account = (
                AccAccount.objects.filter(tenant=tenant, id=account_id).first()
                if account_id
                else None
            )
            resolve_import_row(row, account=account)

    return redirect("accounting:imports_cash_journal_batch_detail", batch_id=row.batch_id)


@login_required
@screen_permission("accounting.view_accimportbatch")
def imports_cash_journal_row_qualify(request: HttpRequest, row_id: str) -> HttpResponse:
    """Ecran "à qualifier" (chantier RG-QUALIF) — remplace le(s)
    placeholder(s) d'une ligne `needs_qualification` par l'entite reelle
    saisie, potentiellement gate par la nouvelle `ApprovalRule` de
    qualification (visible ensuite dans l'ecran generique "Mes
    validations en attente")."""
    tenant = resolve_tenant(request)
    row = get_object_or_404(AccImportRow, tenant=tenant, id=row_id)

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.qualify_accimportrow")
        if refus is not None:
            return refus

    if request.method == "POST":
        account_id = request.POST.get("account_id") or None
        account = (
            AccAccount.objects.filter(tenant=tenant, id=account_id).first() if account_id else None
        )
        partner_id_raw = request.POST.get("partner_id") or None
        partner_id = uuid.UUID(partner_id_raw) if partner_id_raw else None
        qualify_import_row(row, account=account, partner_id=partner_id, qualified_by=request.user)

    return redirect("accounting:imports_cash_journal_batch_detail", batch_id=row.batch_id)


# --------------------------------------------------------------------------
# G-4 — l'import de factures fournisseur, et sa qualification validée
# --------------------------------------------------------------------------
#
# **Le service existait au complet, l'écran non.** `invoice_import` lit le
# fichier, groupe les lignes par facture, résout tiers/produit/compte/TVA,
# isole les lignes non résolubles, matérialise l'écriture, et fait passer
# une qualification par le moteur d'approbation quand elle remplace un
# placeholder. Aucune de ces six capacités n'était atteignable : le module
# n'avait d'écran que pour le plan comptable et le journal de caisse.


@login_required
@screen_permission("accounting.view_accinvoiceimportbatch")
def download_invoice_template(request: HttpRequest) -> HttpResponse:
    """Le modèle de fichier, dérivé des en-têtes que le service accepte.

    Les libellés viennent du premier alias déclaré de chaque champ dans
    `INVOICE_IMPORT_HEADER_ALIASES` — écrire ici une seconde liste ferait
    diverger le modèle téléchargé du format réellement lu, et la divergence
    ne se verrait qu'au premier import raté."""
    return _xlsx_template_response(
        build_xlsx_template(
            [
                "REFERENCE",
                "DATE",
                "SENS",
                "PARTENAIRE",
                "CODE_PRODUIT",
                "DESIGNATION",
                "QUANTITE",
                "PRIX_UNITAIRE",
                "TAUX_TVA",
                "COMPTE",
            ],
            example_row=[
                "FA-2026-001",
                dt.date.today(),
                "achat",
                "Fournisseur Andry",
                "ART-001",
                "Tissu coton",
                10,
                15000,
                20,
                "601000",
            ],
        ),
        "modele_import_factures.xlsx",
    )


@login_required
@screen_permission("accounting.view_accinvoiceimportbatch")
def imports_invoices(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accmove")
        if refus is not None:
            return refus
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_invoices_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except (ValueError, ValidationError) as exc:
                error = "; ".join(getattr(exc, "messages", [str(exc)]))

    return render(
        request,
        "accounting/imports/invoices.html",
        {
            "summary": summary,
            "error": error,
            "batches": AccInvoiceImportBatch.objects.filter(tenant=tenant).order_by("-created_at")[
                :20
            ],
        },
    )


@login_required
@screen_permission("accounting.view_accinvoiceimportbatch")
def imports_invoices_batch_detail(request: HttpRequest, batch_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    batch = get_object_or_404(AccInvoiceImportBatch, tenant=tenant, id=batch_id)
    return render(
        request,
        "accounting/imports/invoices_batch_detail.html",
        {
            "batch": batch,
            "rows": batch.rows.order_by("row_number"),
            "accounts": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
        },
    )


@login_required
@screen_permission("accounting.qualify_accinvoiceimportrow")
def imports_invoices_row_discard(request: HttpRequest, row_id: str) -> HttpResponse:
    """Écarter une ligne non résoluble.

    La garde d'écriture est AU DÉCORATEUR parce que cette vue n'existe que
    pour écrire : un rôle en lecture seule ne doit pas cliquer un bouton
    pour se le faire refuser à l'envoi (C-1d)."""
    tenant = resolve_tenant(request)
    row = get_object_or_404(AccInvoiceImportRow, tenant=tenant, id=row_id)
    if request.method == "POST":
        resolve_invoice_import_row(row, discard=True)
    return redirect("accounting:imports_invoices_batch_detail", batch_id=row.batch_id)


@login_required
@screen_permission("accounting.qualify_accinvoiceimportrow")
def imports_invoices_row_qualify(request: HttpRequest, row_id: str) -> HttpResponse:
    """Remplacer un placeholder par l'entité réelle.

    Quand la ligne en portait un, `qualify_import_row` crée une demande
    d'approbation : la décision revient au rôle approbateur depuis « Mes
    validations », jamais à celui qui saisit."""
    tenant = resolve_tenant(request)
    row = get_object_or_404(AccInvoiceImportRow, tenant=tenant, id=row_id)
    if request.method == "POST":
        compte_id = request.POST.get("account_id") or None
        tiers_id = request.POST.get("partner_id") or None
        qualify_invoice_import_row(
            row,
            account=(
                AccAccount.objects.filter(tenant=tenant, id=compte_id).first()
                if compte_id
                else None
            ),
            partner_id=uuid.UUID(tiers_id) if tiers_id else None,
            qualified_by=request.user,
        )
    return redirect("accounting:imports_invoices_batch_detail", batch_id=row.batch_id)
