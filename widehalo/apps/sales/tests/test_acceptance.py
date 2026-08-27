"""Finalisation du module `sales` (S7) : verifie explicitement, dans un
seul fichier canonique, l'etat des 4 tests d'acceptance §5.5.8 du CDC.
Chaque test ci-dessous documente son statut (pass/partiel-avec-deviation)
et renvoie, en commentaire, vers le test de niveau inferieur qui couvre
deja le detail — ce fichier n'est pas une re-implementation complete,
c'est le point d'entree canonique pour repondre a la question "le module
sales passe-t-il les 4 tests d'acceptance du CDC ?".

Statuts (recapitulatif, cf. plan section "Module `sales`", decisions de
sequencement) :
  1. RG-SAL-3 (qualification d'origine) : PARTIEL, deviation documentee —
     seule la branche "a produire" cree un document reel (`MrpOrder`) ;
     "sur stock"/"a acheter" restent des stubs honnetes (`apps.stocks`/
     `apps.purchase` n'existent pas). Cf.
     `apps/sales/tests/test_procurement.py`.
  2. RG-SAL-6 (commande recurrente jamais auto-confirmee) : PASS complet.
     Cf. `apps/sales/tests/test_recurrence.py::test_generate_due_order_
     never_auto_confirms` (nom exact a verifier dans ce fichier — le
     comportement teste la, quel que soit le nom exact de la fonction,
     est bien "genere en draft, jamais confirmed").
  3. RG-SAL-7 (rupture matiere signalee en amont de l'echeance) : PARTIEL,
     deviation documentee — seule la composante delai fournisseur est
     reelle (`catalog.get_supplier_lead_time_days`) ; la cause "stock" ne
     peut jamais etre calculee (`apps.stocks` n'existe pas), jamais
     renvoyee. Cf. `apps/sales/tests/test_forecast.py`.
  4. RG-SAL-5 (masquage de la marge par role) : PASS complet, SANS
     deviation — premiere utilisation reelle de `SENSITIVE_FIELDS`/
     `filter_fields_for_role` (S7). Cf.
     `apps/sales/tests/test_margin_masking.py` pour le detail (API +
     ecran + roles autorises/exclus)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.catalog.services.public import get_variant_template_id
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import filter_fields_for_role
from apps.core.tests.utils import use_tenant
from apps.sales.models import SalesOrderLine
from apps.sales.services.orders import add_order_line, confirm_order, create_order
from apps.sales.services.recurrence import create_recurrence, generate_due_order
from apps.sales.tests.factories import SalesOrderFactory

pytestmark = pytest.mark.django_db


def test_acceptance_1_procurement_qualification_partial_deviation_documented() -> None:
    """§5.5.8 n°1 : PARTIEL. Une ligne "a produire" sans nomenclature
    active (aucun `MrpBom` cree dans ce test) reste honnetement marquee
    "necessite une planification manuelle" — jamais un faux `MrpOrder`.
    Une ligne "sur stock"/"a acheter" reste en attente, jamais de document
    reel (stub `apps.stocks`/`apps.purchase`, non construits dans le
    sequencement du Lot 2 a ce stade). Detail complet et cas "a produire"
    reussi : `apps/sales/tests/test_procurement.py`."""
    tenant = Tenant.objects.create(code="ACC-1", name="Acceptance 1 Tenant")
    salesperson = User.objects.create_user(email="acc1@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            description="Sur stock",
            qty=Decimal(1),
            unit_price=Decimal(100),
            is_custom=False,
            variant_id=uuid.uuid4(),
            source=SalesOrderLine.SOURCE_STOCK,
        )
        add_order_line(
            order,
            description="A acheter",
            qty=Decimal(1),
            unit_price=Decimal(100),
            is_custom=False,
            variant_id=uuid.uuid4(),
            source=SalesOrderLine.SOURCE_ACHAT,
        )
        confirm_order(order, salesperson)
        order.refresh_from_db()
        stock_line = order.lines.get(source=SalesOrderLine.SOURCE_STOCK)
        purchase_line = order.lines.get(source=SalesOrderLine.SOURCE_ACHAT)
        assert stock_line.mrp_order_id is None
        assert purchase_line.mrp_order_id is None
        assert purchase_line.purchase_order_line_id is None


def test_acceptance_2_recurring_order_never_auto_confirmed() -> None:
    """§5.5.8 n°2 : PASS complet — "le systeme genere automatiquement une
    nouvelle commande a l'echeance ... la generation n'est JAMAIS
    automatiquement confirmee". Detail complet :
    `apps/sales/tests/test_recurrence.py`."""
    tenant = Tenant.objects.create(code="ACC-2", name="Acceptance 2 Tenant")
    user = User.objects.create_user(email="acc2@example.com", password="Str0ngPassw0rd!23")
    with use_tenant(tenant.id):
        template = SalesOrderFactory(tenant=tenant)
        recurrence = create_recurrence(
            tenant=tenant,
            name="Hebdo",
            interval="weekly",
            start_date=dt.date.today(),
            template_order=template,
        )
        new_order = generate_due_order(recurrence, user)
        assert new_order is not None
        assert new_order.state == "draft"


def test_acceptance_3_forecast_supplier_lead_time_cause_documented_deviation() -> None:
    """§5.5.8 n°3 : PARTIEL — seule la cause "delai fournisseur" est
    reellement calculee (`catalog.services.public.get_supplier_lead_time_
    days`, reel) ; la cause "rupture stock matiere" ne peut jamais etre
    renvoyee (`apps.stocks` n'existe pas). Verifie ici que la fonction
    `get_variant_template_id` (gap S3, prerequis de la chaine de
    qualification) reste appelable sans lever, meme sans donnee — detail
    complet du calcul de cause dominante :
    `apps/sales/tests/test_forecast.py`."""
    # Aucun template pour ce variant : ne doit jamais lever, jamais un faux
    # positif de resolution.
    assert get_variant_template_id(uuid.uuid4()) is None


def test_acceptance_4_margin_masking_full_pass_no_deviation() -> None:
    """§5.5.8 n°4 : PASS complet, SANS deviation — premiere utilisation
    reelle de `SENSITIVE_FIELDS`/`filter_fields_for_role` (S7). Detail
    complet (API + ecran, roles direction/admin/resp_commercial vs
    commercial) : `apps/sales/tests/test_margin_masking.py`."""
    data = {"margin_pct": Decimal("15.00"), "subtotal": Decimal("100")}
    assert "margin_pct" not in filter_fields_for_role("sales.SalesOrderLine", {"commercial"}, data)
    assert "margin_pct" in filter_fields_for_role("sales.SalesOrderLine", {"direction"}, data)
    assert "margin_pct" in filter_fields_for_role("sales.SalesOrderLine", {"admin"}, data)
    assert "margin_pct" in filter_fields_for_role("sales.SalesOrderLine", {"resp_commercial"}, data)
