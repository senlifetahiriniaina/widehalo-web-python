from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.financing.models import FinLoanApplication
from apps.financing.services.credoc import create_credoc
from apps.financing.services.loan_applications import create_loan_application

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_financing():
    tenant = Tenant.objects.create(code="FIN-WEB", name="Financing Web Tenant")
    user = User.objects.create_user(email="financing-web@example.com", password="Str0ngPassw0rd!23")
    # "collaborateur" n'est pas dans CORE_MFA_REQUIRED_ROLES (contrairement a
    # "admin"/"direction"/"comptable", les 3 seuls roles reellement scopes
    # sur `financing`) — meme choix que `apps.strategy.tests.test_views`
    # pour un simple test de rendu d'ecran (les vues HTMX ne verifient que
    # `@login_required`, pas de RBAC N2, meme discipline que
    # `apps.purchase.views`/`apps.payroll.views`).
    grant_role(user, "collaborateur")
    return tenant, user


def test_loan_application_list_screen_renders(web_financing) -> None:
    tenant, user = web_financing
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/financing/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_loan_application_detail_screen_renders(web_financing) -> None:
    tenant, user = web_financing
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type=FinLoanApplication.LOAN_TYPE_OPERATING,
            amount_requested_mga=Decimal("2000000"),
            duration_months=6,
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/financing/{application.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_credoc_list_screen_renders(web_financing) -> None:
    tenant, user = web_financing
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/financing/credocs/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_credoc_detail_screen_renders(web_financing) -> None:
    tenant, user = web_financing
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur",
            amount_mga=Decimal("10000000"),
            validity_date=dt.date(2026, 12, 31),
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/financing/credocs/{credoc.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_credoc_dossier_timeline_screen_renders(web_financing) -> None:
    """B2 : nouvel écran composite lecture-seule."""
    tenant, user = web_financing
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur",
            amount_mga=Decimal("10000000"),
            validity_date=dt.date(2026, 12, 31),
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(
        f"/financing/credocs/{credoc.id}/dossier/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert response.status_code == 200


def test_credoc_detail_transition_requires_a_reason(web_financing) -> None:
    """B2 : le formulaire HTML omettant le motif doit re-rendre la page
    avec une erreur (302 -> refus, jamais une transition silencieuse sans
    motif) — même round-trip HTTP réel que le reste de ce dépôt pour un
    garde-fou métier."""
    tenant, user = web_financing
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur",
            amount_mga=Decimal("10000000"),
            validity_date=dt.date(2026, 12, 31),
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/financing/credocs/{credoc.id}/",
        {"action": "open", "reason": ""},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"motif" in response.content.lower() or b"obligatoire" in response.content.lower()

    response = client.post(
        f"/financing/credocs/{credoc.id}/",
        {"action": "open", "reason": "Accord de la banque émettrice reçu"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        credoc.refresh_from_db()
        assert credoc.state == "ouvert"
