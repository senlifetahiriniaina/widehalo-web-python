"""AUTO3 : `apps.helpdesk.services.automation_registration` —
`helpdesk.create_ticket_from_event`, LE mecanisme concret de « connexion
native aux operations » (cf. plan, section dediee). Verifie explicitement :
resolution du demandeur de repli (premier superutilisateur du tenant),
rattachement generique reussi ET rattachement degrade proprement (jamais
d'exception) sur un `content_type_label` invalide/introuvable, resolution
`ticket_type` par correspondance sur `related_content_type`."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.automation_registry import get_registered_action
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.helpdesk.models import KIND_INCIDENT, HlpTicket
from apps.helpdesk.services.automation_registration import _create_ticket_from_event
from apps.helpdesk.tests.factories import HlpTicketTypeCatalogFactory

pytestmark = pytest.mark.django_db


def test_action_is_registered_in_the_shared_registry() -> None:
    registered = get_registered_action("helpdesk.create_ticket_from_event")
    assert registered is not None
    assert registered.module == "helpdesk"
    assert registered.function is _create_ticket_from_event
    assert "content_type_label" in registered.param_schema


def test_creates_ticket_with_fallback_superuser_requester() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-1", name="Helpdesk AUTO3 Tenant 1")
    with use_tenant(tenant.id):
        superuser = UserFactory(is_superuser=True)

        reference = _create_ticket_from_event(str(tenant.id), {"subject": "Panne detectee"})

        ticket = HlpTicket.objects.get(tenant=tenant)
        assert ticket.reference == reference
        assert ticket.requester_id == superuser.id
        assert ticket.kind == KIND_INCIDENT
        assert ticket.subject == "Panne detectee"
        assert ticket.content_type is None
        assert ticket.ticket_type is None


def test_default_subject_when_missing() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-2", name="Helpdesk AUTO3 Tenant 2")
    with use_tenant(tenant.id):
        UserFactory(is_superuser=True)

        _create_ticket_from_event(str(tenant.id), {})

        ticket = HlpTicket.objects.get(tenant=tenant)
        assert ticket.subject  # repli non vide, jamais un sujet blanc


def test_raises_when_no_superuser_available() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-3", name="Helpdesk AUTO3 Tenant 3")
    with use_tenant(tenant.id), pytest.raises(ValueError):
        _create_ticket_from_event(str(tenant.id), {"subject": "Sans demandeur"})

    assert not HlpTicket.objects.filter(tenant=tenant).exists()


def test_never_raises_on_garbage_content_type_label() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-4", name="Helpdesk AUTO3 Tenant 4")
    with use_tenant(tenant.id):
        UserFactory(is_superuser=True)

        reference = _create_ticket_from_event(
            str(tenant.id),
            {
                "subject": "Evenement mal forme",
                "content_type_label": "not-a-real-label",
                "object_id": "1234",
            },
        )

        ticket = HlpTicket.objects.get(reference=reference)
        assert ticket.content_type is None
        assert ticket.ticket_type is None


def test_never_raises_on_unknown_app_model_label() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-5", name="Helpdesk AUTO3 Tenant 5")
    with use_tenant(tenant.id):
        UserFactory(is_superuser=True)

        reference = _create_ticket_from_event(
            str(tenant.id),
            {
                "subject": "Module inexistant",
                "content_type_label": "not_a_real_app.NotAModel",
                "object_id": "1234",
            },
        )

        ticket = HlpTicket.objects.get(reference=reference)
        assert ticket.content_type is None


def test_resolves_ticket_type_by_matching_related_content_type() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-6", name="Helpdesk AUTO3 Tenant 6")
    with use_tenant(tenant.id):
        from django.contrib.contenttypes.models import ContentType

        UserFactory(is_superuser=True)
        other_tenant_user = UserFactory()
        content_type = ContentType.objects.get_for_model(other_tenant_user.__class__)
        ticket_type = HlpTicketTypeCatalogFactory(tenant=tenant, related_content_type=content_type)

        reference = _create_ticket_from_event(
            str(tenant.id),
            {
                "subject": "Rattache",
                "content_type_label": f"{content_type.app_label}.{content_type.model}",
                "object_id": str(other_tenant_user.id),
            },
        )

        ticket = HlpTicket.objects.get(reference=reference)
        assert ticket.content_type_id == content_type.id
        assert ticket.object_id == str(other_tenant_user.id)
        assert ticket.ticket_type_id == ticket_type.id


def test_no_ticket_type_match_leaves_ticket_type_none() -> None:
    tenant = Tenant.objects.create(code="HLP-AUTO3-7", name="Helpdesk AUTO3 Tenant 7")
    with use_tenant(tenant.id):
        from django.contrib.contenttypes.models import ContentType

        UserFactory(is_superuser=True)
        other_user = UserFactory()
        content_type = ContentType.objects.get_for_model(other_user.__class__)
        # Aucun `HlpTicketTypeCatalog` ne declare ce `related_content_type`
        # pour ce tenant -> aucune supposition hasardeuse, `ticket_type`
        # reste `None`.
        reference = _create_ticket_from_event(
            str(tenant.id),
            {
                "subject": "Sans correspondance de type",
                "content_type_label": f"{content_type.app_label}.{content_type.model}",
                "object_id": str(other_user.id),
            },
        )

        ticket = HlpTicket.objects.get(reference=reference)
        assert ticket.content_type_id == content_type.id
        assert ticket.ticket_type is None
