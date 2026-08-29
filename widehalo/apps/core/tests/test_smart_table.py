"""§5.11 reporting (chantier `reporting`, verification RPT-GRID1/RPT-SAVE1) :
`SmartTable`/`SavedTableView` etaient deja pleinement conformes a RPT-GRID1
(tri/filtre/pagination/colonnes/export) — RPT-SAVE1 ("vues sauvegardees,
partageables PAR ROLE") ne l'etait qu'a moitie : seul un partage personnel
existait. `shared_with_role` comble ce manque ; ce test verifie que
`visible_saved_views` (utilisee par `smart_table_response`) expose bien les
vues personnelles ET les vues partagees avec un role de l'utilisateur
courant — jamais celles partagees avec un role qu'il n'a pas."""

from __future__ import annotations

import pytest

from apps.core.models.tenant import Tenant
from apps.core.models.ui import SavedTableView
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.core.views.smart_table import visible_saved_views

pytestmark = pytest.mark.django_db


def test_visible_saved_views_includes_own_and_role_shared_but_not_others() -> None:
    tenant = Tenant.objects.create(code="SMT-SHARE", name="SmartTable Sharing Tenant")
    owner = User.objects.create_user(email="smt-owner@example.com", password="Str0ngPassw0rd!23")
    viewer = User.objects.create_user(email="smt-viewer@example.com", password="Str0ngPassw0rd!23")
    grant_role(viewer, "comptable")

    with use_tenant(tenant.id):
        SavedTableView.objects.create(
            tenant=tenant, table_key="core.sample", name="Perso", owner=owner
        )
        SavedTableView.objects.create(
            tenant=tenant,
            table_key="core.sample",
            name="Partagee comptable",
            owner=owner,
            shared_with_role="comptable",
        )
        SavedTableView.objects.create(
            tenant=tenant,
            table_key="core.sample",
            name="Partagee RH",
            owner=owner,
            shared_with_role="rh",
        )

        names = {v.name for v in visible_saved_views(viewer, "core.sample")}

    assert names == {"Partagee comptable"}


def test_visible_saved_views_scopes_by_table_key() -> None:
    tenant = Tenant.objects.create(code="SMT-SCOPE", name="SmartTable Scope Tenant")
    owner = User.objects.create_user(email="smt-scope@example.com", password="Str0ngPassw0rd!23")

    with use_tenant(tenant.id):
        SavedTableView.objects.create(
            tenant=tenant, table_key="core.sample.a", name="A", owner=owner
        )
        SavedTableView.objects.create(
            tenant=tenant, table_key="core.sample.b", name="B", owner=owner
        )

        names = {v.name for v in visible_saved_views(owner, "core.sample.a")}

    assert names == {"A"}
