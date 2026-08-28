"""RG-PUR-3 (§5.6.2, PU5 du sous-sequencement `purchase` — cf. plan) :
reapprovisionnement automatique. Depuis le chantier de durcissement
retroactif (`apps.stocks` existe desormais), `run_reordering` lit le VRAI
stock disponible (`stocks.services.public.get_available_stock_qty`) — cf.
`apps.purchase.services.reordering` pour le detail. Les tests ci-dessous
n'ensemencent PAS de stock reel sauf mention explicite : aucun
`StkQuant`/`StkWarehouse` cree pour une variante donnee => sa
disponibilite reelle est `Decimal(0)` (agregat vide), ce qui reproduit
exactement le comportement precedemment stube pour ces cas — une regle
avec `min_qty > 0` continue donc de se declencher en l'absence de tout
stock connu (jamais un faux negatif), une regle avec `min_qty <= 0` ne se
declenche JAMAIS (regle effectivement desactivee, cas valide). Les
nouveaux tests `test_rule_skips_when_stock_is_sufficient`/
`test_rule_triggers_when_stock_is_below_min_qty` verifient en plus le cas
REEL (stock effectivement seme via `apps.stocks.tests.factories`)."""

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
from apps.stocks.tests.factories import StkQuantFactory

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
    """Aucun stock seme (disponibilite reelle nulle < min_qty=10) : la
    regle se declenche."""
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


def test_rule_at_and_above_threshold_without_known_stock(reordering_setup) -> None:
    """Sans aucun stock connu pour la variante, la disponibilite reelle
    est nulle : `0 < min_qty` est vrai des que `min_qty` est strictement
    positif — meme un `min_qty` tres bas se declenche toujours quand aucun
    `StkQuant` n'existe (jamais un oubli, au pire une demande superflue)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="THR")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal("0.01"), max_qty=Decimal(100)
        )
        requisitions = run_reordering(tenant)
        assert len(requisitions) == 1


def test_rule_skips_when_stock_is_sufficient(reordering_setup) -> None:
    """Stock reel seme au-dessus de `min_qty` : la regle ne se declenche
    plus — le coeur du chantier de durcissement retroactif (avant, le
    stock stube a zero declenchait TOUJOURS une regle a `min_qty > 0`)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="SUFF")
        StkQuantFactory(tenant=tenant, variant_id=variant.id, qty=Decimal(80))
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        assert run_reordering(tenant) == []


def test_rule_triggers_when_stock_is_below_min_qty(reordering_setup) -> None:
    """Stock reel seme mais sous `min_qty` : la regle se declenche, et la
    quantite demandee est `max_qty - stock_disponible` (arrondie au
    multiple), pas `max_qty` a lui seul."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="BELOW")
        StkQuantFactory(tenant=tenant, variant_id=variant.id, qty=Decimal(6))
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        requisitions = run_reordering(tenant)

        assert len(requisitions) == 1
        line = requisitions[0].lines.first()
        assert line.qty == Decimal(44)  # 50 - 6, multiple_qty=1 par defaut


def test_rule_accounts_for_reserved_qty_not_just_on_hand(reordering_setup) -> None:
    """`get_available_stock_qty` est `qty - qty_reserved`, pas seulement
    `qty` — un stock physiquement present mais deja entierement reserve ne
    doit pas empecher le declenchement de la regle."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="RSVD")
        StkQuantFactory(
            tenant=tenant, variant_id=variant.id, qty=Decimal(80), qty_reserved=Decimal(80)
        )
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        assert len(run_reordering(tenant)) == 1


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
    """Acceptance §5.6.7 n°3 : aucun stock reel seme ici pour ces variantes
    (disponibilite reelle nulle, cf. `apps.purchase.services.reordering`
    module docstring — jamais un faux positif/negatif, seulement une
    demande de plus par regle active dans ce cas). Verifie que la commande
    de management traite CHAQUE tenant
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
