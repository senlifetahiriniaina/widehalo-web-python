"""Appel d'offres (RG-PUR-4, §5.6.3, PU3+PU4 du sous-sequencement `purchase`
— cf. plan) : creation, envoi a N fournisseurs, enregistrement des
reponses, tableau comparatif pondere, et attribution — qui genere une vraie
`PurOrder` via `services/orders.py` (jamais un modele provisoire, cf. la
note de fusion PU3+PU4 du plan)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.purchase.models import (
    PurOrder,
    PurRfq,
    PurRfqLine,
    PurRfqResponse,
    PurRfqResponseLine,
    PurRfqSupplier,
)
from apps.purchase.services.orders import add_order_line, create_order


def create_rfq(
    *,
    tenant: Tenant,
    date: dt.date,
    deadline: dt.date | None = None,
    award_criteria: dict[str, float] | None = None,
) -> PurRfq:
    reference = next_reference(tenant, "PRFQ", timezone.now().year)
    kwargs = {}
    if award_criteria is not None:
        kwargs["award_criteria"] = award_criteria
    return PurRfq.objects.create(
        tenant=tenant, reference=reference, date=date, deadline=deadline, **kwargs
    )


def add_rfq_line(
    rfq: PurRfq, *, variant_id: UUID, description: str, qty: Decimal, uom: str = ""
) -> PurRfqLine:
    return PurRfqLine.objects.create(
        tenant=rfq.tenant, rfq=rfq, variant_id=variant_id, description=description, qty=qty, uom=uom
    )


def add_rfq_supplier(rfq: PurRfq, *, partner_id: UUID) -> PurRfqSupplier:
    return PurRfqSupplier.objects.create(tenant=rfq.tenant, rfq=rfq, partner_id=partner_id)


def send_rfq(rfq: PurRfq) -> PurRfq:
    """Refuse un envoi sans fournisseur consulte ou sans ligne — un appel
    d'offres vide n'a aucun sens metier (rien a comparer, aucune reponse
    possible)."""
    if rfq.state != PurRfq.STATE_DRAFT:
        raise ValidationError(_("Seul un appel d'offres en brouillon peut être envoyé."))
    if not rfq.suppliers.exists():
        raise ValidationError(
            _("Un appel d'offres sans fournisseur consulte ne peut pas être envoyé.")
        )
    if not rfq.lines.exists():
        raise ValidationError(_("Un appel d'offres sans ligne ne peut pas être envoyé."))
    rfq.state = PurRfq.STATE_SENT
    rfq.save(update_fields=["state"])
    return rfq


def record_rfq_response(
    rfq: PurRfq,
    *,
    partner_id: UUID,
    date_received: dt.date,
    lines: list[dict[str, Any]],
    currency: str = "MGA",
    lead_time_days: int = 0,
    validity_date: dt.date | None = None,
) -> PurRfqResponse:
    """`lines` : liste de {"variant_id": UUID, "qty": Decimal,
    "unit_price_mga": Decimal}. `total_mga` est calcule (jamais saisi) a
    partir des lignes, pour rester coherent avec le detail enregistre."""
    if rfq.state != PurRfq.STATE_SENT:
        raise ValidationError(
            _("Une réponse ne peut être enregistrée que pour un appel d'offres envoyé.")
        )

    total_mga = sum(
        (Decimal(line["qty"]) * Decimal(line["unit_price_mga"]) for line in lines), Decimal(0)
    )
    response = PurRfqResponse.objects.create(
        tenant=rfq.tenant,
        rfq=rfq,
        partner_id=partner_id,
        date_received=date_received,
        total_mga=total_mga,
        currency=currency,
        lead_time_days=lead_time_days,
        validity_date=validity_date,
    )
    for line in lines:
        PurRfqResponseLine.objects.create(
            tenant=rfq.tenant,
            response=response,
            variant_id=line["variant_id"],
            qty=line["qty"],
            unit_price_mga=line["unit_price_mga"],
        )
    return response


def compute_comparison_table(rfq: PurRfq) -> list[dict[str, Any]]:
    """RG-PUR-4 : tableau comparatif pondere par `rfq.award_criteria`
    (`price`/`delay`/`quality`). Normalisation "part du maximum observe"
    pour `price` (`total_mga`) et `delay` (`lead_time_days`) : chaque
    critere est ramene entre 0 (le moins cher/le plus rapide) et 1 (le plus
    cher/le plus lent), plus bas est toujours meilleur. `quality` n'a
    aucune source numerique dans ce modele (aucune evaluation fournisseur
    n'est rattachee a une reponse d'appel d'offres a ce stade — gap
    identifie pour un futur lot, cf. RG-PUR-8/`mrp.MrpSupplierEvaluation`
    mutualise) : sa valeur normalisee est fixee a une constante neutre
    (0.5) IDENTIQUE pour toutes les reponses, jamais une donnee inventee —
    elle ne change donc jamais le classement relatif, seulement le score
    absolu affiche. Le score final (plus bas = meilleur) est stocke sur
    chaque `PurRfqResponse.score`. Retourne la liste triee du meilleur au
    moins bon."""
    responses = list(rfq.responses.all())
    if not responses:
        return []

    criteria = rfq.award_criteria or {}
    price_weight = Decimal(str(criteria.get("price", 0)))
    delay_weight = Decimal(str(criteria.get("delay", 0)))
    quality_weight = Decimal(str(criteria.get("quality", 0)))
    neutral_quality = Decimal("0.5")

    max_price = max((r.total_mga for r in responses), default=Decimal(0)) or Decimal(1)
    max_delay = max((r.lead_time_days for r in responses), default=0) or 1

    rows: list[dict[str, Any]] = []
    for response in responses:
        normalized_price = response.total_mga / max_price
        normalized_delay = Decimal(response.lead_time_days) / Decimal(max_delay)
        score = (
            price_weight * normalized_price
            + delay_weight * normalized_delay
            + quality_weight * neutral_quality
        ).quantize(Decimal("0.0001"))
        response.score = score
        response.save(update_fields=["score"])
        rows.append(
            {
                "response_id": response.id,
                "partner_id": response.partner_id,
                "total_mga": response.total_mga,
                "lead_time_days": response.lead_time_days,
                "validity_date": response.validity_date,
                "score": score,
            }
        )

    rows.sort(key=lambda row: Decimal(row["score"]))
    return rows


def award_rfq(rfq: PurRfq, response: PurRfqResponse, *, awarded_by: User) -> PurOrder:
    """Genere une vraie `PurOrder` a partir des lignes de la reponse
    gagnante — `response` est un argument explicite obligatoire : jamais de
    selection automatique "le moins cher gagne" (le CDC decrit
    l'attribution comme une decision humaine s'appuyant sur le tableau
    comparatif, pas un automatisme, cf. plan)."""
    if rfq.state != PurRfq.STATE_SENT:
        raise ValidationError(_("Seul un appel d'offres envoyé peut être attribue."))
    if response.rfq_id != rfq.id:
        raise ValidationError(_("Cette réponse n'appartient pas a cet appel d'offres."))

    rfq_lines_by_variant = {line.variant_id: line for line in rfq.lines.all()}

    order = create_order(
        tenant=rfq.tenant,
        partner_id=response.partner_id,
        date=timezone.now().date(),
        rfq=rfq,
    )
    for line in response.lines.all():
        matched = rfq_lines_by_variant.get(line.variant_id)
        add_order_line(
            order,
            variant_id=line.variant_id,
            description=matched.description if matched else str(line.variant_id),
            qty=line.qty,
            unit_price_mga=line.unit_price_mga,
            uom=matched.uom if matched else "",
        )

    rfq.state = PurRfq.STATE_AWARDED
    rfq.save(update_fields=["state"])
    return order
