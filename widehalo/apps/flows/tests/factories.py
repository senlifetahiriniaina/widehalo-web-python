"""Factories du hub de flux.

Toute sous-factory tenant-scopee HERITE du tenant parent
(`factory.SelfAttribute("..tenant")`), convention du depot etablie par
`apps/catalog/tests/factories.py`. Sans elle, la sous-factory cree son
PROPRE tenant et la Row-Level Security rejette l'insertion sous le contexte
du parent — c'est exactement ce qui s'est produit au premier jet de ce
fichier, et l'erreur (`new row violates row-level security policy`) ne
designe pas la cause.

Une garde du depot (`apps/core/tests/test_tenant_portability_per_entity.py`)
exige une factory par modele heritant de `BaseModel` : sans elle, un test de
portabilite ne peut pas construire l'entite et l'oublie en silence.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import factory

from apps.core.tests.factories import TenantFactory
from apps.flows.models import (
    FlwApiKey,
    FlwConnector,
    FlwConsent,
    FlwCredential,
    FlwExchange,
    FlwIncident,
    FlwLink,
    FlwMapping,
    FlwPayload,
    FlwSchedule,
    FlwTrigger,
)
from apps.flows.operations import (
    OP_PUSH_DOCUMENT,
    OPERATION_CODES,
)


class FlwConnectorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwConnector

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"connecteur-{n}")
    name = "Connecteur de test"
    family = FlwConnector.FAMILY_FISCAL
    # Les HUIT, parce qu'un connecteur de test qui n'en declarerait qu'une
    # ferait echouer tout test parlant d'une autre pour une raison sans
    # rapport avec ce qu'il verifie. Le refus d'une operation non declaree
    # est verifie la ou il compte, sur un connecteur volontairement etroit
    # (`test_s6_operations.py`) — pas par accident, dans vingt tests qui
    # parlent d'autre chose.
    supported_operations = factory.List(sorted(OPERATION_CODES))


class FlwApiKeyFactory(factory.django.DjangoModelFactory):
    """La factory exigee par `test_tenant_portability_per_entity` pour tout
    `BaseModel`. Elle pose une empreinte ARBITRAIRE : une cle construite
    par cette voie n'est utilisable par personne, puisque aucun clair ne lui
    correspond. C'est voulu — emettre une vraie cle passe par
    `services.api_keys.issue_key`, seul endroit ou le clair existe, et une
    factory qui rendrait des cles utilisables en semerait dans tous les
    jeux de donnees de test."""

    class Meta:
        model = FlwApiKey

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory("apps.core.tests.factories.UserFactory")
    label = factory.Sequence(lambda n: f"cle-{n}")
    prefix = factory.Sequence(lambda n: f"wh_test{n:02d}")
    token_hash = factory.Sequence(lambda n: hashlib.sha256(f"factice-{n}".encode()).hexdigest())
    scopes = factory.List([])


class FlwCredentialFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwCredential

    tenant = factory.SubFactory(TenantFactory)
    connector = factory.SubFactory(FlwConnectorFactory, tenant=factory.SelfAttribute("..tenant"))
    label = "Identifiant de test"
    kind = FlwCredential.KIND_API_KEY
    secret = "secret-de-test"


class FlwLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwLink

    tenant = factory.SubFactory(TenantFactory)
    connector = factory.SubFactory(FlwConnectorFactory, tenant=factory.SelfAttribute("..tenant"))
    name = factory.Sequence(lambda n: f"liaison-{n}")


class FlwMappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwMapping

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    document_type = "facture_vente"


class FlwScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwSchedule

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    operation = OP_PUSH_DOCUMENT
    frequency = FlwSchedule.FREQUENCY_DAILY


class FlwTriggerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwTrigger

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    # Un evenement REELLEMENT publie (`core.events.PUBLISHED_EVENT_TYPES`).
    # Le defaut precedent, « sales.order_confirmed », n'existe nulle part :
    # un declencheur construit par cette factory n'aurait jamais pu tirer, et
    # aucun test ne l'aurait dit. `save_trigger` refuse desormais un nom
    # d'evenement non publie (T0) ; la factory, qui court-circuite le
    # service, doit au moins ne pas semer l'inverse.
    event_name = "workflow.transitioned"
    operation = OP_PUSH_DOCUMENT


class FlwExchangeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwExchange

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    direction = FlwExchange.DIRECTION_OUTBOUND
    operation = OP_PUSH_DOCUMENT
    partition_month = factory.LazyFunction(lambda: dt.date.today().replace(day=1))


class FlwPayloadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwPayload

    tenant = factory.SubFactory(TenantFactory)
    exchange = factory.SubFactory(FlwExchangeFactory, tenant=factory.SelfAttribute("..tenant"))
    body = '{"exemple": true}'


class FlwIncidentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FlwIncident

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    family = FlwIncident.FAMILY_UNAVAILABLE
    state = FlwIncident.STATE_OPEN
    first_seen_at = factory.LazyFunction(lambda: dt.datetime.now(tz=dt.UTC))
    last_seen_at = factory.LazyFunction(lambda: dt.datetime.now(tz=dt.UTC))


class FlwConsentFactory(factory.django.DjangoModelFactory):
    """T9 (CON-2) — le consentement de sortie.

    `categories` est laisse VIDE par defaut : un consentement de test qui
    couvrirait d'office toutes les categories rendrait
    `consent_covers_current_scope` toujours vrai, et le gel — tout l'objet
    du modele — cesserait d'etre exerce."""

    class Meta:
        model = FlwConsent

    tenant = factory.SubFactory(TenantFactory)
    link = factory.SubFactory(FlwLinkFactory, tenant=factory.SelfAttribute("..tenant"))
    categories: list[str] = []
    third_party = "Tiers de test"
    country_code = "MG"
    retention_days = 365
    granted_by = factory.SubFactory("apps.core.tests.factories.UserFactory")
    granted_at = factory.LazyFunction(lambda: dt.datetime.now(tz=dt.UTC))
