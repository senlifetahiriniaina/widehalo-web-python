"""Diffusion planifiée (`services/diffusion.py`) — cahier Phase 2 §13.1,
BI-7 : journalisée avec destinataire, périmètre, canal et statut."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.bi.models import BiDiffusionLog, BiReport
from apps.bi.services.diffusion import run_due_diffusions, send_report_to_recipient
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def diffusion_tenant() -> Tenant:
    return Tenant.objects.create(code="BI-DIFF", name="BI Diffusion Tenant")


def test_send_report_to_recipient_logs_success(diffusion_tenant: Tenant) -> None:
    with use_tenant(diffusion_tenant.id):
        register_metric(
            diffusion_tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=diffusion_tenant, montant_ht_mga=Decimal("10000"))
        report = BiReportFactory(tenant=diffusion_tenant)
        recipient = UserFactory(email="direction@example.com")
        grant_role(recipient, "direction")

        log = send_report_to_recipient(report, recipient)

        assert log.status == BiDiffusionLog.STATUS_SENT
        assert log.recipient == "direction@example.com"
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["direction@example.com"]


def test_run_due_diffusions_advances_watermark_and_logs_each_recipient(
    diffusion_tenant: Tenant,
) -> None:
    with use_tenant(diffusion_tenant.id):
        register_metric(
            diffusion_tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=diffusion_tenant, montant_ht_mga=Decimal("1000"))
        recipient = UserFactory(email="direction2@example.com")
        grant_role(recipient, "direction")
        report = BiReportFactory(
            tenant=diffusion_tenant,
            diffusion_enabled=True,
            diffusion_frequency=BiReport.FREQUENCY_DAILY,
            diffusion_recipients=["direction2@example.com"],
            diffusion_next_run_at=timezone.now(),
        )

        sent_count = run_due_diffusions(diffusion_tenant)

        assert sent_count == 1
        assert BiDiffusionLog.objects.filter(tenant=diffusion_tenant, report=report).count() == 1
        report.refresh_from_db()
        assert report.diffusion_last_run_at is not None
        assert report.diffusion_next_run_at > timezone.now()
