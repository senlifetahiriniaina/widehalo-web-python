from __future__ import annotations

import factory

from apps.reporting.models import RptDefinition, RptLayout


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
    template_path = "reports/base.html"
