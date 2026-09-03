"""Écrans HTMX du module `bi` — rendu réel, permissions N2."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from apps.analytics.models import AnMetricDefinition
from apps.analytics.services.dictionary import register_metric
from apps.analytics.tests.factories import AnFactVenteFactory
from apps.bi.tests.factories import BiReportFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_bi():
    tenant = Tenant.objects.create(code="BI-WEB", name="BI Web Tenant")
    # `controleur_gestion` (pas `direction`) : memes droits complets sur
    # `bi` (cf. `rbac_policy.py`), mais hors `settings.CORE_MFA_REQUIRED_
    # ROLES` — evite un aller-retour TOTP superflu dans ces tests HTTP,
    # meme discipline que `apps.simulation.tests.test_views`.
    user = User.objects.create_user(email="controleur-bi@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "controleur_gestion")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_dashboard_requires_authentication(web_bi) -> None:
    tenant, _user = web_bi
    response = Client().get("/bi/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code in (302, 401, 403)


def test_dashboard_renders_catalogue_tab(web_bi) -> None:
    tenant, user = web_bi
    with use_tenant(tenant.id):
        BiReportFactory(tenant=tenant, name="Rapport ventes")
    client = _client_for(tenant, user)

    response = client.get("/bi/?tab=catalogue", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"Rapport ventes" in response.content


def test_report_new_requires_add_permission(web_bi) -> None:
    tenant, _user = web_bi
    viewer = User.objects.create_user(email="collab-bi@example.com", password="Str0ngPassw0rd!23")
    grant_role(viewer, "collaborateur")
    client = _client_for(tenant, viewer)

    response = client.get("/bi/reports/new/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 403


def test_report_detail_renders_computed_result(web_bi) -> None:
    tenant, user = web_bi
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("12345"))
        report = BiReportFactory(
            tenant=tenant,
            definition={"metric_codes": ["sales.ca_ht"], "dimensions": [], "filters": []},
        )
    client = _client_for(tenant, user)

    response = client.get(f"/bi/reports/{report.id}/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"12345" in response.content


def test_report_drill_down_endpoint_returns_json(web_bi) -> None:
    tenant, user = web_bi
    with use_tenant(tenant.id):
        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            axes_autorises=["temps"],
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        AnFactVenteFactory(tenant=tenant, montant_ht_mga=Decimal("500"))
        report = BiReportFactory(tenant=tenant)
    client = _client_for(tenant, user)

    response = client.get(
        f"/bi/reports/{report.id}/drill-down/?metric_code=sales.ca_ht&cell_filters=[]",
        HTTP_X_TENANT_ID=str(tenant.id),
    )

    assert response.status_code == 200
    assert response.json()["blocked"] is False
