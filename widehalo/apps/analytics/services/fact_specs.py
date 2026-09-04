"""Table de correspondance {fait -> champs agrégeables/exposables} — usage
INTERNE à `analytics` (jamais importé par un autre module, règle de
couplage n°1 : `apps.bi`, seul consommateur à ce jour, passe exclusivement
par `services/public.py::aggregate_fact`/`detail_fact`, qui référencent ce
module en interne).

Chaque code d'axe abstrait ("temps", "tiers", "article"...) est le SEUL
vocabulaire qu'un appelant externe peut fournir — sa traduction en lookup
Django réel (`dimension_fields` ci-dessous) reste figée dans le code, hors
d'atteinte de toute donnée stockée en base (même discipline de sécurité
que documentée dans `apps.bi.services.metric_computers`, qui consommait
directement ces specs avant que `test_module_boundaries` ne signale la
violation de couplage — corrigé en les rapatriant ici)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

from apps.analytics.models import (
    AnFactEcriture,
    AnFactEncaissement,
    AnFactMouvementStock,
    AnFactOrdreFabrication,
    AnFactReception,
    AnFactTicketPos,
    AnFactVente,
)


@dataclass(frozen=True)
class FactSpec:
    queryset_factory: Callable[[Any], QuerySet[Any]]
    value_field: str
    dimension_fields: dict[str, str]
    detail_extra_fields: tuple[str, ...] = ()


FACT_SPECS: dict[str, FactSpec] = {
    "vente": FactSpec(
        queryset_factory=lambda tenant: AnFactVente.objects.filter(tenant=tenant),
        value_field="montant_ht_mga",
        dimension_fields={
            "temps": "dim_temps__date",
            "tiers": "dim_tiers__nom",
            "article": "dim_article__libelle",
        },
        detail_extra_fields=("order_reference", "qty", "unit_price_mga"),
    ),
    "ticket_pos": FactSpec(
        queryset_factory=lambda tenant: AnFactTicketPos.objects.filter(tenant=tenant),
        value_field="montant_ttc_mga",
        dimension_fields={
            "temps": "dim_temps__date",
            "tiers": "dim_tiers__nom",
            "article": "dim_article__libelle",
            "point_vente": "point_vente_code",
        },
        detail_extra_fields=("ticket_number", "qty", "unit_price_mga"),
    ),
    "encaissement": FactSpec(
        queryset_factory=lambda tenant: AnFactEncaissement.objects.filter(
            tenant=tenant, direction="inbound"
        ),
        value_field="montant_mga",
        dimension_fields={"temps": "dim_temps__date", "tiers": "dim_tiers__nom"},
        detail_extra_fields=("reference", "method"),
    ),
    "ecriture": FactSpec(
        queryset_factory=lambda tenant: AnFactEcriture.objects.filter(tenant=tenant),
        value_field="solde_mga",
        dimension_fields={
            "temps": "dim_temps__date",
            "tiers": "dim_tiers__nom",
            "compte": "compte_code",
        },
        detail_extra_fields=("move_reference", "debit_mga", "credit_mga"),
    ),
    "mouvement_stock": FactSpec(
        queryset_factory=lambda tenant: AnFactMouvementStock.objects.filter(tenant=tenant),
        value_field="value_mga",
        dimension_fields={
            "temps": "dim_temps__date",
            "article": "dim_article__libelle",
            "nature": "move_type",
            "entrepot_origine": "entrepot_origine_code",
            "entrepot_destination": "entrepot_destination_code",
        },
        detail_extra_fields=("move_reference", "qty", "unit_cost_mga"),
    ),
    "reception": FactSpec(
        queryset_factory=lambda tenant: AnFactReception.objects.filter(tenant=tenant),
        value_field="qty_received",
        dimension_fields={
            "temps": "dim_temps__date",
            "tiers": "dim_tiers__nom",
            "article": "dim_article__libelle",
        },
        detail_extra_fields=(
            "order_reference",
            "unit_price_mga",
            "cout_debarque_unitaire_mga",
            "quality_status",
        ),
    ),
    "ordre_fabrication": FactSpec(
        queryset_factory=lambda tenant: AnFactOrdreFabrication.objects.filter(tenant=tenant),
        value_field="ecart_cout_mga",
        dimension_fields={
            "temps": "dim_temps__date",
            "article": "dim_article__libelle",
            "atelier": "atelier_code",
        },
        detail_extra_fields=(
            "order_reference",
            "qty_produced",
            "cout_reel_mga",
            "cout_planifie_mga",
        ),
    ),
}
