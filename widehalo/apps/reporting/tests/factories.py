from __future__ import annotations

import datetime as dt

import factory
from django.utils import timezone

from apps.reporting.models import RptDefinition, RptJob, RptLayout, RptSchedule


class RptDefinitionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RptDefinition

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"TEST-RPT-{n}")
    module = "core"
    label = "Rapport de test"
    permission = "reporting.view_rptdefinition"
    supports_rows = True


class RptLayoutFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RptLayout

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    code = factory.Sequence(lambda n: f"LAYOUT-{n}")
    name = "Gabarit de test"
    template_path = "reports/_base.html"


class RptJobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RptJob

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    report_code = "TEST-RPT"
    params = factory.LazyFunction(dict)
    format = RptJob.FORMAT_JSON


class RptScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RptSchedule

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Planification {n}")
    report_code = "TEST-RPT"
    params = factory.LazyFunction(dict)
    format = RptJob.FORMAT_JSON
    frequency = RptSchedule.FREQUENCY_DAILY
    next_run_at = factory.LazyFunction(lambda: timezone.now() + dt.timedelta(days=1))
