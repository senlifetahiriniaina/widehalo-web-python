from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurSubstitute
from apps.purchase.services.substitution import (
    approve_substitute,
    create_substitute,
    ensure_substitute_usable,
    list_substitutes_for_variant,
    request_substitute_approval,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def substitution_setup():
    tenant = Tenant.objects.create(code="PUR-SUB-T", name="Purchase Substitution Tenant")
    with use_tenant(tenant.id):
        buyer = User.objects.create_user(
            email="acheteur2@example.com", password="Str0ngPassw0rd!23"
        )
        buyer.groups.add(Group.objects.get_or_create(name="acheteur")[0])
        variant_id = uuid.uuid4()
        return tenant, buyer, variant_id


def test_create_substitute_identique_is_immediately_usable(substitution_setup) -> None:
    tenant, _buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_IDENTIQUE,
        )
        assert substitute.approved_by is None
        ensure_substitute_usable(substitute)  # ne leve pas


def test_create_substitute_equivalent_is_immediately_usable(substitution_setup) -> None:
    tenant, _buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_EQUIVALENT,
        )
        ensure_substitute_usable(substitute)  # ne leve pas


# §5.6.7 n°2 : "Une substitution de niveau degrade sans validation est refusee"
def test_ensure_substitute_usable_refuses_unapproved_degrade(substitution_setup) -> None:
    tenant, _buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        with pytest.raises(ValidationError):
            ensure_substitute_usable(substitute)


def test_approve_substitute_refuses_for_non_degrade(substitution_setup) -> None:
    tenant, buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_IDENTIQUE,
        )
        with pytest.raises(ValidationError):
            approve_substitute(substitute, approved_by=buyer)


def test_request_then_approve_degrade_substitute_makes_it_usable(substitution_setup) -> None:
    tenant, buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        request_substitute_approval(substitute, requested_by=buyer)
        with pytest.raises(ValidationError):
            ensure_substitute_usable(substitute)

        approved = approve_substitute(substitute, approved_by=buyer)
        assert approved.approved_by_id == buyer.id
        ensure_substitute_usable(approved)  # ne leve plus


def test_approve_substitute_without_prior_request_still_works(substitution_setup) -> None:
    tenant, buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        substitute = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        approved = approve_substitute(substitute, approved_by=buyer)
        assert approved.approved_by_id == buyer.id


# §5.6.7 n°1 : substituts proposes et classes par compatibilite
def test_list_substitutes_for_variant_orders_by_compatibility(substitution_setup) -> None:
    tenant, buyer, variant_id = substitution_setup
    with use_tenant(tenant.id):
        degrade = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        identique = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_IDENTIQUE,
        )
        equivalent = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_EQUIVALENT,
        )
        # Un substitut d'une autre variante ne doit pas apparaitre.
        create_substitute(
            tenant=tenant,
            variant_id=uuid.uuid4(),
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_IDENTIQUE,
        )

        result = list_substitutes_for_variant(variant_id)
        assert [s.id for s in result] == [identique.id, equivalent.id, degrade.id]
