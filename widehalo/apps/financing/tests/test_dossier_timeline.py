"""B2 (Phase 3, "chronologie unifiée CREDOC/import/coût débarqué", cf.
plan) : `services/credoc.py::build_dossier_timeline` — agrégation LECTURE
SEULE croisant `purchase`/`logistics`/`financing`, seul module dont les
dépendances déclarées atteignent les deux autres (cf. `apps/financing/
module.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant
from apps.financing.services.credoc import build_dossier_timeline, create_credoc, open_credoc
from apps.logistics.services.shipments import book_shipment, create_shipment
from apps.logistics.tests.factories import LogCustomsFileFactory
from apps.purchase.services.orders import create_order

pytestmark = pytest.mark.django_db


def test_build_dossier_timeline_aggregates_order_shipment_and_credoc() -> None:
    tenant = Tenant.objects.create(code="FIN-DOSSIER-1", name="Financing Dossier Tenant 1")
    with use_tenant(tenant.id):
        user = UserFactory()
        grant_role(user, "comptable")

        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date(2026, 1, 5))
        credoc = create_credoc(
            tenant,
            purchase_order_id=order.id,
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
        )
        open_credoc(credoc, user, reason="Accord de la banque émettrice reçu")

        shipment = create_shipment(
            tenant, origin="Guangzhou", destination="Toamasina", purchase_order_ids=[order.id]
        )
        book_shipment(shipment, user)

        # Dates de dedouanement PLACEES DANS LE FUTUR par rapport a
        # "aujourd'hui" (LogCustomsFile.opened_at/cleared_at/closed_at sont
        # de simples `date`, pas des `datetime` — un decalage relatif
        # garantit un ordre chronologique deterministe face aux evenements
        # CREDOC/expedition ci-dessus, dates au moment REEL de l'execution
        # du test, quel que soit ce moment).
        today = dt.date.today()
        LogCustomsFileFactory(
            tenant=tenant,
            shipment=shipment,
            opened_at=today + dt.timedelta(days=1),
            cleared_at=today + dt.timedelta(days=10),
            closed_at=today + dt.timedelta(days=15),
            landed_cost_batch_id=uuid.uuid4(),
        )

        dossier = build_dossier_timeline(credoc)

        assert dossier["order"] is not None
        assert dossier["order"]["id"] == order.id
        assert dossier["order"]["reference"] == order.reference

        assert len(dossier["shipments"]) == 1
        assert dossier["shipments"][0]["id"] == shipment.id
        assert len(dossier["shipments"][0]["customs_files"]) == 1

        assert len(dossier["credoc_history"]) == 1
        assert dossier["credoc_history"][0]["reason"] == "Accord de la banque émettrice reçu"

        # 1 credoc cree + 1 transition credoc + 1 transition expedition + 3
        # evenements douaniers (ouvert/dedouane/cloture) = 6, TRIES par date.
        assert len(dossier["events"]) == 6
        sources = [event["source"] for event in dossier["events"]]
        assert sources == ["credoc", "credoc", "shipment", "customs", "customs", "customs"]
        assert "coût débarqué appliqué" in dossier["events"][-1]["label"]


def test_build_dossier_timeline_handles_missing_order_and_no_shipments() -> None:
    """Gap de configuration a la charge du tenant, meme discipline que le
    reste du depot : un `purchase_order_id` opaque (ex. saisi a la main,
    sans commande reelle correspondante) ne fait jamais lever d'exception —
    seule la section "commande" reste vide."""
    tenant = Tenant.objects.create(code="FIN-DOSSIER-2", name="Financing Dossier Tenant 2")
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("10000000"),
            validity_date=dt.date(2026, 12, 31),
        )

        dossier = build_dossier_timeline(credoc)

        assert dossier["order"] is None
        assert dossier["shipments"] == []
        assert dossier["credoc_history"] == []
        assert len(dossier["events"]) == 1
        assert dossier["events"][0]["source"] == "credoc"
