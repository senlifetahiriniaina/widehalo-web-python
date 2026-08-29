"""Factories factory_boy pour les modeles du module `automation`."""

from __future__ import annotations

import factory

from apps.automation.models import STEP_TYPE_ACTION, AutoFlow, AutoRun, AutoRunStep, AutoStep


class AutoFlowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AutoFlow

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Flux {n}")
    trigger_event_type = "workflow.transitioned"
    is_active = False


class AutoStepFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AutoStep

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    flow = factory.SubFactory(AutoFlowFactory, tenant=factory.SelfAttribute("..tenant"))
    step_type = STEP_TYPE_ACTION
    config = factory.LazyFunction(lambda: {"action_code": "core.notify_role", "param_mapping": {}})


class AutoRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AutoRun

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    flow = factory.SubFactory(AutoFlowFactory, tenant=factory.SelfAttribute("..tenant"))


class AutoRunStepFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AutoRunStep

    tenant = factory.SubFactory("apps.core.tests.factories.TenantFactory")
    run = factory.SubFactory(AutoRunFactory, tenant=factory.SelfAttribute("..tenant"))
    step = factory.SubFactory(AutoStepFactory, tenant=factory.SelfAttribute("..tenant"))
