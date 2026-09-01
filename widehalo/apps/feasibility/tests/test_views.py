from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.feasibility.models import FeaStudy
from apps.feasibility.services.simulation import create_study

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_feasibility():
    tenant = Tenant.objects.create(code="FEA-WEB", name="Feasibility Web Tenant")
    user = User.objects.create_user(
        email="feasibility-web@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(user, "resp_commercial")
    return tenant, user


def test_study_list_screen_renders(web_feasibility) -> None:
    tenant, user = web_feasibility
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/feasibility/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_study_detail_screen_renders_and_add_line(web_feasibility) -> None:
    tenant, user = web_feasibility
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Etude ecran", owner=user, created_by=user)

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    detail_response = client.get(f"/feasibility/{study.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert detail_response.status_code == 200

    add_line_response = client.post(
        f"/feasibility/{study.id}/",
        {
            "action": "add_line",
            "hypothetical_name": "Produit test ecran",
            "assumed_qty": "5",
            "assumed_unit_price_mga": "10000",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert add_line_response.status_code == 200
    with use_tenant(tenant.id):
        assert study.lines.count() == 1


def test_study_create_screen(web_feasibility) -> None:
    tenant, user = web_feasibility
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    create_response = client.post(
        "/feasibility/new/",
        {"name": "Nouvelle etude ecran", "sector_code": "textile"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert create_response.status_code == 302
    assert create_response.url.startswith("/feasibility/wizard/")
    assert create_response.url.endswith("/step2/")


def _login(client: Client, tenant: Tenant, user: User) -> None:
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()


def test_wizard_full_flow_completes_study(web_feasibility) -> None:
    """Parcours bout en bout des 3 etapes de l'assistant guide (UXR6) :
    ne re-teste PAS l'arithmetique de simulation (deja couverte par
    `test_simulation.py`) — verifie uniquement la navigation/redirections
    et que les MEMES fonctions de service deja testees sont bien
    appelees par la coquille de navigation (statut final + marge
    calculee sur la ligne, sans dupliquer les assertions de detail)."""
    tenant, user = web_feasibility
    client = Client()
    _login(client, tenant, user)

    # Etape 1 : creation de l'en-tete.
    step1_response = client.post(
        "/feasibility/new/",
        {"name": "Etude assistant", "sector_code": "textile"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert step1_response.status_code == 302
    with use_tenant(tenant.id):
        study = FeaStudy.objects.get(name="Etude assistant")

    step2_url = f"/feasibility/wizard/{study.id}/step2/"
    step3_url = f"/feasibility/wizard/{study.id}/step3/"

    # Etape 2 : ajout d'une ligne.
    step2_get = client.get(step2_url, HTTP_X_TENANT_ID=str(tenant.id))
    assert step2_get.status_code == 200

    step2_post = client.post(
        step2_url,
        {
            "hypothetical_name": "Produit hypothese assistant",
            "assumed_qty": "10",
            "assumed_unit_price_mga": "5000",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert step2_post.status_code == 200
    with use_tenant(tenant.id):
        assert study.lines.count() == 1
        line = study.lines.get()

    # Etape 3 : simulation de la ligne puis finalisation.
    step3_get = client.get(step3_url, HTTP_X_TENANT_ID=str(tenant.id))
    assert step3_get.status_code == 200

    simulate_response = client.post(
        step3_url,
        {"action": "simulate_line", "line_id": str(line.id)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert simulate_response.status_code == 200
    with use_tenant(tenant.id):
        line.refresh_from_db()
        assert line.computed_margin_pct != 0

    complete_response = client.post(
        step3_url,
        {"action": "complete"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert complete_response.status_code == 302
    assert complete_response.url == f"/feasibility/{study.id}/"

    with use_tenant(tenant.id):
        study.refresh_from_db()
        assert study.status == FeaStudy.STATUS_COMPLETED


def test_wizard_step3_with_no_lines_redirects_to_step2(web_feasibility) -> None:
    """Grille cote serveur (jamais fiee au seul JS cote client) : demander
    l'etape 3 sans aucune ligne doit rediriger vers l'etape 2."""
    tenant, user = web_feasibility
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Etude sans ligne", owner=user, created_by=user)

    client = Client()
    _login(client, tenant, user)

    response = client.get(f"/feasibility/wizard/{study.id}/step3/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 302
    assert response.url == f"/feasibility/wizard/{study.id}/step2/"
