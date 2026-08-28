"""RG-PUR-3 (§5.6.2, PU5 du sous-sequencement `purchase` — cf. plan) :
reapprovisionnement automatique. Stub honnete documente (`stocks`
n'existe pas encore) : le stock disponible est TOUJOURS considere a zero
par `run_reordering` — cf. `apps.purchase.services.reordering` pour la
justification complete. Consequence testee ici : une regle avec
`min_qty > 0` se declenche TOUJOURS (jamais un faux negatif qui ferait
perdre un vrai besoin), une regle avec `min_qty <= 0` ne se declenche
JAMAIS (regle effectivement desactivee, cas valide)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurRequisition
from apps.purchase.services.reordering import (
    _round_up_to_multiple,
    create_reordering_rule,
    run_reordering,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def reordering_setup():
    tenant = Tenant.objects.create(code="PUR-REORD", name="Purchase Reordering Tenant")
    with use_tenant(tenant.id):
        admin = User.objects.create_superuser(
            email="pur-reord-admin@example.com", password="Str0ngPassw0rd!23"
        )
        return tenant, admin


def _make_variant(tenant, *, suffix="0001"):
    """`add_requisition_line` (appelee par `run_reordering`) resout
    `estimated_price_mga` via `catalog.services.public.get_variant_price`,
    qui exige un `ProductVariant` REEL (pas un simple UUID opaque) — cf.
    meme helper dans `apps.purchase.tests.test_orders`."""
    uom = UnitOfMeasure.objects.create(
        tenant=tenant, code=f"PC{suffix}", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
    )
    template = ProductTemplate.objects.create(
        tenant=tenant,
        name=f"Composant {suffix}",
        base_uom=uom,
        reference=f"TPL-PUR-REORD-{suffix}",
        base_price_mga=Decimal("1000"),
    )
    return ProductVariant.objects.create(
        tenant=tenant, template=template, reference=f"VAR-PUR-REORD-{suffix}"
    )


def test_rule_below_threshold_triggers_a_draft_requisition(reordering_setup) -> None:
    """Stock stube a zero (< min_qty=10) : la regle se declenche toujours."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="TRIG")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        requisitions = run_reordering(tenant)

        assert len(requisitions) == 1
        requisition = requisitions[0]
        assert requisition.state == PurRequisition.STATE_DRAFT
        assert requisition.lines.count() == 1
        line = requisition.lines.first()
        assert line.variant_id == variant.id
        assert line.qty == Decimal(50)  # max_qty, arrondi (multiple_qty=1 par defaut)


def test_rule_with_min_qty_zero_or_negative_never_triggers(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(0), max_qty=Decimal(50)
        )
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(-5), max_qty=Decimal(50)
        )
        assert run_reordering(tenant) == []


def test_rule_at_and_above_threshold_stub_semantics(reordering_setup) -> None:
    """Le stock stube est toujours 0 : `0 < min_qty` est vrai des que
    `min_qty` est strictement positif — meme un `min_qty` tres eleve
    ("stock tres au-dessus du seuil" dans un monde reel) se declenche ici,
    c'est la deviation stub assumee et documentee (jamais un oubli, au pire
    une demande superflue)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="THR")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal("0.01"), max_qty=Decimal(100)
        )
        requisitions = run_reordering(tenant)
        assert len(requisitions) == 1


def test_quantity_rounds_up_to_multiple_qty(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="MULT")
        create_reordering_rule(
            tenant=tenant,
            variant_id=variant.id,
            min_qty=Decimal(5),
            max_qty=Decimal(45),
            multiple_qty=Decimal(12),
        )
        requisitions = run_reordering(tenant)
        line = requisitions[0].lines.first()
        # ceil(45 / 12) * 12 = ceil(3.75) * 12 = 4 * 12 = 48.
        assert line.qty == Decimal(48)


def test_round_up_to_multiple_helper_directly() -> None:
    assert _round_up_to_multiple(Decimal(45), Decimal(12)) == Decimal(48)
    assert _round_up_to_multiple(Decimal(48), Decimal(12)) == Decimal(48)
    assert _round_up_to_multiple(Decimal(1), Decimal(0)) == Decimal(1)  # pas de contrainte
    assert _round_up_to_multiple(Decimal(1), Decimal(-3)) == Decimal(1)


def test_requisition_created_is_always_draft_never_submitted_or_approved(
    reordering_setup,
) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="DRAFT")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(1), max_qty=Decimal(10)
        )
        requisitions = run_reordering(tenant)
        assert requisitions[0].state == PurRequisition.STATE_DRAFT


def test_run_reordering_returns_empty_list_without_active_rules(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        assert run_reordering(tenant) == []


def test_run_reordering_ignores_inactive_rules(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        rule = create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(10), max_qty=Decimal(50)
        )
        rule.is_active = False
        rule.save(update_fields=["is_active"])
        assert run_reordering(tenant) == []


def test_run_reordering_returns_empty_list_without_superuser() -> None:
    tenant = Tenant.objects.create(code="PUR-REORD-NOSU", name="Purchase Reordering No Superuser")
    with use_tenant(tenant.id):
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(10), max_qty=Decimal(50)
        )
        assert run_reordering(tenant) == []


def test_run_purchase_reordering_command_runs_across_two_tenants_without_cross_tenant_leakage() -> (
    None
):
    """Acceptance §5.6.7 n°3 (deviation stub documentee : stock stube a
    zero, cf. `apps.purchase.services.reordering` module docstring — jamais
    un faux positif/negatif, seulement une demande de plus par regle
    active). Verifie que la commande de management traite CHAQUE tenant
    independamment : les demandes generees pour le tenant A ne fuient
    jamais vers le tenant B, meme quand les deux sont traites dans la meme
    invocation de la commande."""
    tenant_a = Tenant.objects.create(code="PUR-REORD-A", name="Reordering Tenant A")
    tenant_b = Tenant.objects.create(code="PUR-REORD-B", name="Reordering Tenant B")

    with use_tenant(tenant_a.id):
        User.objects.create_superuser(
            email="pur-reord-a-admin@example.com", password="Str0ngPassw0rd!23"
        )
        variant_a1 = _make_variant(tenant_a, suffix="LEAK-A1")
        variant_a2 = _make_variant(tenant_a, suffix="LEAK-A2")
        create_reordering_rule(
            tenant=tenant_a, variant_id=variant_a1.id, min_qty=Decimal(10), max_qty=Decimal(30)
        )
        create_reordering_rule(
            tenant=tenant_a, variant_id=variant_a2.id, min_qty=Decimal(5), max_qty=Decimal(20)
        )

    with use_tenant(tenant_b.id):
        User.objects.create_superuser(
            email="pur-reord-b-admin@example.com", password="Str0ngPassw0rd!23"
        )
        variant_b1 = _make_variant(tenant_b, suffix="LEAK-B1")
        create_reordering_rule(
            tenant=tenant_b, variant_id=variant_b1.id, min_qty=Decimal(7), max_qty=Decimal(15)
        )

    call_command("run_purchase_reordering")

    with use_tenant(tenant_a.id):
        assert PurRequisition.objects.filter(tenant=tenant_a).count() == 2
    with use_tenant(tenant_b.id):
        assert PurRequisition.objects.filter(tenant=tenant_b).count() == 1


def test_run_purchase_reordering_command_skips_tenant_without_superuser() -> None:
    tenant = Tenant.objects.create(code="PUR-REORD-CMD-NOSU", name="Reordering No Superuser Cmd")
    with use_tenant(tenant.id):
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(10), max_qty=Decimal(30)
        )

    # Ne doit pas lever malgre l'absence de superutilisateur pour ce tenant.
    call_command("run_purchase_reordering")

    with use_tenant(tenant.id):
        assert PurRequisition.objects.filter(tenant=tenant).count() == 0
