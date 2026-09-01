"""UXR3 — picker partenaire reutilisable (recherche instantanee) et mode
`?embed=1` de l'assistant de creation de partenaire (composant transversal
consomme plus tard par UXR4/UXR5, jamais cable a un ecran metier ici)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.models import Partner
from apps.partners.services.onboarding import create_partner

pytestmark = pytest.mark.django_db


def _login_with_tenant(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_instant_picker_returns_matching_partners_tenant_scoped() -> None:
    tenant = Tenant.objects.create(code="UXR3-P1", name="Tenant Picker 1")
    other_tenant = Tenant.objects.create(code="UXR3-P2", name="Tenant Picker 2")
    user = User.objects.create_user(email="uxr3-picker@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        create_partner(tenant=tenant, name="Alpha Textile SARL", roles=["client"])
        create_partner(tenant=tenant, name="Beta Cuir SARL", roles=["client"])
    with use_tenant(other_tenant.id):
        create_partner(tenant=other_tenant, name="Alpha Autre Tenant", roles=["client"])

    response = client.get("/partners/instant-picker/", {"q": "alpha"})
    assert response.status_code == 200
    content = response.content.decode()
    assert "Alpha Textile SARL" in content
    assert "Beta Cuir SARL" not in content
    assert "Alpha Autre Tenant" not in content


def test_instant_picker_truncates_to_twenty_results() -> None:
    tenant = Tenant.objects.create(code="UXR3-P3", name="Tenant Picker 3")
    user = User.objects.create_user(
        email="uxr3-picker-many@example.com", password="Str0ngPassw0rd!23"
    )
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        for index in range(25):
            create_partner(tenant=tenant, name=f"Partner {index:02d}", roles=["client"])

    response = client.get("/partners/instant-picker/", {"q": "Partner"})
    assert response.status_code == 200
    assert response.content.decode().count("data-partner-id=") == 20


def test_instant_picker_excludes_inactive_partners() -> None:
    tenant = Tenant.objects.create(code="UXR3-P4", name="Tenant Picker 4")
    user = User.objects.create_user(
        email="uxr3-picker-inactive@example.com", password="Str0ngPassw0rd!23"
    )
    client = _login_with_tenant(tenant, user)

    with use_tenant(tenant.id):
        inactive = create_partner(tenant=tenant, name="Gamma Archive SARL", roles=["client"])
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

    response = client.get("/partners/instant-picker/", {"q": "gamma"})
    assert response.status_code == 200
    assert "Gamma Archive SARL" not in response.content.decode()


def test_wizard_embed_renders_bare_fragments() -> None:
    tenant = Tenant.objects.create(code="UXR3-E1", name="Tenant Embed 1")
    user = User.objects.create_user(email="uxr3-embed@example.com", password="Str0ngPassw0rd!23")
    client = _login_with_tenant(tenant, user)

    step1 = client.get("/partners/new/?embed=1")
    assert step1.status_code == 200
    step1_content = step1.content.decode()
    assert "<html" not in step1_content.lower()
    assert "<body" not in step1_content.lower()
    assert "app-shell" not in step1_content
    assert 'hx-post="/partners/new/?embed=1"' in step1_content

    step2 = client.post("/partners/new/", {"step": "1", "name": "Delta SARL", "embed": "1"})
    assert step2.status_code == 200
    step2_content = step2.content.decode()
    assert "<html" not in step2_content.lower()
    assert "<body" not in step2_content.lower()
    assert "app-shell" not in step2_content


def test_wizard_non_embed_still_renders_full_page() -> None:
    tenant = Tenant.objects.create(code="UXR3-E2", name="Tenant Embed 2")
    user = User.objects.create_user(
        email="uxr3-non-embed@example.com", password="Str0ngPassw0rd!23"
    )
    client = _login_with_tenant(tenant, user)

    step1 = client.get("/partners/new/")
    assert step1.status_code == 200
    assert "<html" in step1.content.decode().lower()


def test_wizard_embed_completion_creates_partner_and_triggers_event() -> None:
    tenant = Tenant.objects.create(code="UXR3-E3", name="Tenant Embed 3")
    user = User.objects.create_user(
        email="uxr3-embed-complete@example.com", password="Str0ngPassw0rd!23"
    )
    client = _login_with_tenant(tenant, user)

    step1 = client.post(
        "/partners/new/",
        {"step": "1", "name": "Epsilon SARL", "nif": "NIF-EPS", "embed": "1"},
    )
    assert step1.status_code == 200

    step2 = client.post(
        "/partners/new/?embed=1",
        {"step": "2", "roles": ["client"], "credit_limit_mga": "1000", "embed": "1"},
    )
    assert step2.status_code == 200
    assert step2.content == b""

    trigger_header = step2.headers.get("HX-Trigger")
    assert trigger_header is not None
    trigger_payload = json.loads(trigger_header)
    assert "wh-partner-created" in trigger_payload
    event_detail = trigger_payload["wh-partner-created"]
    assert event_detail["partner_name"] == "Epsilon SARL"

    with use_tenant(tenant.id):
        partner = Partner.objects.get(id=event_detail["partner_id"])
        assert partner.name == "Epsilon SARL"
        assert partner.nif == "NIF-EPS"
        assert partner.roles == ["client"]


def test_wizard_non_embed_completion_still_redirects_to_detail() -> None:
    tenant = Tenant.objects.create(code="UXR3-E4", name="Tenant Embed 4")
    user = User.objects.create_user(
        email="uxr3-non-embed-complete@example.com", password="Str0ngPassw0rd!23"
    )
    client = _login_with_tenant(tenant, user)

    client.post("/partners/new/", {"step": "1", "name": "Zeta SARL"})
    response = client.post(
        "/partners/new/", {"step": "2", "roles": ["client"], "credit_limit_mga": "0"}
    )
    assert response.status_code == 302
    assert response.url.startswith("/partners/")
    assert "HX-Trigger" not in response.headers


def test_partner_picker_component_renders_with_given_field_and_display_ids() -> None:
    """Preuve que le composant fonctionne de maniere standalone (hors
    integration CRM/Ventes, deliberement hors perimetre UXR3) : un
    template hote minimal l'inclut avec des ids arbitraires et on verifie
    que ce sont bien ceux-la qui apparaissent dans le HTML rendu."""
    from django.template import Context, Template

    template = Template(
        '{% include "components/_partner_picker.html" with '
        'field_id="partner_id" display_id="partner_id_display" %}'
    )
    rendered = template.render(Context({}))

    assert 'id="partner_id"' in rendered
    assert 'name="partner_id"' in rendered
    assert 'id="partner_id_display"' in rendered
    assert 'data-field-id="partner_id"' in rendered
    assert 'data-display-id="partner_id_display"' in rendered
    assert "/partners/instant-picker/" in rendered
    assert "/partners/new/?embed=1" in rendered
