"""Rapports `sales` (§5.5.7, S7) : SAL-DEVIS, SAL-BC, SAL-CA, SAL-MARGE,
SAL-RET, SAL-OBJ, SAL-BL (minimal), SAL-PREV. SAL-FAC ("cf. Accounting")
n'a pas de generateur ici : c'est un simple lien vers l'ecran de facture
deja existant du module `accounting` (cf. `templates/sales/reports.html`),
aucune duplication de generation de PDF.

`rows_to_bytes` est une COPIE volontaire du helper identique de
`apps.mrp.services.reports`/`apps.patronage.services.reports` (verifie
avant d'ecrire ce fichier : la fonction est deja dupliquee par app dans ce
projet, jamais centralisee dans `core`) — suivre la convention existante
plutot que d'introduire une nouvelle dependance inter-app pour un
utilitaire generique."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.sales.models import (
    SalesForecast,
    SalesOrder,
    SalesOrderLine,
    SalesQuotation,
    SalesTarget,
)

# RG-SAL-5 : memes roles que `apps.core.services.permissions.
# SENSITIVE_FIELDS["sales.SalesOrderLine"]["margin_pct"]` — le rapport
# SAL-MARGE doit respecter le meme masquage que l'ecran/l'API.
_MARGIN_VISIBLE_ROLES = {"direction", "admin", "resp_commercial"}


def rows_to_bytes(rows: list[dict[str, Any]], fields: list[str], *, format: str = "json") -> bytes:
    if format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, default=str).encode("utf-8")

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(fields)
        for row in rows:
            sheet.append([row.get(field) for field in fields])
        buffer_bytes = io.BytesIO()
        workbook.save(buffer_bytes)
        return buffer_bytes.getvalue()

    raise ValueError(f"Format d'export non supporte : {format}")


def quotation_pdf(quotation: SalesQuotation) -> bytes:
    """SAL-DEVIS — migre du HTML inline historique (Lot 2) vers le gabarit
    partage `templates/reports/_base.html` (RPT-3, meme patron que
    `delivery_note_pdf` ci-dessous) pour le chantier "marque d'entreprise
    sur le PDF devis/commande" : injecte desormais `tenant`/
    `tenant_logo_data_uri` au contexte, ce qui fait automatiquement
    apparaitre le logo/nom/adresse en en-tete et les coordonnees en pied de
    page (rendus par `_base.html`, jamais recalcules ici). Regression
    visuelle assumee et documentee (cf. plan) : le PDF change d'apparence,
    memes donnees deja rendues (reference, partenaire, lignes, totaux)."""
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from apps.core.services.branding import get_tenant_logo_data_uri

    html = render_to_string(
        "reports/legal/quotation.html",
        {
            "quotation": quotation,
            "tenant": quotation.tenant,
            "tenant_logo_data_uri": get_tenant_logo_data_uri(quotation.tenant),
        },
    )
    result: bytes = HTML(string=html).write_pdf()
    return result


def order_confirmation_pdf(order: SalesOrder) -> bytes:
    """SAL-BC — meme migration que `quotation_pdf` ci-dessus."""
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from apps.core.services.branding import get_tenant_logo_data_uri

    html = render_to_string(
        "reports/legal/order_confirmation.html",
        {
            "order": order,
            "tenant": order.tenant,
            "tenant_logo_data_uri": get_tenant_logo_data_uri(order.tenant),
        },
    )
    result: bytes = HTML(string=html).write_pdf()
    return result


def delivery_note_rows(order: SalesOrder) -> list[dict[str, Any]]:
    """SAL-BL — bon de livraison, portee MINIMALE assumee (documentee) : se
    contente de lister les lignes de la commande avec ce qui est deja livre,
    suffisant pour un accuse de reception papier basique.

    **Correction L15** : cette docstring affirmait « `apps.stocks` n'existe
    pas encore » pour justifier l'absence de numero de colis, d'emplacement
    d'entrepot et de transporteur. Le module existe depuis la Phase 3, et
    `apps.logistics` porte meme les transporteurs. La portee reste minimale,
    mais c'est desormais un CHOIX et non une contrainte : enrichir ce bon de
    livraison suppose de decider ce qu'un client doit voir d'un mouvement de
    stock interne, et cette decision n'a pas ete prise. La justification
    perimee est retiree parce qu'un motif faux empeche de rouvrir la
    question."""
    return [
        {
            "description": line.description,
            "qty_ordered": line.qty,
            "qty_delivered": line.qty_delivered,
            "uom": line.uom,
        }
        for line in order.lines.all()
    ]


def delivery_note_pdf(order: SalesOrder) -> bytes:
    """SAL-BL, PDF — construit pour RPT-10 (§reporting, REP4) : `sales`
    n'avait jusqu'ici jamais eu besoin d'un PDF pour le bon de livraison
    (seul `delivery_note_rows` existait, consomme en tabulaire). Contrairement
    a `quotation_pdf`/`order_confirmation_pdf` ci-dessus (HTML inline, patron
    historique du Lot 2), ce nouveau gabarit utilise le fichier de template
    partage `templates/reports/_base.html` (RPT-3 : "les NOUVEAUX gabarits
    de ce module" — la mise en page unifiee s'applique ici, les gabarits
    deja construits par ce module ne sont pas retrofites)."""
    from django.template.loader import render_to_string
    from weasyprint import HTML

    html = render_to_string(
        "reports/legal/delivery_note.html", {"order": order, "lines": delivery_note_rows(order)}
    )
    result: bytes = HTML(string=html).write_pdf()
    return result


def revenue_report(
    *, date_from: dt.date, date_to: dt.date, group_by: str = "partner_id"
) -> list[dict[str, Any]]:
    """SAL-CA — chiffre d'affaires par periode/client/commercial. `group_by`
    parmi "partner_id"/"salesperson"/"date" (le CDC demande aussi "produit"/
    "region" : produit necessiterait de deplier par ligne+resoudre le
    catalogue, region n'existe dans aucun modele `partners` expose — hors
    perimetre documente de cette premiere version du rapport, a etendre
    quand un besoin concret se precise)."""
    valid_group_by = {"partner_id", "salesperson", "date"}
    if group_by not in valid_group_by:
        raise ValueError(f"group_by invalide : {group_by}")

    queryset = SalesOrder.objects.filter(
        date__gte=date_from, date__lte=date_to, is_active=True
    ).exclude(state=SalesOrder.STATE_CANCELLED)

    if group_by == "salesperson":
        rows = (
            queryset.values("salesperson__email")
            .annotate(total_mga=Sum("amount_total_mga"))
            .order_by("-total_mga")
        )
        return [
            {
                "salesperson": row["salesperson__email"] or "-",
                "total_mga": row["total_mga"] or Decimal(0),
            }
            for row in rows
        ]

    group_field = "date" if group_by == "date" else "partner_id"
    rows = (
        queryset.values(group_field)
        .annotate(total_mga=Sum("amount_total_mga"))
        .order_by(f"-{group_field}" if group_by == "date" else "-total_mga")
    )
    return [
        {group_field: str(row[group_field]), "total_mga": row["total_mga"] or Decimal(0)}
        for row in rows
    ]


def margin_report(*, role_codes: set[str]) -> list[dict[str, Any]]:
    """SAL-MARGE — analyse de marge par commande, RG-SAL-5 : ne renvoie
    JAMAIS `margin_pct`/`cost_estimate_mga` a un role hors
    `_MARGIN_VISIBLE_ROLES` — meme masquage que l'ecran/l'API, applique
    ici directement (pas de dict a filtrer champ par champ, la colonne
    entiere est omise en amont pour ce rapport tabulaire)."""
    can_see_margin = bool(role_codes & _MARGIN_VISIBLE_ROLES)
    lines = SalesOrderLine.objects.filter(is_active=True).select_related("order")
    rows: list[dict[str, Any]] = []
    for line in lines:
        row: dict[str, Any] = {
            "order_reference": line.order.reference,
            "description": line.description,
            "subtotal": line.subtotal,
        }
        if can_see_margin:
            row["margin_pct"] = line.margin_pct
            row["cost_estimate_mga"] = line.cost_estimate_mga
        rows.append(row)
    return rows


def late_orders_report() -> list[dict[str, Any]]:
    """SAL-RET — commandes en retard : `commitment_date` depassee et pas
    encore livrees (`delivered`/`invoiced`/`closed`/`cancelled` exclus,
    ce sont des issues finales, jamais "en retard")."""
    today = dt.date.today()
    final_states = (
        SalesOrder.STATE_DELIVERED,
        SalesOrder.STATE_INVOICED,
        SalesOrder.STATE_CLOSED,
        SalesOrder.STATE_CANCELLED,
    )
    orders = SalesOrder.objects.filter(commitment_date__lt=today, is_active=True).exclude(
        state__in=final_states
    )
    return [
        {
            "reference": order.reference,
            "partner_id": str(order.partner_id),
            "commitment_date": order.commitment_date,
            "state": order.state,
            "days_late": (today - order.commitment_date).days if order.commitment_date else None,
        }
        for order in orders
    ]


def target_achievement_report(*, period: str) -> list[dict[str, Any]]:
    """SAL-OBJ — realisation des objectifs commerciaux vs `SalesTarget`.
    Le realise est approxime par la somme de `amount_total_mga` des
    commandes NON annulees de la periode (bucket mensuel "YYYY-MM" compare
    au prefixe de `SalesOrder.date`) — pas de notion de "commande
    realisee" plus fine que celle-ci dans ce lot."""
    year, month = (int(part) for part in period.split("-"))
    orders_total = SalesOrder.objects.filter(
        date__year=year, date__month=month, is_active=True
    ).exclude(state=SalesOrder.STATE_CANCELLED).aggregate(total=Sum("amount_total_mga"))[
        "total"
    ] or Decimal(0)
    targets = SalesTarget.objects.filter(period=period, is_active=True)
    rows: list[dict[str, Any]] = []
    for target in targets:
        achievement_pct = (
            (orders_total / target.amount_mga * Decimal(100)) if target.amount_mga else Decimal(0)
        )
        rows.append(
            {
                "scope": target.scope,
                "scope_ref": str(target.scope_ref) if target.scope_ref else "",
                "target_mga": target.amount_mga,
                "realized_mga": orders_total,
                "achievement_pct": achievement_pct,
            }
        )
    return rows


def forecast_rows(*, date_from: str, date_to: str) -> list[dict[str, Any]]:
    """SAL-PREV — previsions/ecarts (`SalesForecast`, deja calculees par
    `services.forecast.build_forecast`/`recompute_forecasts_for_period` en
    S6) : simple mise a plat tabulaire, aucun nouveau calcul ici."""
    forecasts = SalesForecast.objects.filter(
        period__gte=date_from, period__lte=date_to, is_active=True
    ).order_by("period", "variant_id")
    return [
        {
            "period": forecast.period,
            "variant_id": str(forecast.variant_id),
            "partner_id": str(forecast.partner_id) if forecast.partner_id else "",
            "qty_forecast": forecast.qty_forecast,
            "qty_actual": forecast.qty_actual,
            "confidence": forecast.confidence,
            "method": forecast.method,
        }
        for forecast in forecasts
    ]
