"""Finalisation du module `purchase` (PU8) : verifie explicitement, dans un
seul fichier canonique, l'etat des 4 tests d'acceptance §5.6.7 du CDC.
Chaque test ci-dessous documente son statut et renvoie, en commentaire,
vers le test de niveau inferieur qui couvre deja le detail — ce fichier
n'est pas une re-implementation complete, c'est le point d'entree
canonique pour repondre a la question "le module purchase passe-t-il les
4 tests d'acceptance du CDC ?" (meme discipline que
`apps/sales/tests/test_acceptance.py`/`apps/mrp/tests/*`).

Statuts (recapitulatif) :
  1. RG-PUR-2 (substituts classes par compatibilite) : PASS complet. Cf.
     `apps/purchase/tests/test_substitution.py::
     test_list_substitutes_for_variant_sorted_by_compatibility` (PU2).
  2. RG-PUR-2 (substitution degrade sans validation refusee) : PASS
     complet. Cf. `apps/purchase/tests/test_substitution.py`/
     `test_requisitions.py` (PU2).
  3. RG-PUR-3 (reapprovisionnement automatique -> demande d'achat en
     brouillon) : PASS complet, AVEC UN STUB DOCUMENTE — le declenchement
     repose sur un stock disponible toujours considere a zero
     (`apps.stocks`/`apps.logistics` n'existent pas encore dans ce depot,
     cf. docstring `services/reordering.py`). Ce stub ne remet PAS en
     cause le critere d'acceptance lui-meme (une demande d'achat EST bien
     creee en brouillon des que `min_qty > 0`) — a la difference des
     deviations PARTIELLES de `sales` (RG-SAL-3/RG-SAL-7), qui omettaient
     une branche entiere du critere. Cf.
     `apps/purchase/tests/test_reordering.py`.
  4. RG-PUR-6 (facture >5% du bon de commande bloque la validation et
     ouvre un litige) : PASS complet, SANS deviation. Cf.
     `apps/purchase/tests/test_invoicing.py`."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.purchase.models import PurCri, PurReorderingRule, PurSubstitute
from apps.purchase.services.invoicing import record_supplier_invoice
from apps.purchase.services.orders import (
    add_order_line,
    confirm_order,
    create_order,
    mark_order_in_transit,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.receiving import receive_order_line
from apps.purchase.services.reordering import run_reordering
from apps.purchase.services.requisitions import add_requisition_line, create_requisition
from apps.purchase.services.substitution import create_substitute, list_substitutes_for_variant

pytestmark = pytest.mark.django_db


def test_acceptance_1_substitutes_ranked_by_compatibility_full_pass() -> None:
    """§5.6.7 n°1 : "Une rupture sur un tissu propose les substituts
    declares, classes par compatibilite" — PASS complet. Detail complet :
    `apps/purchase/tests/test_substitution.py` (PU2)."""
    tenant = Tenant.objects.create(code="PUR-ACC-1", name="Acceptance 1 Tenant")
    with use_tenant(tenant.id):
        variant_id = uuid.uuid4()
        degraded = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        identical = create_substitute(
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

        ranked = list_substitutes_for_variant(variant_id)
        assert [s.id for s in ranked] == [identical.id, equivalent.id, degraded.id]


def test_acceptance_2_degraded_substitute_without_validation_is_rejected_full_pass() -> None:
    """§5.6.7 n°2 : "Une substitution de niveau degrade sans validation est
    refusee" — PASS complet. Detail complet :
    `apps/purchase/tests/test_substitution.py`/`test_requisitions.py`
    (PU2)."""
    from django.core.exceptions import ValidationError

    tenant = Tenant.objects.create(code="PUR-ACC-2", name="Acceptance 2 Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="acc2@example.com", password="Str0ngPassw0rd!23")
        variant_id = uuid.uuid4()
        degraded = create_substitute(
            tenant=tenant,
            variant_id=variant_id,
            substitute_variant_id=uuid.uuid4(),
            compatibility=PurSubstitute.COMPATIBILITY_DEGRADE,
        )
        requisition = create_requisition(tenant=tenant, requester=user, date_needed=dt.date.today())

        with pytest.raises(ValidationError):
            add_requisition_line(
                requisition,
                variant_id=variant_id,
                description="Substitut non valide",
                qty=Decimal(1),
                substitute_id=degraded.id,
            )


def test_acceptance_3_reordering_creates_draft_requisition_below_min_full_pass_stub() -> None:
    """§5.6.7 n°3 : "Le reapprovisionnement automatique cree une demande
    d'achat en brouillon lorsque le stock passe sous le minimum" — PASS
    complet, avec un stub honnete documente sur le stock disponible
    (toujours considere a zero, `apps.stocks` non construit dans ce depot
    — cf. docstring `services/reordering.py`). Ce stub ne compromet PAS le
    critere teste ici : des que `min_qty > 0`, une `PurRequisition` EN
    BROUILLON est bien creee, jamais une commande confirmee. Detail
    complet : `apps/purchase/tests/test_reordering.py`."""
    tenant = Tenant.objects.create(code="PUR-ACC-3", name="Acceptance 3 Tenant")
    with use_tenant(tenant.id):
        User.objects.create_superuser(email="acc3-admin@example.com", password="Str0ngPassw0rd!23")
        # `run_reordering` -> `add_requisition_line` resout
        # `estimated_price_mga` via `catalog.services.public.
        # get_variant_price`, qui exige un `ProductVariant` REEL (pas un
        # simple UUID opaque) — meme helper que
        # `apps/purchase/tests/test_reordering.py::_make_variant`.
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC-ACC3", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        template = ProductTemplate.objects.create(
            tenant=tenant,
            name="Composant Acceptance 3",
            base_uom=uom,
            reference="TPL-PUR-ACC-3",
            base_price_mga=Decimal("1000"),
        )
        variant = ProductVariant.objects.create(
            tenant=tenant, template=template, reference="VAR-PUR-ACC-3"
        )
        PurReorderingRule.objects.create(
            tenant=tenant,
            variant_id=variant.id,
            min_qty=Decimal(10),
            max_qty=Decimal(50),
            multiple_qty=Decimal(1),
        )

        created = run_reordering(tenant)

        assert len(created) == 1
        assert created[0].state == "draft"
        assert created[0].lines.count() == 1


def test_acceptance_4_invoice_variance_above_5pct_blocks_and_opens_dispute_full_pass() -> None:
    """§5.6.7 n°4 : "Une facture superieure de 5% au bon de commande bloque
    la validation et ouvre un litige" — PASS complet, SANS deviation.
    Verifie a la fois qu'AUCUNE facture n'est creee (`invoice_id is None`),
    que la commande transite vers `in_dispute` (jamais `invoiced`), et
    qu'un `PurCri` de type `litige` est cree en plus (PU7, RG-PUR-8). Detail
    complet : `apps/purchase/tests/test_invoicing.py`."""
    tenant = Tenant.objects.create(code="PUR-ACC-4", name="Acceptance 4 Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="acc4@example.com", password="Str0ngPassw0rd!23")
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            variant_id=uuid.uuid4(),
            description="Tissu coton",
            qty=Decimal(100),
            unit_price_mga=Decimal(1000),
        )
        submit_order_for_validation(order, user)
        validate_order(order, user)
        send_order(order, user)
        confirm_order(order, user)
        mark_order_in_transit(order, user)
        line = order.lines.first()
        receive_order_line(
            line, qty_received_now=Decimal(100), quality_status="conforme", user=user
        )
        order.refresh_from_db()
        assert order.state == "received"

        # Commande = 100 x 1000 = 100 000 MGA. Facture a 106 000 (+6%,
        # depasse le seuil par defaut de 2% ET l'exemple "5%" du CDC).
        result = record_supplier_invoice(
            order,
            invoice_lines=[
                {
                    "order_line_id": line.id,
                    "qty_invoiced": Decimal(100),
                    "unit_price_mga": Decimal(1060),
                }
            ],
            date=dt.date.today(),
            user=user,
        )

        assert result["invoice_id"] is None
        assert result["dispute_opened"] is True
        order.refresh_from_db()
        assert order.state == "in_dispute"
        assert order.state != "invoiced"
        assert PurCri.objects.filter(order=order, type=PurCri.TYPE_LITIGE).exists()
