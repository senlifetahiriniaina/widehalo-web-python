"""Factories factory_boy pour les modeles du module `core` — une par modele
concret (couche T1 du plan de durcissement, CDC §14 couches).

`TenantFactory` (et `UserFactory`) sont le point d'ancrage dote par les
autres apps via un `SubFactory` a chemin pointe
`"apps.core.tests.factories.TenantFactory"` (resolution paresseuse, permet
l'ecriture parallele des modules). Les modeles socle qui ne referencent pas
`tenant` via une FK (simple `tenant_id`/`UUIDField`, ou pas de notion de
tenant du tout — ex. `StateTransitionLog`, `RoleProfile`) sont traites tels
quels, sans forcer une relation qui n'existe pas dans le modele reel."""

from __future__ import annotations

import datetime
import uuid

import factory
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from apps.core.models.audit import AuditLog
from apps.core.models.document import Document
from apps.core.models.event import EventLog
from apps.core.models.idempotency import IdempotencyKey
from apps.core.models.notification import Notification, WhatsAppMessage
from apps.core.models.rbac import RoleProfile
from apps.core.models.regulatory import CountryDefaultsProfile, RegulatoryParameter
from apps.core.models.risk import CATEGORY_OTHER, RiskItem
from apps.core.models.search import SearchDocument
from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User, UserTenantMembership
from apps.core.models.workflow import (
    ApprovalDelegation,
    ApprovalRequest,
    ApprovalRule,
    StateTransitionLog,
)


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    code = factory.Sequence(lambda n: f"TEN{n}")
    name = factory.Sequence(lambda n: f"Societe {n}")
    country_code = "MG"
    base_currency = "MGA"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create: tuple[str, ...] = ()

    class Params:
        password = "Str0ngPassw0rd!23"

    email = factory.Sequence(lambda n: f"user{n}@example.com")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "Str0ngPassw0rd!23")
        manager = cls._get_manager(model_class)
        return manager.create_user(*args, password=password, **kwargs)


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group

    name = factory.Sequence(lambda n: f"role-{n}")


class RoleProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RoleProfile

    group = factory.SubFactory(GroupFactory)
    code = factory.Sequence(lambda n: f"ROLE{n}")
    description = factory.Sequence(lambda n: f"Role {n}")


class UserTenantMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserTenantMembership

    user = factory.SubFactory(UserFactory)
    tenant = factory.SubFactory(TenantFactory)
    is_default = True


class SavedTableViewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SavedTableView

    tenant = factory.SubFactory(TenantFactory)
    table_key = "partners.list"
    name = factory.Sequence(lambda n: f"Vue {n}")
    owner = factory.SubFactory(UserFactory)


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    tenant = factory.SubFactory(TenantFactory)
    file = factory.django.FileField(filename="document.pdf")
    original_name = "document.pdf"
    mime_type = "application/pdf"
    size = 1024
    sha256 = factory.Sequence(lambda n: f"{n:064d}")


class AuditLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditLog

    tenant_id = factory.LazyFunction(uuid.uuid4)
    action = AuditLog.ACTION_OTHER
    changes = factory.LazyFunction(dict)
    metadata = factory.LazyFunction(dict)


class EventLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EventLog

    tenant_id = factory.LazyFunction(uuid.uuid4)
    event_type = factory.Sequence(lambda n: f"event.type.{n}")
    payload = factory.LazyFunction(dict)


class IdempotencyKeyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = IdempotencyKey

    tenant_id = factory.LazyFunction(uuid.uuid4)
    user_id = factory.LazyFunction(uuid.uuid4)
    key = factory.Sequence(lambda n: f"idem-key-{n}")
    request_hash = factory.Sequence(lambda n: f"hash-{n}")
    response_status = 200
    response_body = "{}"
    expires_at = factory.LazyFunction(
        lambda: datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(hours=1)
    )


class NotificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Notification

    tenant_id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    notification_type = factory.Sequence(lambda n: f"notification.type.{n}")
    payload = factory.LazyFunction(dict)
    channel = Notification.CHANNEL_APP


class WhatsAppMessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WhatsAppMessage

    tenant_id = factory.LazyFunction(uuid.uuid4)
    direction = WhatsAppMessage.DIRECTION_OUTBOUND
    phone_number = "+261340000000"
    body = "Bonjour"


class RegulatoryParameterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RegulatoryParameter

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"PARAM{n}")
    value = factory.LazyFunction(lambda: {"rate": "0.20"})
    valid_from = datetime.date(2026, 1, 1)


class CountryDefaultsProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CountryDefaultsProfile

    country_code = factory.Sequence(lambda n: f"M{n % 10}")
    base_currency = "MGA"
    default_language = "fr"
    timezone = "Indian/Antananarivo"


class SearchDocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchDocument

    tenant_id = factory.LazyFunction(uuid.uuid4)
    content_type = factory.LazyFunction(lambda: ContentType.objects.get_for_model(Tenant))
    object_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    text = factory.Sequence(lambda n: f"Document indexe {n}")


class SequenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Sequence

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"SEQ{n}")
    fiscal_year = 2026


class StateTransitionLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StateTransitionLog

    content_type = factory.LazyFunction(lambda: ContentType.objects.get_for_model(Tenant))
    object_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    field_name = "state"
    from_state = "draft"
    to_state = "confirmed"


class ApprovalRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApprovalRule

    tenant = factory.SubFactory(TenantFactory)
    content_type = factory.LazyFunction(lambda: ContentType.objects.get_for_model(Tenant))
    name = factory.Sequence(lambda n: f"Regle {n}")
    approver_role = "manager"


class ApprovalRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApprovalRequest

    rule = factory.SubFactory(ApprovalRuleFactory)
    content_type = factory.LazyFunction(lambda: ContentType.objects.get_for_model(Tenant))
    object_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    requested_by = factory.SubFactory(UserFactory)


class RiskItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RiskItem

    tenant = factory.SubFactory(TenantFactory)
    category = CATEGORY_OTHER
    likelihood = 2
    impact = 2
    score = 4
    owner = factory.SubFactory(UserFactory)


class ApprovalDelegationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ApprovalDelegation

    delegator = factory.SubFactory(UserFactory)
    delegate = factory.SubFactory(UserFactory)
    valid_from = factory.LazyFunction(lambda: datetime.datetime.now(tz=datetime.UTC))
    valid_to = factory.LazyFunction(
        lambda: datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(days=30)
    )
