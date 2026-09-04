"""Bloc D, D4 (QUA-4 à QUA-7) : dossier de rappel — met en quarantaine le
lot d'origine ET tous ses descendants, snapshotte la généalogie au moment
de la déclaration (jamais recalculée a posteriori)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.models import QltRecallDossier
from apps.quality.services.recall import close_recall, declare_recall
from apps.stocks.models import StkLot
from apps.stocks.services.genealogy import record_consumption
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="QLT-RCL", name="Quality Recall Tenant")
    with use_tenant(t.id):
        yield t


@pytest.fixture
def user(tenant):
    with use_tenant(tenant.id):
        return User.objects.create_user(email="rappel@example.com", password="Str0ngPassw0rd!23")


def test_declare_recall_holds_origin_lot_and_all_descendants(tenant, user) -> None:
    with use_tenant(tenant.id):
        raw_lot = StkLotFactory(tenant=tenant, name="MP-QLT-001")
        finished_lot = StkLotFactory(tenant=tenant, name="PF-QLT-001")
        record_consumption(
            tenant=tenant,
            parent_lot=raw_lot,
            child_lot=finished_lot,
            qty=Decimal("20"),
            source_document="MRP-OF-QLT-001",
        )

        dossier = declare_recall(
            tenant=tenant,
            lot_variant_id=raw_lot.variant_id,
            lot_name=raw_lot.name,
            reason="Contamination suspectée",
            initiated_by=user,
        )

        assert dossier.state == QltRecallDossier.STATE_OPEN
        assert dossier.reference.startswith("QLT-RECALL-")
        assert {entry["lot_name"] for entry in dossier.impacted_lots} == {
            "MP-QLT-001",
            "PF-QLT-001",
        }
        assert StkLot.objects.get(id=raw_lot.id).is_held() is True
        assert StkLot.objects.get(id=finished_lot.id).is_held() is True


def test_declare_recall_snapshot_is_frozen_after_later_genealogy_changes(tenant, user) -> None:
    with use_tenant(tenant.id):
        raw_lot = StkLotFactory(tenant=tenant, name="MP-QLT-002")
        finished_lot = StkLotFactory(tenant=tenant, name="PF-QLT-002")
        record_consumption(
            tenant=tenant,
            parent_lot=raw_lot,
            child_lot=finished_lot,
            qty=Decimal("10"),
            source_document="MRP-OF-QLT-002",
        )

        dossier = declare_recall(
            tenant=tenant,
            lot_variant_id=raw_lot.variant_id,
            lot_name=raw_lot.name,
            reason="Test snapshot",
            initiated_by=user,
        )
        snapshot_before = dossier.genealogy_snapshot

        # Un nouveau lot est rattaché APRÈS la déclaration — ne doit
        # jamais apparaître dans le snapshot déjà figé.
        second_finished_lot = StkLotFactory(tenant=tenant, name="PF-QLT-002-LATER")
        record_consumption(
            tenant=tenant,
            parent_lot=raw_lot,
            child_lot=second_finished_lot,
            qty=Decimal("5"),
            source_document="MRP-OF-QLT-002-LATER",
        )

        dossier.refresh_from_db()
        assert dossier.genealogy_snapshot == snapshot_before
        assert "PF-QLT-002-LATER" not in {entry["lot_name"] for entry in dossier.impacted_lots}


def test_declare_recall_requires_reason(tenant, user) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, name="LOT-QLT-NOREASON")
        with pytest.raises(ValidationError):
            declare_recall(
                tenant=tenant,
                lot_variant_id=lot.variant_id,
                lot_name=lot.name,
                reason="",
                initiated_by=user,
            )


def test_declare_recall_refuses_unknown_lot(tenant, user) -> None:
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        declare_recall(
            tenant=tenant,
            lot_variant_id=uuid.uuid4(),
            lot_name="LOT-INCONNU",
            reason="Test",
            initiated_by=user,
        )


def test_close_recall_requires_reason_and_does_not_release_quarantine(tenant, user) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, name="LOT-QLT-CLOSE")
        dossier = declare_recall(
            tenant=tenant,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            reason="Test clôture",
            initiated_by=user,
        )

        with pytest.raises(ValidationError):
            close_recall(dossier, closed_by=user, closing_reason="")

        close_recall(dossier, closed_by=user, closing_reason="Analyse terminée, sans suite")
        dossier.refresh_from_db()

        assert dossier.state == QltRecallDossier.STATE_CLOSED
        assert dossier.closed_by == user
        assert dossier.closed_at is not None
        assert StkLot.objects.get(id=lot.id).is_held() is True


def test_close_recall_refuses_double_close(tenant, user) -> None:
    with use_tenant(tenant.id):
        lot = StkLotFactory(tenant=tenant, name="LOT-QLT-DOUBLE-CLOSE")
        dossier = declare_recall(
            tenant=tenant,
            lot_variant_id=lot.variant_id,
            lot_name=lot.name,
            reason="Test",
            initiated_by=user,
        )
        close_recall(dossier, closed_by=user, closing_reason="Corrigé")
        with pytest.raises(ValidationError):
            close_recall(dossier, closed_by=user, closing_reason="Deuxième tentative")
