"""Bloc D, D4 (QUA-4) : test de performance sur un jeu de données
représentatif — premier test de ce type dans le dépôt (aucun précédent de
timing n'existe ailleurs). Portée assumée et documentée dans le plan D4 :
le seuil de 5 s couvre `declare_recall` DE BOUT EN BOUT (traversée de
généalogie + mise en quarantaine de chaque lot impacté), pas seulement la
lecture de l'arbre — c'est l'opération que l'audit Phase 3 nomme
explicitement comme jamais mesurée."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.quality.services.recall import declare_recall
from apps.stocks.models import StkLot
from apps.stocks.services.genealogy import record_consumption

pytestmark = [pytest.mark.django_db, pytest.mark.slow]

RECALL_PERFORMANCE_THRESHOLD_SECONDS = 5

# Arbre representatif : une racine consommee par BRANCHING_FACTOR lots,
# chacun consomme a son tour par BRANCHING_FACTOR lots, sur DEPTH niveaux
# — 4^4 = 256 lots au dernier niveau, ~340 lots au total (bien en-deca de
# MAX_DEPTH=10 dans genealogy.py). Taille choisie pour rester
# representative (plusieurs centaines de lots, embranchements multiples)
# tout en restant mesurable de facon fiable dans ce bac a sable.
BRANCHING_FACTOR = 4
DEPTH = 4


def _build_genealogy_tree(tenant: Tenant, *, branching_factor: int, depth: int) -> StkLot:
    root = StkLot.objects.create(tenant=tenant, variant_id=uuid.uuid4(), name="ROOT-PERF")
    frontier = [root]
    for level in range(depth):
        next_frontier: list[StkLot] = []
        for parent in frontier:
            for branch in range(branching_factor):
                child = StkLot.objects.create(
                    tenant=tenant,
                    variant_id=uuid.uuid4(),
                    name=f"LOT-PERF-{level}-{parent.id}-{branch}",
                )
                record_consumption(
                    tenant=tenant,
                    parent_lot=parent,
                    child_lot=child,
                    qty=Decimal("1"),
                    source_document=f"OF-PERF-{level}-{branch}",
                )
                next_frontier.append(child)
        frontier = next_frontier
    return root


def test_declare_recall_completes_within_threshold_on_a_representative_tree() -> None:
    tenant = Tenant.objects.create(code="QLT-PERF", name="Quality Performance Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="perf-qlt@example.com", password="Str0ngPassw0rd!23")
        root = _build_genealogy_tree(tenant, branching_factor=BRANCHING_FACTOR, depth=DEPTH)

        started_at = time.perf_counter()
        dossier = declare_recall(
            tenant=tenant,
            lot_variant_id=root.variant_id,
            lot_name=root.name,
            reason="Test de performance QUA-4",
            initiated_by=user,
        )
        elapsed_seconds = time.perf_counter() - started_at

        expected_impacted_count = (
            sum(BRANCHING_FACTOR**level for level in range(1, DEPTH + 1)) + 1
        )  # + la racine elle-meme
        assert len(dossier.impacted_lots) == expected_impacted_count
        assert elapsed_seconds < RECALL_PERFORMANCE_THRESHOLD_SECONDS, (
            f"declare_recall a pris {elapsed_seconds:.2f}s pour "
            f"{expected_impacted_count} lots impactés — au-delà du seuil "
            f"QUA-4 de {RECALL_PERFORMANCE_THRESHOLD_SECONDS}s."
        )
