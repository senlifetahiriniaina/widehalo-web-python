"""Ecrans HTMX minimaux du module `accounting` (verification des 14
couches, U1) : liste des factures client, detail avec bandeau de workflow
+ panneau lateral (audit/documents), formulaire de creation. Meme patron
que `apps.partners.views` : chaque vue appelle directement les fonctions
de service, jamais l'API ninja, authentification par session."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    AccAccount,
    AccJournal,
    AccMove,
    AccPayment,
    AccPaymentAllocation,
    AccPeriod,
)
from apps.accounting.services.einvoice_submission import CONNECTOR_CODE, DOCUMENT_TYPE
from apps.accounting.services.einvoice_verdict import (
    MARKED_VARIANT,
    refresh_from_exchanges,
    render_marked_representation,
    verdict_summary,
)
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    cancel_invoice,
    create_invoice,
    validate_invoice,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.payments import register_payment
from apps.accounting.services.quick_entry import suggest_counterpart_account
from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.user import User
from apps.core.services.approvals import pending_for_object
from apps.core.services.documents import store_document
from apps.core.services.next_steps import next_steps_for
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.presentation import presentation_response
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.flows.services.public import describe_signing_certificate, document_exchange_panel

QUICK_ENTRY_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="date", label=_("Date"), searchable=False),
    Column(key="state", label=_("État")),
    Column(key="total_debit", label=_("Débit"), format="mga", searchable=False),
    Column(key="total_credit", label=_("Crédit"), format="mga", searchable=False),
]


COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="date", label=_("Date")),
    Column(key="invoice_state", label=_("Statut")),
    Column(key="total_debit", label=_("Montant (MGA)"), format="mga", searchable=False),
]


@login_required
@screen_permission("accounting.view_accmove")
def invoice_list(request: HttpRequest) -> HttpResponse:
    queryset = AccMove.objects.filter(move_type=AccMove.TYPE_CUSTOMER_INVOICE, is_active=True)
    return presentation_response(
        request,
        table_key="accounting.invoices",
        model_label="accounting.AccMove",
        columns=COLUMNS,
        queryset=queryset,
        page_template="accounting/list.html",
        page_context={"row_url_name": "accounting:detail"},
    )


#: Droit exige par chaque action de l'ecran de facture, aligne sur les
#: codenames que l'API porte deja pour les memes operations
#: (`apps/accounting/api.py` : `validate_accmove` pour la validation,
#: `change_accmove` pour l'enregistrement d'un reglement). Le depot de
#: piece jointe n'a pas d'`action` et retombe donc sur le defaut,
#: `change_accmove` — modifier la facture en lui attachant un document.
_DROITS_FACTURE = {
    "validate": "accounting.validate_accmove",
    "cancel": "accounting.cancel_accmove",
    "register_payment": "accounting.change_accmove",
}


@login_required
@screen_permission("accounting.view_accmove")
def invoice_detail(request: HttpRequest, invoice_id: str) -> HttpResponse:
    invoice = get_object_or_404(AccMove, id=invoice_id, move_type=AccMove.TYPE_CUSTOMER_INVOICE)
    content_type = ContentType.objects.get_for_model(AccMove)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        # Le depot de piece jointe ne poste AUCUN champ `action` (cf.
        # `templates/accounting/detail.html`, formulaire multipart). Il doit
        # donc etre une branche a part entiere de cet aiguillage.
        #
        # **Avant C-1, il n'en etait pas une, et rien ne se produisait.** Le
        # bloc `store_document(...)` vivait APRES ce `try/except/else`, dont
        # le `else` retourne une redirection des qu'aucune exception n'est
        # levee — c'est-a-dire sur tout POST sans `action` reconnue. Le code
        # de depot etait donc inatteignable : l'exploitant choisissait un
        # fichier, validait, revenait sur sa facture, et rien n'etait
        # enregistre, sans le moindre message. Douzieme occurrence du motif
        # « rien de decoratif » de cette vague, et l'une des pires : une
        # perte silencieuse de ce que l'utilisateur croyait deposer.
        uploaded_file = request.FILES.get("document")
        refus = screen_forbidden(
            request, _DROITS_FACTURE.get(action or "", "accounting.change_accmove")
        )
        if refus is not None:
            return refus
        try:
            if action == "validate":
                validate_invoice(invoice, user)
            elif action == "cancel":
                cancel_invoice(invoice, user, motif=request.POST.get("motif", ""))
            elif action == "register_payment":
                period = (
                    AccPeriod.objects.filter(tenant=invoice.tenant, state=AccPeriod.STATE_OPEN)
                    .order_by("date_start")
                    .first()
                )
                if period is None:
                    raise ValidationError(_("Aucune période ouverte pour cet exercice."))
                payment_journal = get_object_or_404(
                    AccJournal, id=request.POST.get("payment_journal_id")
                )
                cash_account = get_object_or_404(AccAccount, id=request.POST.get("cash_account_id"))
                gain_account = get_object_or_404(AccAccount, id=request.POST.get("gain_account_id"))
                loss_account = get_object_or_404(AccAccount, id=request.POST.get("loss_account_id"))
                register_payment(
                    invoice=invoice,
                    period=period,
                    journal=payment_journal,
                    cash_account=cash_account,
                    gain_account=gain_account,
                    loss_account=loss_account,
                    date=date.fromisoformat(
                        request.POST.get("payment_date") or date.today().isoformat()
                    ),
                    amount=Decimal(request.POST.get("payment_amount") or "0"),
                    method=request.POST.get("method", AccPayment.METHOD_TRANSFER),
                )
            elif uploaded_file is not None:
                store_document(
                    tenant=invoice.tenant,
                    uploaded_file=uploaded_file,
                    uploaded_by=user if user.is_authenticated else None,
                    content_object=invoice,
                )
        except (ApprovalRequiredError, ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("accounting:detail", invoice_id=invoice.id)

    # T4 (EFA-4) — « l'identifiant attribué et le marquage vérifiable sont
    # reportés sur la REPRÉSENTATION LISIBLE du document ». Elle est un
    # second document, distinct de celui qui a été soumis : ce dernier
    # reste figé et signé (RPT-9), celui-ci porte le marquage. Sans ce
    # chemin, la représentation existerait sans que personne ne puisse
    # l'atteindre — le critère ne serait pas tenu.
    if request.GET.get("representation") == MARKED_VARIANT:
        contenu = render_marked_representation(
            invoice, actor=user if user.is_authenticated else None
        )
        if contenu is None:
            raise Http404(_("Cette facture n'a pas encore reçu de verdict fiscal."))
        return HttpResponse(contenu, content_type="text/plain; charset=utf-8")

    audit_entries = AuditLog.objects.filter(
        content_type=content_type, object_id=str(invoice.id)
    ).order_by("-created_at")[:20]
    documents = Document.objects.filter(content_type=content_type, object_id=str(invoice.id))
    payment_journals = AccJournal.objects.filter(
        tenant=invoice.tenant, type__in=[AccJournal.TYPE_BANK, AccJournal.TYPE_CASH]
    ).order_by("code")
    cash_accounts = AccAccount.objects.filter(
        tenant=invoice.tenant, is_active=True, type__in=[AccAccount.TYPE_BANK, AccAccount.TYPE_CASH]
    ).order_by("code")
    accounts = AccAccount.objects.filter(tenant=invoice.tenant, is_active=True).order_by("code")
    allocations = AccPaymentAllocation.objects.filter(move_line__move=invoice).select_related(
        "payment", "move_line"
    )
    default_payment_journal = payment_journals.first()
    default_cash_account = cash_accounts.first()

    # T4 — relire les verdicts arrivés depuis le dernier affichage. C'est
    # ce chemin qui donne un appelant de production à
    # `refresh_from_exchanges` : sans lui, un verdict revenu du hub ne
    # serait jamais inscrit sur la pièce, et l'écran afficherait
    # indéfiniment « en attente » alors que l'administration a tranché.
    refresh_from_exchanges(invoice)
    certificat = describe_signing_certificate(invoice.tenant, connector_code=CONNECTOR_CODE)
    verdict = verdict_summary(invoice)

    return render(
        request,
        "accounting/detail.html",
        {
            "next_steps": next_steps_for(invoice, user),
            # D-B : ce que la fiche doit dire quand elle refuse de se
            # valider. Sans cela, l'exploitant lit « en attente
            # d'approbation » une fois, au moment du clic, et plus rien
            # ensuite.
            "demandes_en_attente": pending_for_object(invoice),
            "invoice": invoice,
            "lines": invoice.lines.all(),
            "audit_entries": audit_entries,
            "documents": documents,
            "payment_journals": payment_journals,
            "cash_accounts": cash_accounts,
            "accounts": accounts,
            "default_payment_journal_id": (
                default_payment_journal.id if default_payment_journal else None
            ),
            "default_cash_account_id": default_cash_account.id if default_cash_account else None,
            "payment_methods": AccPayment.METHOD_CHOICES,
            "allocations": allocations,
            "error": error,
            "today": date.today(),
            # T8 (CON-1) — l'état des ÉCHANGES de la pièce, à côté de l'axe
            # fiscal et jamais à sa place : le fragment fiscal de T4 rend
            # `fiscal_state` (EFA-6), celui-ci rend ce que le hub a fait de
            # cette facture, opération par opération.
            **document_exchange_panel(
                invoice.tenant, document_type=DOCUMENT_TYPE, document_id=invoice.id
            ),
            # T4 — l'état fiscal est un TROISIÈME axe : il voisine l'état de
            # règlement sans jamais le conditionner (EFA-6).
            "fiscal_state": invoice.fiscal_state,
            "fiscal_state_display": invoice.get_fiscal_state_display(),
            "fiscal_reference": verdict.fiscal_reference,
            "marked_available": bool(
                invoice.fiscal_state == AccMove.FISCAL_STATE_ACCEPTED and verdict.fiscal_reference
            ),
            # `awaiting_link` distingue les deux attentes que le bandeau
            # formule différemment : « le raccordement n'est pas ouvert »
            # n'appelle aucune action de l'utilisateur, « en attente de
            # verdict » dit quand la prochaine tentative aura lieu.
            "awaiting_link": invoice.fiscal_state == AccMove.FISCAL_STATE_TO_SUBMIT,
            "certificate": certificat,
        },
    )


@login_required
# Un ecran dont la SEULE raison d'etre est la creation exige le droit de
# creer pour s'ouvrir, et pas seulement pour se soumettre : laisser un
# role en lecture seule remplir un formulaire pour le refuser a l'envoi
# lui fait perdre sa saisie et ne lui apprend rien plus tot.
@screen_permission("accounting.add_accmove")
def invoice_create(request: HttpRequest) -> HttpResponse:
    """Formulaire minimal : une facture a ligne de produit unique (le
    detail multi-lignes reste accessible via l'API pour les besoins
    avances — coherent avec le perimetre "ecran minimal" de cette phase)."""
    tenant = resolve_tenant(request)
    journals = AccJournal.objects.filter(tenant=tenant, type=AccJournal.TYPE_SALE).order_by("code")
    receivable_accounts = AccAccount.objects.filter(
        tenant=tenant, is_active=True, type=AccAccount.TYPE_RECEIVABLE
    ).order_by("code")
    income_accounts = AccAccount.objects.filter(
        tenant=tenant, is_active=True, type=AccAccount.TYPE_INCOME
    ).order_by("code")
    default_journal = journals.first()
    default_receivable_account = receivable_accounts.first()
    default_income_account = income_accounts.first()
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accmove")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            journal = get_object_or_404(AccJournal, id=request.POST.get("journal_id"))
            period = (
                AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN)
                .order_by("date_start")
                .first()
            )
            if period is None:
                raise ValidationError(_("Aucune période ouverte pour cet exercice."))
            receivable_account = get_object_or_404(
                AccAccount, id=request.POST.get("receivable_account_id")
            )
            income_account = get_object_or_404(AccAccount, id=request.POST.get("income_account_id"))
            amount = Decimal(request.POST.get("amount") or "0")
            invoice = create_invoice(
                tenant=tenant,
                journal=journal,
                period=period,
                date=date.fromisoformat(request.POST.get("date") or date.today().isoformat()),
                partner_id=None,
                receivable_account=receivable_account,
                income_lines=[
                    {
                        "account": income_account,
                        "amount": amount,
                        "label": request.POST.get("label", ""),
                    }
                ],
            )
        except (ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("accounting:detail", invoice_id=invoice.id)

    return render(
        request,
        "accounting/create.html",
        {
            "journals": journals,
            "receivable_accounts": receivable_accounts,
            "income_accounts": income_accounts,
            "default_journal_id": default_journal.id if default_journal else None,
            "default_receivable_account_id": (
                default_receivable_account.id if default_receivable_account else None
            ),
            "default_income_account_id": (
                default_income_account.id if default_income_account else None
            ),
            "error": error,
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# Saisie comptable rapide (X2, Sprint 8 / L5)
# ---------------------------------------------------------------------------


@login_required
@screen_permission("accounting.view_accmove")
def quick_entry_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    # C-2 : cet ecran portait DEUX tables — les brouillons, puis « les 50
    # ecritures publiees les plus recentes ». Cette troncature ne se disait
    # nulle part : au-dela de 50, les ecritures disparaissaient de l'ecran
    # sans que rien ne l'indique. Une seule liste paginee, avec l'etat en
    # colonne, les rend toutes atteignables et les rend cherchables.
    return smart_table_response(
        request,
        table_key="accounting.quick_entries",
        columns=QUICK_ENTRY_COLUMNS,
        queryset=AccMove.objects.filter(
            tenant=tenant, move_type=AccMove.TYPE_ENTRY, is_active=True
        ),
        page_template="accounting/quick_entry_list.html",
        page_context={"row_url_name": "accounting:quick_entry_detail"},
    )


@login_required
# Un ecran dont la SEULE raison d'etre est la creation exige le droit de
# creer pour s'ouvrir, et pas seulement pour se soumettre : laisser un
# role en lecture seule remplir un formulaire pour le refuser a l'envoi
# lui fait perdre sa saisie et ne lui apprend rien plus tot.
@screen_permission("accounting.add_accmove")
def quick_entry_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    journals = AccJournal.objects.filter(tenant=tenant).order_by("code")
    periods = AccPeriod.objects.filter(tenant=tenant, state=AccPeriod.STATE_OPEN).order_by(
        "date_start"
    )
    default_journal = journals.first()
    default_period = periods.first()
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_accmove")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            journal = get_object_or_404(
                AccJournal, id=request.POST.get("journal_id"), tenant=tenant
            )
            period = get_object_or_404(AccPeriod, id=request.POST.get("period_id"), tenant=tenant)
            move = create_draft_move(
                tenant=tenant,
                journal=journal,
                period=period,
                date=date.fromisoformat(request.POST.get("date") or date.today().isoformat()),
                narration=request.POST.get("narration", ""),
            )
        except (ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("accounting:quick_entry_detail", move_id=move.id)

    return render(
        request,
        "accounting/quick_entry_create.html",
        {
            "journals": journals,
            "periods": periods,
            "default_journal_id": default_journal.id if default_journal else None,
            "default_period_id": default_period.id if default_period else None,
            "error": error,
            "today": date.today(),
        },
    )


@login_required
@screen_permission("accounting.view_accmove")
def quick_entry_detail(request: HttpRequest, move_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    move = get_object_or_404(AccMove, id=move_id, tenant=tenant, move_type=AccMove.TYPE_ENTRY)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accmove")
        if refus is not None:
            return refus

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_line":
                account = get_object_or_404(
                    AccAccount, id=request.POST.get("account_id"), tenant=tenant
                )
                add_line(
                    move,
                    account=account,
                    label=request.POST.get("label", ""),
                    debit=Decimal(request.POST.get("debit") or "0"),
                    credit=Decimal(request.POST.get("credit") or "0"),
                )
            elif action == "post":
                post_move(move)
        except (ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("accounting:quick_entry_detail", move_id=move.id)

    lines = list(move.lines.select_related("account").all())
    totals = move.lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    total_debit = totals["debit"] or Decimal(0)
    total_credit = totals["credit"] or Decimal(0)
    suggested_account = (
        suggest_counterpart_account(tenant=tenant, account=lines[-1].account) if lines else None
    )

    return render(
        request,
        "accounting/quick_entry_detail.html",
        {
            "move": move,
            "lines": lines,
            "accounts": AccAccount.objects.filter(tenant=tenant, is_active=True).order_by("code"),
            "total_debit": total_debit,
            "total_credit": total_credit,
            "balance": total_debit - total_credit,
            "suggested_account": suggested_account,
            "error": error,
        },
    )
