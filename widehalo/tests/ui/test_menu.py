from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from bs4 import BeautifulSoup
from django.test import Client

pytestmark = pytest.mark.django_db


def test_main_menu_has_at_most_nine_entries() -> None:
    tenant = Tenant.objects.create(code="UI-MENU", name="UI Menu Tenant")
    user = User.objects.create_user(email="ui-menu@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    soup = BeautifulSoup(client.get("/dashboard/").content, "html.parser")
    menu = soup.find("ul", class_="app-menu")
    entries = menu.find_all("li", recursive=False)
    assert len(entries) <= 9
