from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.strategy.models import StgObjective
from apps.strategy.services.objectives import create_objective

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_strategy():
    tenant = Tenant.objects.create(code="STG-WEB", name="Strategy Web Tenant")
    user = User.objects.create_user(email="strategy-web@example.com", password="Str0ngPassw0rd!23")
    # "collaborateur" n'est pas dans CORE_MFA_REQUIRED_ROLES — meme choix
    # que `apps.presence.tests.test_views` pour un simple test d'ecran.
    grant_role(user, "collaborateur")
    return tenant, user


@pytest.fixture
def web_pilotage():
    # "controleur_gestion" a view/add/change sur `strategy` (cf. rbac_
    # policy) et n'est pas dans CORE_MFA_REQUIRED_ROLES — meme choix que
    # documente dans le plan/summary de ce chantier.
    tenant = Tenant.objects.create(code="STG-PIL", name="Strategy Pilotage Tenant")
    user = User.objects.create_user(email="pilotage-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "controleur_gestion")
    return tenant, user


def _logged_client(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_objective_list_screen_renders(web_strategy) -> None:
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/strategy/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200


def test_objective_detail_screen_renders(web_strategy) -> None:
    tenant, user = web_strategy
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif ecran",
            level=StgObjective.LEVEL_COMPANY,
            period_start="2026-01-01",
            period_end="2026-12-31",
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/strategy/{objective.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert "Objectif ecran" in response.content.decode()


def test_capacity_outlook_screen_renders(web_strategy) -> None:
    """CAP1-2 (cf. plan) : ecran HTMX minimal du tableau capacite-vs-charge."""
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get("/strategy/capacity/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert "Capacité" in response.content.decode()


def test_capacity_outlook_screen_accepts_custom_horizon(web_strategy) -> None:
    tenant, user = web_strategy
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(
        "/strategy/capacity/", {"horizon_days": "14"}, HTTP_X_TENANT_ID=str(tenant.id)
    )

    assert response.status_code == 200


def test_pilotage_screen_requires_login() -> None:
    """`strategy` accorde `view`/`add`/`change` a l'ensemble des 13 roles
    (RBAC per-app, cf. `docs/RBAC.md` §3.1 et le commentaire dedie dans
    `rbac_policy.py`) : aucun role existant ne peut donc jamais recevoir un
    403 sur cet ecran — la seule frontiere d'acces reelle qui tient est
    l'authentification elle-meme (`@login_required`, redirection vers la
    connexion)."""
    tenant = Tenant.objects.create(code="STG-PIL-ANON", name="Strategy Anon Tenant")
    client = Client()

    response = client.get("/strategy/pilotage/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 302
    assert "/login" in response.url or "accounts" in response.url


def test_pilotage_budget_tab_renders(web_pilotage) -> None:
    tenant, user = web_pilotage
    client = _logged_client(tenant, user)

    response = client.get("/strategy/pilotage/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert "Pilotage" in response.content.decode()


def test_pilotage_create_lock_and_revise_budget_flow(web_pilotage) -> None:
    tenant, user = web_pilotage
    client = _logged_client(tenant, user)

    create_response = client.post(
        "/strategy/pilotage/budgets/new/",
        {
            "name": "Budget ecran",
            "source": "manual",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert create_response.status_code == 302

    with use_tenant(tenant.id):
        from apps.strategy.models import StgBudget

        budget = StgBudget.objects.get(tenant=tenant, name="Budget ecran")
        assert budget.is_locked is False

    lock_response = client.post(
        f"/strategy/pilotage/budgets/{budget.id}/lock/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert lock_response.status_code == 302
    budget.refresh_from_db()
    assert budget.is_locked is True

    revise_response = client.post(
        f"/strategy/pilotage/budgets/{budget.id}/revise/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert revise_response.status_code == 302
    with use_tenant(tenant.id):
        assert StgBudget.objects.filter(tenant=tenant, name="Budget ecran").count() == 2


def test_pilotage_initiative_create_opens_chatter_channel(web_pilotage) -> None:
    tenant, user = web_pilotage
    with use_tenant(tenant.id):
        objective = create_objective(
            tenant,
            title="Objectif pour initiative",
            level=StgObjective.LEVEL_COMPANY,
            period_start="2026-01-01",
            period_end="2026-12-31",
        )
    client = _logged_client(tenant, user)

    response = client.post(
        "/strategy/pilotage/initiatives/new/",
        {"objective_id": str(objective.id), "title": "Initiative ecran"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        from apps.strategy.models import StgInitiative

        initiative = StgInitiative.objects.get(tenant=tenant, title="Initiative ecran")

        from apps.chat.models import ChatChannel

        assert ChatChannel.objects.filter(tenant=tenant, object_id=str(initiative.id)).exists()


def test_pilotage_risk_create_and_reassess_flow(web_pilotage) -> None:
    tenant, user = web_pilotage
    client = _logged_client(tenant, user)

    create_response = client.post(
        "/strategy/pilotage/risks/new/",
        {"title": "Risque ecran", "probability": "3", "impact": "4"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert create_response.status_code == 302

    with use_tenant(tenant.id):
        from apps.strategy.models import StgRisk

        risk = StgRisk.objects.get(tenant=tenant, title="Risque ecran")
        assert risk.risk_score == 12
        assert risk.last_reassessed_at is None

    reassess_response = client.post(
        f"/strategy/pilotage/risks/{risk.id}/reassess/",
        {"probability": "5", "impact": "5", "control_measure": "Mesure ajoutee"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert reassess_response.status_code == 302
    risk.refresh_from_db()
    assert risk.risk_score == 25
    assert risk.last_reassessed_at is not None


def test_pilotage_review_pack_generate_and_detail_screen(web_pilotage) -> None:
    tenant, user = web_pilotage
    client = _logged_client(tenant, user)

    generate_response = client.post(
        "/strategy/pilotage/review-packs/new/",
        {"period_start": "2026-01-01", "period_end": "2026-03-31"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert generate_response.status_code == 302

    with use_tenant(tenant.id):
        from apps.strategy.models import StgReviewPack

        pack = StgReviewPack.objects.get(tenant=tenant)

    detail_response = client.get(
        f"/strategy/pilotage/review-packs/{pack.id}/", HTTP_X_TENANT_ID=str(tenant.id)
    )
    assert detail_response.status_code == 200
    assert "Pack de revue" in detail_response.content.decode()


def test_objective_activate_screen_accepts_measurable_objective(web_pilotage) -> None:
    """`activate_objective` reste une porte de validation pure (`status`
    est TOUJOURS calcule, jamais force par l'activation, cf. docstring
    `services/objectives.py`) — l'ecran redirige avec succes, sans que le
    statut affiche devienne "active"."""
    tenant, user = web_pilotage
    with use_tenant(tenant.id):
        from apps.analytics.models import AnMetricDefinition
        from apps.analytics.services.dictionary import register_metric
        from apps.strategy.services.objectives import add_key_result

        register_metric(
            tenant,
            code="sales.ca_ht",
            libelle="CA HT",
            module_source="sales",
            statut=AnMetricDefinition.STATUT_PUBLIE,
        )
        # Niveau individuel : n'importe quel role peut gerer son propre
        # objectif (cf. `services/scoping.py::assert_can_manage_level`),
        # contrairement au niveau entreprise reserve a admin/direction.
        objective = create_objective(
            tenant,
            title="Objectif ecran activable",
            level=StgObjective.LEVEL_INDIVIDUAL,
            owner=user,
            period_start="2026-01-01",
            period_end="2026-12-31",
        )
        add_key_result(
            objective,
            metric_name="CA MGA",
            target_value=Decimal("1000000"),
            metric_code="sales.ca_ht",
        )
        assert objective.status == StgObjective.STATUS_AT_RISK
    client = _logged_client(tenant, user)

    response = client.post(f"/strategy/{objective.id}/activate/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 302

    objective.refresh_from_db()
    assert objective.status == StgObjective.STATUS_AT_RISK
