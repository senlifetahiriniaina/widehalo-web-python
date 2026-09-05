"""Bloc D, D1 (QUA-1/2/3) : ouverture manuelle et clôture d'une
non-conformité — motif obligatoire dans les deux cas."""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.models import QltNonConformity
from apps.quality.services.non_conformity import (
    close_non_conformity,
    create_non_conformity,
    has_open_non_conformity,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def nc_setup():
    tenant = Tenant.objects.create(code="QLT-NC", name="Quality NC Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="nc@example.com", password="Str0ngPassw0rd!23")
        return tenant, user


def test_create_non_conformity_requires_reason(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_non_conformity(tenant=tenant, opened_by=user, description="")


def test_create_non_conformity_assigns_reference(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id):
        nc = create_non_conformity(
            tenant=tenant, opened_by=user, description="Corps étranger détecté"
        )
        assert nc.reference.startswith("QLT-NC-")
        assert nc.state == QltNonConformity.STATE_OPEN


def test_close_non_conformity_requires_reason(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id):
        nc = create_non_conformity(tenant=tenant, opened_by=user, description="Défaut mineur")
        with pytest.raises(ValidationError):
            close_non_conformity(nc, closed_by=user, closing_reason="")


def test_close_non_conformity_refuses_double_close(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id):
        nc = create_non_conformity(tenant=tenant, opened_by=user, description="Défaut mineur")
        close_non_conformity(nc, closed_by=user, closing_reason="Corrigé")
        with pytest.raises(ValidationError):
            close_non_conformity(nc, closed_by=user, closing_reason="Encore")


def test_close_non_conformity_records_closer_and_timestamp(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id):
        nc = create_non_conformity(tenant=tenant, opened_by=user, description="Défaut mineur")
        closed = close_non_conformity(nc, closed_by=user, closing_reason="Corrigé")
        assert closed.state == QltNonConformity.STATE_CLOSED
        assert closed.closed_by_id == user.id
        assert closed.closed_at is not None
        assert closed.closing_reason == "Corrigé"


def test_has_open_non_conformity(nc_setup) -> None:
    tenant, user = nc_setup
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        assert (
            has_open_non_conformity(tenant=tenant, lot_variant_id=variant_id, lot_name="LOT-X")
            is False
        )

        nc = create_non_conformity(
            tenant=tenant,
            opened_by=user,
            description="Défaut mineur",
            lot_variant_id=variant_id,
            lot_name="LOT-X",
        )
        assert (
            has_open_non_conformity(tenant=tenant, lot_variant_id=variant_id, lot_name="LOT-X")
            is True
        )

        close_non_conformity(nc, closed_by=user, closing_reason="Corrigé")
        assert (
            has_open_non_conformity(tenant=tenant, lot_variant_id=variant_id, lot_name="LOT-X")
            is False
        )
