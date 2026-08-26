from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from bs4 import BeautifulSoup
from django.test import Client

pytestmark = pytest.mark.django_db


def _logged_in_client() -> Client:
    tenant = Tenant.objects.create(code="UI-A11Y", name="UI A11y Tenant")
    user = User.objects.create_user(email="ui-a11y@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_dashboard_declares_a_language() -> None:
    client = _logged_in_client()
    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    assert soup.html is not None
    assert soup.html.get("lang")


def test_login_page_inputs_all_have_labels() -> None:
    soup = BeautifulSoup(Client().get("/login/").content, "html.parser")
    labelled_ids = {label.get("for") for label in soup.find_all("label") if label.get("for")}
    for field in soup.find_all(["input", "select", "textarea"]):
        if field.get("type") == "hidden" or field.get("type") == "csrfmiddlewaretoken":
            continue
        assert field.get("id") in labelled_ids or field.get("aria-label"), (
            f"Champ sans label associe : {field}"
        )


def test_search_page_input_has_a_label() -> None:
    client = _logged_in_client()
    soup = BeautifulSoup(client.get("/search/").content, "html.parser")
    labelled_ids = {label.get("for") for label in soup.find_all("label") if label.get("for")}
    search_input = soup.find("input", {"name": "q"})
    assert search_input is not None
    assert search_input.get("id") in labelled_ids
