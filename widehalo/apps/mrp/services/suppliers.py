"""MRP-QQCD1 (evaluation fournisseur ponderee) et MRP-ECH1 (demande
d'echantillon) — enrichissements WideHalo adoptes en V1."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from apps.core.models.tenant import Tenant
from apps.mrp.models import MrpSampleRequest, MrpSupplierEvaluation

MAX_SCORE = Decimal(5)


def evaluate_supplier(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    score_quantity: Decimal,
    score_quality: Decimal,
    score_cost: Decimal,
    score_delay: Decimal,
    score_conformity: Decimal,
    component_template_id: UUID | None = None,
    weight_quantity: int = MrpSupplierEvaluation.DEFAULT_WEIGHT_QUANTITY,
    weight_quality: int = MrpSupplierEvaluation.DEFAULT_WEIGHT_QUALITY,
    weight_cost: int = MrpSupplierEvaluation.DEFAULT_WEIGHT_COST,
    weight_delay: int = MrpSupplierEvaluation.DEFAULT_WEIGHT_DELAY,
    weight_conformity: int = MrpSupplierEvaluation.DEFAULT_WEIGHT_CONFORMITY,
    conformity_blocking: bool = False,
    notes: str = "",
) -> MrpSupplierEvaluation:
    """Note ponderee sur 100, ramenee a une echelle de notes /5. Le critere
    de conformite est BLOQUANT si une certification obligatoire manque ou
    est expiree (`conformity_blocking=True`) — le score reste calcule pour
    tracabilite, mais l'appelant doit refuser l'approvisionnement dans ce
    cas (cf. `is_blocked` sur l'objet retourne, pas un champ mais une regle
    de lecture simple)."""
    # Chaque note est sur 5, chaque poids est un pourcentage (somme = 100
    # par defaut) : la note ponderee resultante est deja sur 100.
    weighted = (
        score_quantity * weight_quantity
        + score_quality * weight_quality
        + score_cost * weight_cost
        + score_delay * weight_delay
        + score_conformity * weight_conformity
    ) / MAX_SCORE

    return MrpSupplierEvaluation.objects.create(
        tenant=tenant,
        partner_id=partner_id,
        component_template_id=component_template_id,
        date=date,
        score_quantity=score_quantity,
        score_quality=score_quality,
        score_cost=score_cost,
        score_delay=score_delay,
        score_conformity=score_conformity,
        weight_quantity=weight_quantity,
        weight_quality=weight_quality,
        weight_cost=weight_cost,
        weight_delay=weight_delay,
        weight_conformity=weight_conformity,
        conformity_blocking=conformity_blocking,
        weighted_score=weighted,
        notes=notes,
    )


def is_supplier_approved(evaluation: MrpSupplierEvaluation) -> bool:
    """Le critere de conformite est bloquant independamment du score."""
    return not evaluation.conformity_blocking


def request_sample(
    *,
    tenant: Tenant,
    partner_id: UUID,
    component_template_id: UUID,
    date_requested: dt.date,
) -> MrpSampleRequest:
    return MrpSampleRequest.objects.create(
        tenant=tenant,
        partner_id=partner_id,
        component_template_id=component_template_id,
        date_requested=date_requested,
    )


def receive_sample(sample: MrpSampleRequest, *, date_received: dt.date) -> MrpSampleRequest:
    sample.state = MrpSampleRequest.STATE_RECEIVED
    sample.date_received = date_received
    sample.save(update_fields=["state", "date_received"])
    return sample


def decide_sample(sample: MrpSampleRequest, *, approved: bool, notes: str = "") -> MrpSampleRequest:
    sample.state = MrpSampleRequest.STATE_APPROVED if approved else MrpSampleRequest.STATE_REJECTED
    sample.evaluation_notes = notes
    sample.save(update_fields=["state", "evaluation_notes"])
    return sample
