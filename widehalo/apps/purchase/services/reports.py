"""Rapports `purchase` (§5.6.5, PU8 — dernier lot de `purchase`) : PUR-BC,
PUR-RFQ, PUR-COMP, PUR-REC, PUR-ENG, PUR-EVAL, PUR-RET, PUR-CRI.

`rows_to_bytes` est une COPIE volontaire du helper identique de
`apps.sales.services.reports`/`apps.mrp.services.reports`/
`apps.patronage.services.reports` (deja duplique par app dans ce projet,
jamais centralise dans `core`, verifie avant d'ecrire ce fichier) — suivre
la convention existante plutot que d'introduire une nouvelle dependance
inter-app pour un utilitaire generique.

Seul PUR-BC (bon de commande, document imprime destine au fournisseur) est
un PDF bilingue — meme patron que `sales.services.reports.
order_confirmation_pdf`/`mrp.services.reports.order_pdf`. Les 6 autres
rapports (PUR-RFQ/PUR-COMP/PUR-REC/PUR-ENG/PUR-EVAL/PUR-RET/PUR-CRI) sont
des exports tabulaires json/csv/xlsx via `rows_to_bytes` — meme choix que
SAL-CA/SAL-MARGE/SAL-RET/SAL-OBJ/SAL-PREV (donnees d'analyse/pilotage,
jamais un document a faire signer par un tiers)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.core.models.tenant import Tenant
from apps.mrp.services.public import list_supplier_evaluations
from apps.purchase.models import PurCri, PurOrder, PurReceiptLine, PurRfq
from apps.purchase.services.rfq import compute_comparison_table


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


def order_pdf(order: PurOrder) -> bytes:
    """PUR-BC — bon de commande PDF bilingue, meme patron que
    `sales.services.reports.order_confirmation_pdf`/`mrp.services.reports.
    order_pdf`."""
    from weasyprint import HTML

    lines_html = "".join(
        f"<tr><td>{line.description}</td><td>{line.qty}</td><td>{line.unit_price_mga}</td>"
        f"<td>{line.subtotal_mga}</td></tr>"
        for line in order.lines.all()
    )
    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Bon de commande / Purchase order {order.reference}</h1>
      <p>Fournisseur / Supplier : {order.partner_id}</p>
      <p>Date : {order.date}</p>
      <p>Statut / State : {order.get_state_display()}</p>
      <p>Origine / Origin : {order.get_origin_display()}</p>
      <table border="1" cellspacing="0" cellpadding="4">
        <thead><tr><th>Description</th><th>Qte / Qty</th><th>Prix unitaire / Unit price</th>
        <th>Sous-total / Subtotal</th></tr></thead>
        <tbody>{lines_html}</tbody>
      </table>
      <p>Total / Total : {order.amount_total_mga} {order.currency}</p>
    </body></html>
    """
    result: bytes = HTML(string=html).write_pdf()
    return result


def rfq_rows(rfq: PurRfq) -> list[dict[str, Any]]:
    """PUR-RFQ — contenu de l'appel d'offres : une ligne par ligne d'appel
    d'offres, avec le nombre de fournisseurs consultes/reponses recues en
    rappel (identiques sur chaque ligne, la granularite reelle de l'appel
    d'offres est la ligne d'article, pas le fournisseur — le detail par
    fournisseur/reponse est couvert separement par PUR-COMP)."""
    suppliers_count = rfq.suppliers.count()
    responses_count = rfq.responses.count()
    return [
        {
            "variant_id": str(line.variant_id),
            "description": line.description,
            "qty": line.qty,
            "uom": line.uom,
            "suppliers_consulted": suppliers_count,
            "responses_received": responses_count,
        }
        for line in rfq.lines.all()
    ]


def rfq_comparison_rows(rfq: PurRfq) -> list[dict[str, Any]]:
    """PUR-COMP — tableau comparatif pondere, simple mise a plat tabulaire
    de `services/rfq.py::compute_comparison_table` (deja calcule, PU3+PU4)
    — aucun nouveau calcul ici."""
    rows = compute_comparison_table(rfq)
    return [
        {
            "response_id": str(row["response_id"]),
            "partner_id": str(row["partner_id"]),
            "total_mga": row["total_mga"],
            "lead_time_days": row["lead_time_days"],
            "validity_date": row["validity_date"],
            "score": row["score"],
        }
        for row in rows
    ]


def reception_rows(order: PurOrder) -> list[dict[str, Any]]:
    """PUR-REC — bon de reception : regroupe les `PurReceiptLine` de TOUTES
    les lignes de `order` par date de reception, exactement comme annonce
    par la docstring de deviation PU5 (`services/receiving.py::
    PurReceiptLine`, "un futur PU8 PDF report peut grouper PurReceiptLine
    par order_line__order et par date sans en-tete persistant") — SANS
    creer de modele `PurReceipt` (toujours aucun a ce stade, cf. cette
    meme docstring). Format tabulaire (pas un PDF, cf. docstring de module)
    : chaque ligne du rapport est UN `PurReceiptLine`, tri par date puis
    par ligne de commande — le regroupement visuel par date reste a la
    charge du gabarit d'affichage (`purchase/reports.html`) ou du tableur
    genere (une colonne `date` explicite permet un tri/regroupement cote
    tableur sans perte d'information)."""
    receipt_lines = (
        PurReceiptLine.objects.filter(order_line__order=order)
        .select_related("order_line")
        .order_by("created_at")
    )
    return [
        {
            "date": receipt_line.created_at.date(),
            "order_line_id": str(receipt_line.order_line_id),
            "description": receipt_line.order_line.description,
            "qty_received": receipt_line.qty_received,
            "quality_status": receipt_line.quality_status,
            "notes": receipt_line.notes,
        }
        for receipt_line in receipt_lines
    ]


# Etats "clos" d'une `PurOrder` (RG generique, cf. docstring `PUR-ENG`
# ci-dessous) : jamais un engagement/echeance encore ouvert des lors que la
# commande est cloturee ou annulee.
_CLOSED_ORDER_STATES = (PurOrder.STATE_CLOSED, PurOrder.STATE_CANCELLED)

# Etats "solde" (RG PUR-RET, en plus des etats clos ci-dessus) : une
# commande deja recue/facturee n'est plus "en retard" au sens livraison,
# meme si `date_expected` est depassee — seul un retard de LIVRAISON est
# suivi ici (pas un retard de facturation, hors perimetre de ce rapport).
_DELIVERED_OR_CLOSED_ORDER_STATES = (
    PurOrder.STATE_RECEIVED,
    PurOrder.STATE_INVOICED,
    PurOrder.STATE_CLOSED,
    PurOrder.STATE_CANCELLED,
)


def engagements_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """PUR-ENG — engagements et echeancier fournisseurs : `PurOrder`
    encore ouvertes (etat hors `closed`/`cancelled`, RG-PUR-ENG assumee et
    documentee — une commande deja recue/facturee reste un engagement
    financier reel tant qu'elle n'est pas cloturee/annulee, a la
    difference de PUR-RET ci-dessous qui suit un retard de LIVRAISON),
    groupees par fournisseur, avec le montant total et l'echeance prevue.
    Simple agregation des donnees `PurOrder` deja tracees — aucun nouveau
    champ invente (cf. consigne PU8)."""
    orders = PurOrder.objects.filter(tenant=tenant, is_active=True).exclude(
        state__in=_CLOSED_ORDER_STATES
    )
    rows: list[dict[str, Any]] = [
        {
            "partner_id": str(order.partner_id),
            "reference": order.reference,
            "state": order.state,
            "amount_total_mga": order.amount_total_mga,
            "date_expected": order.date_expected,
        }
        for order in orders
    ]
    rows.sort(key=lambda row: (row["partner_id"], row["date_expected"] or dt.date.max))
    return rows


def late_orders_rows(tenant: Tenant) -> list[dict[str, Any]]:
    """PUR-RET — commandes en retard : `date_expected` depassee et pas
    encore soldee (`received`/`invoiced`/`closed`/`cancelled` exclus, ce
    sont des issues finales du point de vue livraison — meme discipline
    que `sales.services.reports.late_orders_report`)."""
    today = timezone.now().date()
    orders = PurOrder.objects.filter(
        tenant=tenant, is_active=True, date_expected__lt=today
    ).exclude(state__in=_DELIVERED_OR_CLOSED_ORDER_STATES)
    return [
        {
            "reference": order.reference,
            "partner_id": str(order.partner_id),
            "date_expected": order.date_expected,
            "state": order.state,
            "days_late": (today - order.date_expected).days if order.date_expected else None,
        }
        for order in orders
    ]


def cri_rows(
    tenant: Tenant,
    *,
    state: str = "",
    type: str = "",  # noqa: A002 — coherent avec `PurCri.type`
) -> list[dict[str, Any]]:
    """PUR-CRI — incidents achats, filtrable par etat/type."""
    entries = PurCri.objects.filter(tenant=tenant, is_active=True)
    if state:
        entries = entries.filter(state=state)
    if type:
        entries = entries.filter(type=type)
    return [
        {
            "reference": entry.reference,
            "date": entry.date,
            "type": entry.type,
            "partner_id": str(entry.partner_id),
            "order_reference": entry.order.reference if entry.order is not None else "",
            "description": entry.description,
            "impact": entry.impact,
            "cost_mga": entry.cost_mga,
            "state": entry.state,
        }
        for entry in entries
    ]


def supplier_evaluation_rows(partner_id: UUID) -> list[dict[str, Any]]:
    """PUR-EVAL — evaluations fournisseur, mutualisees MRP-QQCD1 (RG-PUR-8,
    PU7) : simple mise a plat tabulaire de `mrp.services.public.
    list_supplier_evaluations` (deja consomme par l'API `purchase`, cf.
    `apps/purchase/api.py::list_supplier_evaluations_endpoint`)."""
    results = list_supplier_evaluations(partner_id)
    return [
        {
            "date": row["date"],
            "score_quantity": row["score_quantity"],
            "score_quality": row["score_quality"],
            "score_cost": row["score_cost"],
            "score_delay": row["score_delay"],
            "score_conformity": row["score_conformity"],
            "weighted_score": row["weighted_score"],
            "notes": row["notes"],
        }
        for row in results
    ]
