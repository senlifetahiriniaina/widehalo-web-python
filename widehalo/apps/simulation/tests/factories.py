"""Factories factory_boy pour les modèles du module `simulation`."""

from __future__ import annotations

import datetime as dt

import factory
from django.utils import timezone

from apps.simulation.levers import default_levers
from apps.simulation.models import SimBaseline, SimScenario


def _default_baseline_data() -> dict[str, object]:
    return {
        "ca_ref": "100000000",
        "achats_consommes_ref": "40000000",
        "production_stockee_ref": "0",
        "production_immobilisee_ref": "0",
        "subvention_exploitation_ref": "0",
        "charges_personnel_ref": "20000000",
        "impots_taxes_ref": "1000000",
        "autres_produits_operationnels_ref": "0",
        "dotations_ref": "2000000",
        "produits_financiers_ref": "0",
        "charges_financieres_ref": "500000",
        "impot_resultats_ref": "3000000",
        "ebe_ref": "39000000",
        # Cf. commentaire equivalent dans `test_engine.py` : coherent avec
        # la cascade `compute_indicators` a leviers nuls sur les autres
        # champs de ce dict (un socle reel est toujours coherent, cf.
        # `services.baseline.build_baseline`).
        "resultat_net_ref": "33500000",
        "tva_taux_ref": "20",
        "starting_cash_mga": "15000000",
        "as_of_date": "2026-09-01",
        "degraded": False,
        "open_items": [
            {"kind": "receivable", "due_date": "2026-09-15", "amount_mga": "5000000"},
            {"kind": "payable", "due_date": "2026-09-20", "amount_mga": "3000000"},
        ],
    }


class SimBaselineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SimBaseline

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    period_start = dt.date(2025, 9, 1)
    period_end = dt.date(2026, 9, 1)
    as_of_date = dt.date(2026, 9, 1)
    regulatory_param_version = factory.LazyFunction(lambda: {"tva.taux_normal": 1})
    data = factory.LazyFunction(_default_baseline_data)
    open_items_total_count = 2
    open_items_included_count = 2


class SimScenarioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SimScenario

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    baseline = factory.SubFactory(SimBaselineFactory, tenant=factory.SelfAttribute("..tenant"))
    baseline_extracted_at = factory.LazyFunction(timezone.now)
    baseline_period_start = factory.SelfAttribute("baseline.period_start")
    baseline_period_end = factory.SelfAttribute("baseline.period_end")
    baseline_as_of_date = factory.SelfAttribute("baseline.as_of_date")
    baseline_regulatory_param_version = factory.SelfAttribute("baseline.regulatory_param_version")
    name = factory.Sequence(lambda n: f"Scénario {n}")
    owner = factory.SubFactory("apps.core.tests.factories.UserFactory")
    levers = factory.LazyFunction(lambda: {code: str(value) for code, value in default_levers().items()})
    computed_indicators = factory.LazyFunction(dict)
