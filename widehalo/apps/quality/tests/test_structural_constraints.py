"""Bloc D, D4 (QUA-6/QUA-7) : trigger d'immutabilité `qlt_recall_dossier`
— patron calqué sur `apps/stocks/tests/test_structural_constraints.py`
(`stk_move`, sprint A5)."""

from __future__ import annotations

import pytest
from django.db import connection, transaction

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.models import QltRecallDossier
from apps.quality.services.recall import close_recall, declare_recall
from apps.stocks.tests.factories import StkLotFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="QLT-SC", name="Quality Structural Constraints Tenant")
    with use_tenant(t.id):
        yield t


@pytest.fixture
def user(tenant):
    with use_tenant(tenant.id):
        return User.objects.create_user(email="sc-qlt@example.com", password="Str0ngPassw0rd!23")


def _declared_dossier(tenant, user):
    lot = StkLotFactory(tenant=tenant, name="LOT-QLT-SC-001")
    return declare_recall(
        tenant=tenant,
        lot_variant_id=lot.variant_id,
        lot_name=lot.name,
        reason="Test structurel",
        initiated_by=user,
    )


def test_recall_dossier_is_immutable_even_via_raw_sql(tenant, user) -> None:
    """Contourne les gardes de service et tente directement le SQL — le
    trigger doit refuser, même pour le propriétaire de la table (même
    patron que `stocks.tests.test_structural_constraints::
    test_done_move_is_immutable_even_via_raw_sql`)."""
    with use_tenant(tenant.id):
        dossier = _declared_dossier(tenant, user)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE qlt_recall_dossier SET reason = %s WHERE id = %s",
                ["Motif falsifié", str(dossier.id)],
            )

        dossier.refresh_from_db()
        assert dossier.reason == "Test structurel"


def test_recall_dossier_cannot_be_deleted_via_raw_sql(tenant, user) -> None:
    with use_tenant(tenant.id):
        dossier = _declared_dossier(tenant, user)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM qlt_recall_dossier WHERE id = %s", [str(dossier.id)])

        assert QltRecallDossier.objects.filter(pk=dossier.pk).exists()


def test_recall_dossier_closure_fields_remain_mutable(tenant, user) -> None:
    """Le trigger est « field-aware » : `state`/`closed_by`/`closed_at`/
    `closing_reason` restent modifiables via `close_recall` (le seul
    chemin de mutation légitime après la génération du dossier)."""
    with use_tenant(tenant.id):
        dossier = _declared_dossier(tenant, user)

        close_recall(dossier, closed_by=user, closing_reason="Analyse terminée")

        dossier.refresh_from_db()
        assert dossier.state == "closed"
        assert dossier.closed_by == user


def test_recall_dossier_bookkeeping_field_update_is_still_allowed(tenant, user) -> None:
    """Les champs de suivi communs `BaseModel` (`is_active`/`archived_at`
    via `soft_delete()`) restent modifiables — même choix assumé que
    `stk_move`/`acc_move`."""
    with use_tenant(tenant.id):
        dossier = _declared_dossier(tenant, user)

        dossier.soft_delete()

        dossier.refresh_from_db()
        assert dossier.is_active is False
