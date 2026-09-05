"""Export asynchrone (BI-8) — réutilisation de `apps.reporting` (`RptJob`/
`generate_report`) via le rapport générique enregistré par
`apps.bi.apps.py::ready`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.bi.services.export import REPORT_CODE, render_bi_report_rows
from apps.bi.tests.factories import BiReportFactory
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def test_bi_dynamic_report_is_registered() -> None:
    report = get_registered_report(REPORT_CODE)
    assert report is not None
    assert report.supports_rows()


def test_render_bi_report_rows_activates_tenant_and_returns_rows() -> None:
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.create(code="BI-EXP", name="BI Export Tenant")
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            # L8 : le fait vient desormais du dictionnaire lui-meme, plus
            # d'une table de correspondance figee dans `bi`.
            fait_source="vente",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("7000"))
        report = BiReportFactory(tenant=tenant)
        actor = UserFactory()
        grant_role(actor, "direction")

    # Simule l'execution HORS contexte tenant (job async), cf. docstring
    # `render_bi_report_rows` — aucun `use_tenant` actif ici.
    rows = render_bi_report_rows({"bi_report_id": str(report.id)}, actor)

    # `BiReportFactory.definition` par defaut demande "temps" en dimension
    # (cf. `apps.bi.tests.factories`) — la ligne porte donc aussi cette cle,
    # avec la date reelle du fait (non fixee ici, cf. `AnDimTempsFactory`).
    assert len(rows) == 1
    assert rows[0]["indicateur"] == "sales.ca_ht"
    assert rows[0]["unite"] == ""
    assert rows[0]["value"] == Decimal("7000.0000")
    assert "temps" in rows[0]


def test_render_bi_report_rows_returns_empty_for_unknown_report() -> None:
    actor = UserFactory()
    assert (
        render_bi_report_rows({"bi_report_id": "00000000-0000-0000-0000-000000000000"}, actor) == []
    )
