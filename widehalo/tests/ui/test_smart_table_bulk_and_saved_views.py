"""Actions de masse + vues sauvegardees (Sprint 2 / L1 de la refonte UX,
cf. docs/planning/2026-refonte-ux-sprints.md §5) : extension additive de
`apps.core.views.smart_table` -- meme idiome de connexion que
`tests/ui/test_smart_table.py`."""

from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User
from apps.core.tests.factories import DocumentFactory, SavedTableViewFactory
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> tuple[Client, Tenant, User]:
    tenant = Tenant.objects.create(code="UI-BULK", name="UI Bulk Tenant")
    user = User.objects.create_user(email="ui-bulk@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user


def test_documents_list_renders_bulk_action_checkboxes() -> None:
    client, tenant, _user = _logged_in_client()
    with use_tenant(tenant.id):
        DocumentFactory(tenant=tenant, original_name="facture.pdf")

    response = client.get("/documents/")
    body = response.content.decode()
    assert 'name="ids"' in body
    assert "Archiver la sélection" in body


def test_bulk_archive_soft_deletes_selected_documents_only() -> None:
    client, tenant, _user = _logged_in_client()
    with use_tenant(tenant.id):
        keep = DocumentFactory(tenant=tenant, original_name="a-garder.pdf")
        archive = DocumentFactory(tenant=tenant, original_name="a-archiver.pdf")

    response = client.post("/documents/bulk-archive/", {"ids": [str(archive.id)]})
    assert response.status_code == 302

    keep.refresh_from_db()
    archive.refresh_from_db()
    assert keep.is_active is True
    assert archive.is_active is False
    assert archive.archived_at is not None

    body = client.get("/documents/").content.decode()
    assert "a-garder.pdf" in body
    assert "a-archiver.pdf" not in body


def test_bulk_archive_requires_post() -> None:
    client, _tenant, _user = _logged_in_client()
    response = client.get("/documents/bulk-archive/")
    assert response.status_code == 405


def test_save_current_view_creates_saved_table_view() -> None:
    client, tenant, user = _logged_in_client()

    response = client.post(
        "/smart-table/save-view/",
        {
            "table_key": "core.documents",
            "name": "Mes documents récents",
            "q": "facture",
            "sort": "-created_at",
            "next": "/documents/",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == "/documents/"

    with use_tenant(tenant.id):
        view = SavedTableView.objects.get(table_key="core.documents", owner=user)
        assert view.name == "Mes documents récents"
        assert view.filters == {"q": "facture"}
        assert view.sort == "-created_at"


def test_save_current_view_requires_table_key_and_name() -> None:
    client, _tenant, _user = _logged_in_client()
    response = client.post("/smart-table/save-view/", {"table_key": "", "name": ""})
    assert response.status_code == 400


def test_saved_view_appears_in_selector() -> None:
    client, tenant, user = _logged_in_client()
    SavedTableViewFactory(tenant=tenant, table_key="core.documents", name="Ma vue", owner=user)

    body = client.get("/documents/").content.decode()
    assert "Ma vue" in body
