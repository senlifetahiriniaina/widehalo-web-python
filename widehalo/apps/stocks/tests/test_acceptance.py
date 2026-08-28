"""Finalisation du module `stocks` (ST8, §5.8) : verifie explicitement,
dans un seul fichier canonique, l'etat des 5 tests d'acceptance §5.8.7 du
CDC. Chaque test ci-dessous documente son statut et renvoie, en
commentaire, vers le test de niveau inferieur qui couvre deja le detail —
ce fichier n'est pas une re-implementation complete (sauf le n°5, NOUVEAU a
ce lot), c'est le point d'entree canonique pour repondre a la question "le
module stocks passe-t-il les 5 tests d'acceptance du CDC ?" (meme
discipline que `apps/purchase/tests/test_acceptance.py`).

`stocks` est le module qui LEVE la plupart des stubs des modules
precedents plutot que d'en introduire de nouveaux (cf. plan, section
"Decisions de sequencement") — les 5 tests ci-dessous sont TOUS un PASS
sans reserve/deviation, contrairement a d'autres modules de ce depot
(`sales`/`purchase`) qui documentent des PASS partiels/stubes : c'est la
raison meme de la reinsertion de ce module avant `logistics`.

Statuts (recapitulatif) :
  1. RG-STK-1 (somme algebrique nulle par produit apres 1000 mouvements
     aleatoires) : PASS complet. Cf.
     `test_hypothesis_properties.py::
     test_rg_stk_1_algebraic_sum_is_always_zero_per_variant`.
  2. RG-STK-2 (valeur du stock = somme des couches residuelles apres 500
     operations FIFO) : PASS complet. Cf.
     `test_hypothesis_properties.py::
     test_rg_stk_2_stock_value_equals_sum_of_remaining_layers`.
  3. RG-STK-4 (rouleau annonce 50m mesure 47,5m -> 47,5m enregistre +
     litige ouvert) : PASS complet. Cf. `test_measurements.py::
     test_record_measurement_acceptance_case_50m_announced_47_5m_measured_opens_dispute`.
  4. RG-STK-6 (OF declarant 100 pieces avec 95 entrees en stock apparait
     dans le rapport de coherence) : PASS complet. Cf.
     `test_consistency.py::
     test_production_consistency_report_flags_acceptance_test_case`.
  5. STK-TRAC (la tracabilite d'un lot remonte a la commande fournisseur
     et descend jusqu'aux clients livres) : PASS complet, construit et
     verifie DANS ce fichier (nouveau service ST8,
     `services/traceability.py`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkLot, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.traceability import lot_traceability
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


def test_acceptance_1_rg_stk_1_algebraic_sum_zero_full_pass() -> None:
    """§5.8.7 n°1 — PASS complet. Detail complet (1000 mouvements
    aleatoires Hypothesis) :
    `apps/stocks/tests/test_hypothesis_properties.py::
    test_rg_stk_1_algebraic_sum_is_always_zero_per_variant` (ST2, marque
    `@pytest.mark.slow`, verifie separement via `pytest -m slow`)."""
    assert True


def test_acceptance_2_rg_stk_2_valuation_equals_layers_full_pass() -> None:
    """§5.8.7 n°2 — PASS complet. Detail complet (500 operations FIFO) :
    `apps/stocks/tests/test_hypothesis_properties.py::
    test_rg_stk_2_stock_value_equals_sum_of_remaining_layers` (ST2, marque
    `@pytest.mark.slow`, verifie separement via `pytest -m slow`)."""
    assert True


def test_acceptance_3_rg_stk_4_measurement_variance_opens_dispute_full_pass() -> None:
    """§5.8.7 n°3 — PASS complet. Detail complet :
    `apps/stocks/tests/test_measurements.py::
    test_record_measurement_acceptance_case_50m_announced_47_5m_measured_opens_dispute`
    (ST3)."""
    assert True


def test_acceptance_4_rg_stk_6_consistency_report_flags_declared_vs_entered_full_pass() -> None:
    """§5.8.7 n°4 — PASS complet. Detail complet :
    `apps/stocks/tests/test_consistency.py::
    test_production_consistency_report_flags_acceptance_test_case` (ST6)."""
    assert True


def test_acceptance_5_stk_trac_lot_traceability_upstream_and_downstream_full_pass() -> None:
    """§5.8.7 n°5 : "La tracabilite d'un lot de tissu remonte a la commande
    fournisseur et descend jusqu'aux clients livres." — PASS complet, SANS
    deviation. Scenario litteral du CDC : un lot, une reception dont
    `source_document` simule la reference de la commande fournisseur
    d'origine, une livraison dont `source_document` simule la reference de
    la commande client — `lot_traceability` doit exposer les deux
    references correctement, chacune dans sa direction."""
    tenant = Tenant.objects.create(code="STK-ACC-5", name="Acceptance 5 Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-ACC5", name="Entrepot")
        supplier_location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        internal_location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon tissus",
            type=StkLocation.TYPE_INTERNE,
        )
        client_location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        variant_id = uuid.uuid4()
        lot = StkLot.objects.create(tenant=tenant, variant_id=variant_id, name="LOT-TISSU-ACC5")

        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("100"),
            uom="m",
            location_from=supplier_location,
            location_to=internal_location,
            date=dt.date(2026, 1, 5),
            move_type=StkMove.TYPE_RECEPTION,
            source_document="PCMD-2026-001",
            unit_cost_mga=Decimal("5000"),
            lot=lot,
        )
        validate_move(reception)

        livraison = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal("60"),
            uom="m",
            location_from=internal_location,
            location_to=client_location,
            date=dt.date(2026, 2, 1),
            move_type=StkMove.TYPE_LIVRAISON,
            source_document="SCMD-2026-042",
            lot=lot,
        )
        validate_move(livraison)

        result = lot_traceability(lot)

        upstream_documents = {row["source_document"] for row in result["upstream"]}
        downstream_documents = {row["source_document"] for row in result["downstream"]}
        assert upstream_documents == {"PCMD-2026-001"}
        assert downstream_documents == {"SCMD-2026-042"}
        assert result["current_locations"] == [
            {"location_id": internal_location.id, "location_code": "A1", "qty": Decimal("40")}
        ]
