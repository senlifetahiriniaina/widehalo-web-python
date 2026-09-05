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
REEL (stock effectivement seme via `apps.stocks.tests.factories`).

Bloc F, F2 (FOR-12/FOR-13) : `run_reordering` ne cree plus directement de
`PurRequisition` — elle genere une `PurReorderingProposal` EN ATTENTE
(jamais automatique) ; seul `decide_reordering_proposal` (appele apres
acceptation) cree la vraie demande d'achat. La couverture comparee a
`min_qty` inclut desormais les commandes fournisseur deja EN COURS
(`get_open_order_qty`, reutilise de F1) en plus du stock disponible —
ferme le second volet de FOR-12 ("ignore les commandes en cours")."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurReorderingProposal, PurRequisition
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.reordering import (
    _round_up_to_multiple,
    create_reordering_rule,
    decide_reordering_proposal,
    get_reordering_acceptance_rate,
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
    """`add_requisition_line` (appelee par `decide_reordering_proposal`
    apres acceptation) resout `estimated_price_mga` via
    `catalog.services.public.get_variant_price`, qui exige un
    `ProductVariant` REEL (pas un simple UUID opaque) — cf. meme helper
    dans `apps.purchase.tests.test_orders`."""
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


def _make_buyer(tenant, *, suffix="buyer"):
    """Decideur eligible (`apps.core.services.approvals.decide` exige un
    approbateur du role `acheteur`, cf. `_ensure_rule`/`DEFAULT_APPROVER_
    ROLE` dans `services.reordering`) — meme patron exact que
    `apps.purchase.tests.test_substitution` (RG-PUR-2)."""
    buyer = User.objects.create_user(
        email=f"pur-reord-{suffix}@example.com", password="Str0ngPassw0rd!23"
    )
    buyer.groups.add(Group.objects.get_or_create(name="acheteur")[0])
    return buyer


def _confirm_open_order(tenant, admin, *, variant, qty, uom_code):
    """Fait passer une commande fournisseur jusqu'a `CONFIRMED` (un des
    `_OPEN_ORDER_STATES` de `services.public.get_open_order_qty`) — meme
    parcours que `apps.purchase.tests.test_int1_events._order_to_
    confirmed`, avec un `uom` explicite egal a l'unite de stock de la
    variante pour que `get_conversion_factor` resolve un facteur de 1
    (meme code)."""
    order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
    add_order_line(
        order,
        variant_id=variant.id,
        description="Reappro en cours",
        qty=qty,
        unit_price_mga=Decimal(100),
        uom=uom_code,
    )
    submit_order_for_validation(order, admin)
    validate_order(order, admin)
    send_order(order, admin)
    confirm_order(order, admin)
    return order


def test_rule_below_threshold_triggers_a_pending_proposal(reordering_setup) -> None:
    """Aucun stock seme (disponibilite reelle nulle < min_qty=10) : la
    regle se declenche — et genere une PROPOSITION en attente, jamais
    directement une demande d'achat (FOR-13)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="TRIG")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposals = run_reordering(tenant)

        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.state == PurReorderingProposal.STATE_PENDING
        assert proposal.variant_id == variant.id
        assert proposal.qty_proposed == Decimal(50)  # max_qty, arrondi (multiple_qty=1 par defaut)
        assert proposal.approval_request is not None
        assert PurRequisition.objects.filter(tenant=tenant).count() == 0


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
    `StkQuant` n'existe (jamais un oubli, au pire une proposition
    superflue)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="THR")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal("0.01"), max_qty=Decimal(100)
        )
        proposals = run_reordering(tenant)
        assert len(proposals) == 1


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
    quantite proposee est `max_qty - stock_disponible` (arrondie au
    multiple), pas `max_qty` a lui seul."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="BELOW")
        StkQuantFactory(tenant=tenant, variant_id=variant.id, qty=Decimal(6))
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposals = run_reordering(tenant)

        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.available_stock == Decimal(6)
        assert proposal.on_order_qty == Decimal(0)
        assert proposal.qty_proposed == Decimal(44)  # 50 - 6, multiple_qty=1 par defaut


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


def test_rule_accounts_for_open_purchase_orders_not_just_stock(reordering_setup) -> None:
    """FOR-12 (Bloc F, F2) : second volet — une commande fournisseur deja
    EN COURS (ici `CONFIRMED`, un des `_OPEN_ORDER_STATES`) qui couvre a
    elle seule le manque ne doit plus declencher une proposition
    redondante. Couverture comparee a `min_qty` = stock disponible
    (`get_available_stock_qty`) + commandes en cours
    (`get_open_order_qty`, reutilise de F1), jamais le seul stock."""
    tenant, admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="ONORDER")
        uom_code = variant.template.base_uom.code
        _confirm_open_order(tenant, admin, variant=variant, qty=Decimal(40), uom_code=uom_code)

        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        assert run_reordering(tenant) == []


def test_quantity_proposed_subtracts_open_order_qty(reordering_setup) -> None:
    """FOR-12 : quand la regle se declenche malgre tout (couverture encore
    sous `min_qty`), la quantite proposee tient compte de ce qui est deja
    en commande — jamais un doublon de la quantite deja en route."""
    tenant, admin = reordering_setup
    with use_tenant(tenant.id):
        variant = _make_variant(tenant, suffix="ONORDERQTY")
        uom_code = variant.template.base_uom.code
        _confirm_open_order(tenant, admin, variant=variant, qty=Decimal(10), uom_code=uom_code)

        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(20), max_qty=Decimal(50)
        )
        proposals = run_reordering(tenant)

        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.on_order_qty == Decimal(10)
        assert proposal.qty_proposed == Decimal(40)  # 50 - 0 (stock) - 10 (en commande)


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
        proposals = run_reordering(tenant)
        # ceil(45 / 12) * 12 = ceil(3.75) * 12 = 4 * 12 = 48.
        assert proposals[0].qty_proposed == Decimal(48)


def test_round_up_to_multiple_helper_directly() -> None:
    assert _round_up_to_multiple(Decimal(45), Decimal(12)) == Decimal(48)
    assert _round_up_to_multiple(Decimal(48), Decimal(12)) == Decimal(48)
    assert _round_up_to_multiple(Decimal(1), Decimal(0)) == Decimal(1)  # pas de contrainte
    assert _round_up_to_multiple(Decimal(1), Decimal(-3)) == Decimal(1)


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


def test_decide_reordering_proposal_accepted_creates_draft_requisition(reordering_setup) -> None:
    """Bloc F, F2 : seule l'acceptation explicite (jamais `run_reordering`
    lui-meme, FOR-13) cree la vraie `PurRequisition` — toujours brouillon,
    jamais soumise/approuvee automatiquement."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        buyer = _make_buyer(tenant, suffix="acc")
        variant = _make_variant(tenant, suffix="ACC")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposal = run_reordering(tenant)[0]
        assert proposal.approval_request is not None

        decided = decide_reordering_proposal(proposal.approval_request, buyer, approved=True)

        assert decided.state == PurReorderingProposal.STATE_ACCEPTED
        assert decided.requisition is not None
        assert decided.requisition.state == PurRequisition.STATE_DRAFT
        line = decided.requisition.lines.first()
        assert line is not None
        assert line.variant_id == variant.id
        assert line.qty == Decimal(50)


def test_decide_reordering_proposal_rejected_requires_a_reason(reordering_setup) -> None:
    """FOR-13 : un rejet exige un motif explicite — pas un simple silence
    (meme discipline "motif obligatoire sur toute decision negative" que
    E6/D4 dans ce depot)."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        buyer = _make_buyer(tenant, suffix="rejnoreason")
        variant = _make_variant(tenant, suffix="REJNOREASON")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposal = run_reordering(tenant)[0]
        assert proposal.approval_request is not None

        with pytest.raises(ValidationError, match="motif"):
            decide_reordering_proposal(proposal.approval_request, buyer, approved=False)

        proposal.refresh_from_db()
        assert proposal.state == PurReorderingProposal.STATE_PENDING


def test_decide_reordering_proposal_rejected_leaves_no_requisition(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        buyer = _make_buyer(tenant, suffix="rej")
        variant = _make_variant(tenant, suffix="REJ")
        create_reordering_rule(
            tenant=tenant, variant_id=variant.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposal = run_reordering(tenant)[0]
        assert proposal.approval_request is not None

        decided = decide_reordering_proposal(
            proposal.approval_request,
            buyer,
            approved=False,
            comment="Stock reel suffisant, ecart non detecte.",
        )

        assert decided.state == PurReorderingProposal.STATE_REJECTED
        assert decided.rejection_reason == "Stock reel suffisant, ecart non detecte."
        assert decided.requisition is None
        assert PurRequisition.objects.filter(tenant=tenant).count() == 0


def test_get_reordering_acceptance_rate_is_none_without_any_decision(reordering_setup) -> None:
    """Calcul honnete (FOR-13) : jamais un taux fabrique — `None` tant
    qu'aucune proposition n'a ete decidee."""
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        assert get_reordering_acceptance_rate(tenant) is None


def test_get_reordering_acceptance_rate_computes_honest_ratio(reordering_setup) -> None:
    tenant, _admin = reordering_setup
    with use_tenant(tenant.id):
        buyer = _make_buyer(tenant, suffix="rate")
        variant1 = _make_variant(tenant, suffix="RATE1")
        variant2 = _make_variant(tenant, suffix="RATE2")
        create_reordering_rule(
            tenant=tenant, variant_id=variant1.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        create_reordering_rule(
            tenant=tenant, variant_id=variant2.id, min_qty=Decimal(10), max_qty=Decimal(50)
        )
        proposals = run_reordering(tenant)
        assert len(proposals) == 2
        approval_request_0 = proposals[0].approval_request
        approval_request_1 = proposals[1].approval_request
        assert approval_request_0 is not None
        assert approval_request_1 is not None

        decide_reordering_proposal(approval_request_0, buyer, approved=True)
        decide_reordering_proposal(
            approval_request_1, buyer, approved=False, comment="Non pertinent."
        )

        assert get_reordering_acceptance_rate(tenant) == Decimal("0.5")


def test_run_purchase_reordering_command_runs_across_two_tenants_without_cross_tenant_leakage() -> (
    None
):
    """Acceptance §5.6.7 n°3 : aucun stock reel seme ici pour ces variantes
    (disponibilite reelle nulle, cf. `apps.purchase.services.reordering`
    module docstring — jamais un faux positif/negatif, seulement une
    proposition de plus par regle active dans ce cas). Verifie que la
    commande de management traite CHAQUE tenant independamment : les
    propositions generees pour le tenant A ne fuient jamais vers le
    tenant B, meme quand les deux sont traites dans la meme invocation de
    la commande. Bloc F, F2 : plus aucune `PurRequisition` n'est creee a
    ce stade (FOR-13, "jamais automatique") — seules des
    `PurReorderingProposal` EN ATTENTE le sont."""
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
        assert (
            PurReorderingProposal.objects.filter(
                tenant=tenant_a, state=PurReorderingProposal.STATE_PENDING
            ).count()
            == 2
        )
        assert PurRequisition.objects.filter(tenant=tenant_a).count() == 0
    with use_tenant(tenant_b.id):
        assert (
            PurReorderingProposal.objects.filter(
                tenant=tenant_b, state=PurReorderingProposal.STATE_PENDING
            ).count()
            == 1
        )
        assert PurRequisition.objects.filter(tenant=tenant_b).count() == 0


def test_run_purchase_reordering_command_skips_tenant_without_superuser() -> None:
    tenant = Tenant.objects.create(code="PUR-REORD-CMD-NOSU", name="Reordering No Superuser Cmd")
    with use_tenant(tenant.id):
        create_reordering_rule(
            tenant=tenant, variant_id=uuid.uuid4(), min_qty=Decimal(10), max_qty=Decimal(30)
        )

    # Ne doit pas lever malgre l'absence de superutilisateur pour ce tenant.
    call_command("run_purchase_reordering")

    with use_tenant(tenant.id):
        assert PurReorderingProposal.objects.filter(tenant=tenant).count() == 0
        assert PurRequisition.objects.filter(tenant=tenant).count() == 0
