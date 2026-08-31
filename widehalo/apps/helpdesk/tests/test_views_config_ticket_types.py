"""Ecran d'administration du catalogue de types de tickets
(`config_ticket_types`) et message d'etat vide sur l'ecran de creation de
ticket — cf. plan section "catalogue de tickets helpdesk vide par
defaut"."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.helpdesk.models import HlpTicketTypeCatalog
from apps.helpdesk.services.catalog_loader import load_ticket_type_catalog

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_helpdesk():
    tenant = Tenant.objects.create(code="HLP-WEB", name="Helpdesk Web Tenant")
    user = User.objects.create_user(email="helpdesk-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "collaborateur")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return tenant, user, client


def test_config_ticket_types_screen_lists_existing_entries(web_helpdesk) -> None:
    tenant, _user, client = web_helpdesk
    with use_tenant(tenant.id):
        load_ticket_type_catalog(tenant)

    response = client.get("/helpdesk/config/ticket-types/")
    assert response.status_code == 200
    assert b"stock" in response.content.lower()


def test_config_ticket_types_screen_creates_head_entry(web_helpdesk) -> None:
    tenant, _user, client = web_helpdesk

    response = client.post(
        "/helpdesk/config/ticket-types/",
        {
            "code": "custom.entry",
            "label": "Entree personnalisee",
            "kind": "incident",
            "sector_code": "",
            "related_module": "",
            "parent_id": "",
        },
    )
    assert response.status_code == 200

    with use_tenant(tenant.id):
        assert HlpTicketTypeCatalog.objects.filter(tenant=tenant, code="custom.entry").exists()


def test_ticket_create_screen_shows_empty_state_message_when_catalog_empty(web_helpdesk) -> None:
    _tenant, _user, client = web_helpdesk

    response = client.get("/helpdesk/new/")
    assert response.status_code == 200
    assert "Aucun type de ticket configure" in response.content.decode()
    assert "disabled" in response.content.decode()


def test_ticket_create_screen_hides_empty_state_message_once_catalog_loaded(web_helpdesk) -> None:
    tenant, _user, client = web_helpdesk
    with use_tenant(tenant.id):
        load_ticket_type_catalog(tenant)

    response = client.get("/helpdesk/new/")
    assert response.status_code == 200
    assert "Aucun type de ticket configure" not in response.content.decode()
