"""G-3 — le recouvrement, les ordres de virement, les échéances fiscales et
les relevés de monnaie électronique.

**Quatre chaînes complètes, aucune porte.** La mesure est la même pour les
quatre : le service est livré, testé, exposé en API, et l'exploitant devant
un navigateur ne peut rien en faire.

- `dunning` sait dire quelles créances sont échues et à quel palier de
  relance elles en sont — rien ne l'affichait.
- `transfer_orders` porte le cycle complet de BNK-4, et **deux de ses
  quatre transitions n'ont AUCUN appelant de production** : `mark_remitted`
  et `reconcile_transfer_order`. Le critère dit « son état de remise est
  suivi jusqu'au rapprochement du débit correspondant » ; le suivi
  s'arrêtait à l'export.
- `tax_calendar` sait ce qui est dû à l'administration et quand — personne
  ne pouvait le lire.
- `mobile_money` sait charger un relevé d'agrégateur et rapprocher ses
  lignes d'un règlement — aucun écran pour déposer le fichier.

**L'ordre de virement part des pièces qu'il règle, jamais d'une saisie
libre.** C'est la moitié du critère qu'un formulaire de bénéficiaires
aurait perdue : l'écran liste les dettes fournisseur ouvertes et compose
l'ordre à partir de celles qu'on coche. Le lien vers la pièce est ainsi
établi à la composition, pas reconstitué après coup.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccDunningAction,
    AccDunningLevel,
    AccMobileMoneyStatementLine,
    AccMove,
    AccMoveLine,
    AccPayment,
    AccTaxCalendar,
    AccTransferOrder,
)
from apps.accounting.services.dunning import (
    overdue_receivables,
    record_dunning_action,
    seed_default_dunning_levels,
)
from apps.accounting.services.mobile_money import (
    import_mobile_money_statement,
    reconcile_mobile_money_line,
    unmatched_mobile_money_lines,
)
from apps.accounting.services.tax_calendar import (
    create_tax_calendar_entry,
    seed_default_tax_calendar,
    upcoming_deadlines,
)
from apps.accounting.services.transfer_orders import (
    create_transfer_order,
    export_transfer_order,
    mark_remitted,
    orders_in_flight,
    reconcile_transfer_order,
)
from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.partners.services.public import get_partner_display_names

#: Le type de pièce inscrit sur une ligne d'ordre composée ici. Le couple
#: (type, identifiant) est opaque côté `transfer_orders` : c'est l'écran qui
#: sait ce qu'il désigne, et il le nomme une seule fois.
TYPE_PIECE_REGLEE = "accounting.AccMoveLine"

TRANSFER_ORDER_COLUMNS = [
    Column(key="reference", label=_("Référence")),
    Column(key="origin", label=_("Origine")),
    Column(key="execution_date", label=_("Exécution"), searchable=False),
    Column(key="total_amount", label=_("Montant"), searchable=False, format="mga"),
    Column(key="state", label=_("État")),
]


def _montant(brut: str | None) -> Decimal:
    try:
        return Decimal((brut or "0").replace(" ", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValidationError(_("Montant illisible : %(v)s") % {"v": brut}) from exc


def _date(brut: str | None) -> dt.date:
    try:
        return dt.date.fromisoformat(brut or "")
    except ValueError as exc:
        raise ValidationError(_("Date illisible : %(v)s") % {"v": brut}) from exc


def _messages(exc: ValidationError) -> str:
    return "; ".join(getattr(exc, "messages", [str(exc)]))


# --------------------------------------------------------------------------
# Relances client
# --------------------------------------------------------------------------


@login_required
@screen_permission("accounting.view_accdunningaction")
def dunning_screen(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        action = request.POST.get("action", "")
        refus = screen_forbidden(
            request,
            "accounting.add_accdunninglevel"
            if action == "seed_levels"
            else "accounting.add_accdunningaction",
        )
        if refus is not None:
            return refus
        try:
            if action == "seed_levels":
                seed_default_dunning_levels(tenant)
            elif action == "record":
                record_dunning_action(
                    get_object_or_404(AccMoveLine, id=request.POST.get("move_line_id")),
                    get_object_or_404(
                        AccDunningLevel, id=request.POST.get("level_id"), tenant=tenant
                    ),
                    date_sent=_date(request.POST.get("date_sent")),
                    notes=request.POST.get("notes", ""),
                )
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:dunning")

    creances = overdue_receivables(tenant)
    noms = get_partner_display_names({ligne["partner_id"] for ligne in creances})
    paliers = list(AccDunningLevel.objects.filter(tenant=tenant).order_by("level"))
    par_niveau = {palier.level: palier for palier in paliers}
    for ligne in creances:
        # **Le tiers par son nom, jamais son identifiant technique.** Défaut
        # mesuré trois fois en D-1 : une colonne « Partenaire » rendant un
        # UUIDv7, dont les quatorze premiers caractères sont identiques d'une
        # ligne à l'autre le même jour.
        ligne["partner_display"] = noms.get(str(ligne["partner_id"]), "")
        ligne["level_label"] = (
            par_niveau[ligne["applicable_level"]].label
            if ligne["applicable_level"] in par_niveau
            else ""
        )

    return render(
        request,
        "accounting/dunning.html",
        {
            "creances": creances,
            "paliers": paliers,
            "actions": AccDunningAction.objects.select_related("level", "move_line").order_by(
                "-date_sent"
            )[:50],
            "aujourdhui": dt.date.today().isoformat(),
            "error": erreur,
        },
    )


# --------------------------------------------------------------------------
# Ordres de virement (BNK-4)
# --------------------------------------------------------------------------


def _dettes_ouvertes(tenant) -> list[AccMoveLine]:
    """Les dettes fournisseur qu'un ordre peut régler.

    Mêmes critères que le lettrage : une ligne de dette PUBLIÉE et non
    encore lettrée. Proposer autre chose composerait un ordre qui règle une
    pièce déjà soldée."""
    return list(
        AccMoveLine.objects.filter(
            account__type=AccAccount.TYPE_PAYABLE,
            move__state=AccMove.STATE_POSTED,
            matching_number="",
        ).select_related("move", "account")[:200]
    )


@login_required
@screen_permission("accounting.view_acctransferorder")
def transfer_order_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_acctransferorder")
        if refus is not None:
            return refus
        try:
            choisies = request.POST.getlist("move_line_ids")
            lignes_source = [
                ligne for ligne in _dettes_ouvertes(tenant) if str(ligne.id) in set(choisies)
            ]
            if not lignes_source:
                raise ValidationError(
                    _("Aucune dette sélectionnée : un ordre de virement règle des pièces.")
                )
            noms = get_partner_display_names({ligne.partner_id for ligne in lignes_source})
            ordre = create_transfer_order(
                tenant,
                bank_account=get_object_or_404(
                    AccAccount, id=request.POST.get("bank_account_id"), tenant=tenant
                ),
                execution_date=_date(request.POST.get("execution_date")),
                lines=[
                    {
                        "document_type": TYPE_PIECE_REGLEE,
                        "document_id": str(ligne.id),
                        "beneficiary_label": noms.get(str(ligne.partner_id), "") or ligne.label,
                        "beneficiary_account": "",
                        "amount": ligne.credit - ligne.debit,
                        "reference": ligne.move.reference,
                    }
                    for ligne in lignes_source
                ],
            )
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:transfer_order_detail", order_id=ordre.id)

    dettes = _dettes_ouvertes(tenant)
    noms = get_partner_display_names({ligne.partner_id for ligne in dettes})
    for ligne in dettes:
        ligne.partner_display = noms.get(str(ligne.partner_id), "")
        ligne.montant_du = ligne.credit - ligne.debit

    return smart_table_response(
        request,
        table_key="accounting.transfer_orders",
        columns=TRANSFER_ORDER_COLUMNS,
        queryset=AccTransferOrder.objects.filter(tenant=tenant),
        page_template="accounting/transfer_orders.html",
        page_context={
            "row_url_name": "accounting:transfer_order_detail",
            "en_vol": orders_in_flight(tenant),
            "dettes": dettes,
            "comptes_bancaires": AccAccount.objects.filter(
                tenant=tenant, is_active=True, type=AccAccount.TYPE_BANK
            ).order_by("code"),
            "error": erreur,
        },
    )


@login_required
@screen_permission("accounting.view_acctransferorder")
def transfer_order_detail(request: HttpRequest, order_id: Any) -> HttpResponse:
    tenant = resolve_tenant(request)
    ordre = get_object_or_404(AccTransferOrder, id=order_id, tenant=tenant)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_acctransferorder")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "export":
                contenu = export_transfer_order(ordre)
                reponse = HttpResponse(contenu, content_type="text/csv")
                nom = ordre.reference or str(ordre.id)
                reponse["Content-Disposition"] = f'attachment; filename="{nom}.csv"'
                return reponse
            if action == "remit":
                mark_remitted(ordre)
            elif action == "reconcile":
                reconcile_transfer_order(
                    ordre,
                    get_object_or_404(
                        AccBankStatementLine, id=request.POST.get("statement_line_id")
                    ),
                )
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:transfer_order_detail", order_id=ordre.id)

    return render(
        request,
        "accounting/transfer_order_detail.html",
        {
            "ordre": ordre,
            "lignes": ordre.lines.all().order_by("beneficiary_label"),
            # Seuls les débits du compte de l'ordre, non encore rapprochés :
            # le service refuse tout le reste, l'écran ne le propose donc pas.
            "debits": AccBankStatementLine.objects.filter(
                bank_account=ordre.bank_account,
                direction=AccBankStatementLine.DIRECTION_OUT,
            ).order_by("-statement_date")[:100],
            "error": erreur,
        },
    )


# --------------------------------------------------------------------------
# Échéancier fiscal
# --------------------------------------------------------------------------


@login_required
@screen_permission("accounting.view_acctaxcalendar")
def tax_calendar_screen(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.add_acctaxcalendar")
        if refus is not None:
            return refus
        action = request.POST.get("action", "create")
        try:
            if action == "seed":
                seed_default_tax_calendar(tenant)
            else:
                entree = create_tax_calendar_entry(
                    tenant=tenant,
                    declaration_type=request.POST.get("declaration_type", ""),
                    label=request.POST.get("label", ""),
                    due_date=_date(request.POST.get("due_date")),
                    periodicity=request.POST.get("periodicity", ""),
                )
                # **Une échéance enregistrée doit se voir, ou se dire.**
                # `upcoming_deadlines` écarte les dates passées : une saisie
                # rétrospective était donc enregistrée puis DISPARAISSAIT de
                # l'écran sans un mot — l'utilisateur croit avoir raté son
                # enregistrement et recommence. C'est la perte silencieuse
                # que ce chantier retire partout où il la trouve.
                return redirect(f"{request.path}?created={entree.id}")
        except ValidationError as exc:
            erreur = _messages(exc)
        else:
            return redirect("accounting:tax_calendar")

    horizon = request.GET.get("within_days", "90")
    try:
        jours = max(1, min(int(horizon), 730))
    except (TypeError, ValueError):
        jours = 90

    echeances = upcoming_deadlines(tenant, within_days=jours)
    creee = request.GET.get("created", "")
    hors_horizon = bool(creee) and all(str(e.id) != creee for e in echeances)

    return render(
        request,
        "accounting/tax_calendar.html",
        {
            "echeances": echeances,
            "jours": jours,
            "hors_horizon": hors_horizon,
            "types": AccTaxCalendar.DECLARATION_TYPE_CHOICES,
            "periodicites": AccTaxCalendar.PERIODICITY_CHOICES,
            "error": erreur,
        },
    )


# --------------------------------------------------------------------------
# Relevés de monnaie électronique
# --------------------------------------------------------------------------


@login_required
@screen_permission("accounting.view_accmobilemoneystatementline")
def mobile_money_screen(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    erreur = ""
    charge = 0

    if request.method == "POST":
        refus = screen_forbidden(request, "accounting.change_accmobilemoneystatementline")
        if refus is not None:
            return refus
        action = request.POST.get("action", "")
        try:
            if action == "import":
                fichier = request.FILES.get("statement")
                if fichier is None:
                    raise ValidationError(_("Aucun fichier de relevé fourni."))
                charge = len(import_mobile_money_statement(tenant, fichier.read()))
            elif action == "reconcile":
                reconcile_mobile_money_line(
                    get_object_or_404(
                        AccMobileMoneyStatementLine, id=request.POST.get("line_id"), tenant=tenant
                    ),
                    get_object_or_404(AccPayment, id=request.POST.get("payment_id"), tenant=tenant),
                )
            else:
                raise ValidationError(_("Action inconnue : %(a)s") % {"a": action})
        except (ValidationError, UnicodeDecodeError) as exc:
            erreur = _messages(exc) if isinstance(exc, ValidationError) else str(exc)
        else:
            if action != "import":
                return redirect("accounting:mobile_money")

    return render(
        request,
        "accounting/mobile_money.html",
        {
            "lignes": unmatched_mobile_money_lines(tenant),
            "reglements": AccPayment.objects.filter(
                tenant=tenant, method=AccPayment.METHOD_MOBILE_MONEY
            ).order_by("-date")[:100],
            "charge": charge,
            "error": erreur,
        },
    )
