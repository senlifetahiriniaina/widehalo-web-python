"""Tests securite du portail externe invite (PJ14) — cf. `services/
guest_portal.py` pour la discussion complete du mecanisme. Chaque test de
ce fichier couvre un des points de la checklist securite du plan PJ14 :
resolution valide, expiration, revocation, indiscernabilite des 3 echecs,
isolation cross-tenant sur des donnees REELLES (pas seulement un comptage),
absence de methode d'ecriture a l'URL invite, absence de donnee financiere
sensible/de navigation authentifiee dans la page rendue."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.projects.models import PrjGuestAccess, PrjTask
from apps.projects.services.evm import add_budget_line
from apps.projects.services.guest_portal import (
    create_guest_access,
    get_guest_project_view,
    resolve_guest_access,
    revoke_guest_access,
)
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db

_PAST = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
_FUTURE = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def guest_ctx():
    tenant = Tenant.objects.create(code="PRJ-GUEST-T1", name="Projects Guest Tenant")
    with use_tenant(tenant.id):
        project = create_project(tenant, name="Projet invite")
        task = create_task(tenant, project=project, task_type=PrjTask.TYPE_TASK)
        task.percent_complete = 40
        task.save(update_fields=["percent_complete"])
        milestone = create_task(tenant, project=project, task_type=PrjTask.TYPE_MILESTONE)
        add_budget_line(
            project,
            category="opex",
            label="Ligne sensible",
            planned_amount=Decimal("50000"),
            actual_amount=Decimal("75000"),
            period=dt.date(2026, 1, 1),
        )
        user = User.objects.create_user(
            email="guest-owner@example.com", password="Str0ngPassw0rd!23"
        )
        guest_access = create_guest_access(
            project, guest_email="client@external.example", expires_at=_FUTURE, created_by=user
        )
    yield tenant, project, task, milestone, guest_access, user


# ---------------------------------------------------------------------------
# Service-level : resolution / expiration / revocation
# ---------------------------------------------------------------------------


def test_create_guest_access_generates_secure_token(guest_ctx) -> None:
    tenant, project, _task, _milestone, guest_access, _user = guest_ctx
    assert guest_access.tenant_id == tenant.id
    assert guest_access.project_id == project.id
    # secrets.token_urlsafe(32) -> 43 caracteres, alphabet URL-safe.
    assert len(guest_access.token) >= 32
    assert guest_access.permissions == PrjGuestAccess.PERMISSIONS_READ_ONLY


def test_resolve_guest_access_valid_token_succeeds(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    resolved = resolve_guest_access(guest_access.token)
    assert resolved is not None
    assert resolved.id == guest_access.id


def test_resolve_guest_access_unknown_token_returns_none(guest_ctx) -> None:
    assert resolve_guest_access("this-token-never-existed") is None


def test_resolve_guest_access_empty_token_returns_none(guest_ctx) -> None:
    assert resolve_guest_access("") is None


def test_resolve_guest_access_expired_token_returns_none(guest_ctx) -> None:
    tenant, project, *_ = guest_ctx
    with use_tenant(tenant.id):
        expired = create_guest_access(
            project, guest_email="expired@external.example", expires_at=_PAST
        )
    assert resolve_guest_access(expired.token) is None


def test_resolve_guest_access_future_expiry_is_accepted(guest_ctx) -> None:
    tenant, project, *_ = guest_ctx
    with use_tenant(tenant.id):
        access = create_guest_access(
            project, guest_email="future@external.example", expires_at=_FUTURE
        )
    assert resolve_guest_access(access.token) is not None


def test_resolve_guest_access_revoked_token_returns_none(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    revoke_guest_access(guest_access)
    assert resolve_guest_access(guest_access.token) is None


def test_revoke_guest_access_invalidates_previously_working_token(guest_ctx) -> None:
    """Creation -> l'acces fonctionne -> revocation -> le MEME token ne
    fonctionne plus."""
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    assert resolve_guest_access(guest_access.token) is not None
    revoke_guest_access(guest_access)
    assert resolve_guest_access(guest_access.token) is None


def test_revoke_guest_access_is_idempotent(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    revoke_guest_access(guest_access)
    first_revocation = guest_access.revoked_at
    revoke_guest_access(guest_access)
    guest_access.refresh_from_db()
    assert guest_access.revoked_at == first_revocation


# ---------------------------------------------------------------------------
# Service-level : contenu de la vue invite (exclusion des donnees sensibles)
# ---------------------------------------------------------------------------


def test_get_guest_project_view_excludes_financial_data(guest_ctx) -> None:
    tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    with use_tenant(tenant.id):
        view = get_guest_project_view(guest_access)

    assert "ac" not in view
    assert "eac" not in view
    assert "bac" not in view
    assert "spi" not in view
    assert "cpi" not in view
    for task_row in view["tasks"]:
        assert "budgeted_amount" not in task_row
        assert "custom_fields" not in task_row


def test_get_guest_project_view_exposes_planning_fields(guest_ctx) -> None:
    tenant, project, task, milestone, guest_access, _user = guest_ctx
    with use_tenant(tenant.id):
        view = get_guest_project_view(guest_access)

    assert view["project_name"] == project.name
    task_ids = {row["id"] for row in view["tasks"]}
    assert str(task.id) in task_ids
    assert str(milestone.id) in task_ids
    milestone_ids = {row["id"] for row in view["milestones"]}
    assert str(milestone.id) in milestone_ids
    assert str(task.id) not in milestone_ids
    assert "<svg" in view["gantt_svg"]


# ---------------------------------------------------------------------------
# Isolation cross-tenant — le test le plus important de ce fichier
# ---------------------------------------------------------------------------


def test_resolve_guest_access_never_leaks_across_tenants() -> None:
    tenant_a = Tenant.objects.create(code="PRJ-GUEST-A", name="Tenant A")
    tenant_b = Tenant.objects.create(code="PRJ-GUEST-B", name="Tenant B")

    with use_tenant(tenant_a.id):
        project_a = create_project(tenant_a, name="Projet A confidentiel")
        task_a = create_task(tenant_a, project=project_a, task_type=PrjTask.TYPE_TASK)
        access_a = create_guest_access(
            project_a, guest_email="a@external.example", expires_at=_FUTURE
        )

    with use_tenant(tenant_b.id):
        project_b = create_project(tenant_b, name="Projet B confidentiel")
        task_b = create_task(tenant_b, project=project_b, task_type=PrjTask.TYPE_TASK)
        access_b = create_guest_access(
            project_b, guest_email="b@external.example", expires_at=_FUTURE
        )

    # Le token A resout STRICTEMENT vers le tenant A, jamais B.
    resolved_a = resolve_guest_access(access_a.token)
    assert resolved_a is not None
    assert resolved_a.tenant_id == tenant_a.id
    assert resolved_a.tenant_id != tenant_b.id

    with use_tenant(resolved_a.tenant_id):
        view_a = get_guest_project_view(resolved_a)
    task_ids_a = {row["id"] for row in view_a["tasks"]}
    assert view_a["project_name"] == "Projet A confidentiel"
    assert str(task_a.id) in task_ids_a
    assert str(task_b.id) not in task_ids_a  # contenu reel verifie, pas juste un compte

    # Symetriquement pour B.
    resolved_b = resolve_guest_access(access_b.token)
    assert resolved_b is not None
    assert resolved_b.tenant_id == tenant_b.id
    with use_tenant(resolved_b.tenant_id):
        view_b = get_guest_project_view(resolved_b)
    task_ids_b = {row["id"] for row in view_b["tasks"]}
    assert view_b["project_name"] == "Projet B confidentiel"
    assert str(task_b.id) in task_ids_b
    assert str(task_a.id) not in task_ids_b


# ---------------------------------------------------------------------------
# Vue HTTP anonyme
# ---------------------------------------------------------------------------


def _guest_url(token: str) -> str:
    return reverse("projects:guest_view", args=[token])


def test_guest_http_view_valid_token_renders_project_data(guest_ctx) -> None:
    tenant, project, task, milestone, guest_access, _user = guest_ctx
    client = Client()
    response = client.get(_guest_url(guest_access.token))
    assert response.status_code == 200
    content = response.content.decode()
    assert project.name in content
    assert task.reference in content
    assert milestone.reference in content


def test_guest_http_view_never_exposes_financial_figures(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    client = Client()
    response = client.get(_guest_url(guest_access.token))
    content = response.content.decode()
    assert "75000" not in content
    assert "Ligne sensible" not in content
    assert "EAC" not in content
    assert "SPI" not in content
    assert "CPI" not in content


def test_guest_http_view_has_no_authenticated_navigation(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    client = Client()
    response = client.get(_guest_url(guest_access.token))
    content = response.content.decode()
    assert "app-menu" not in content
    assert "/login/" not in content
    assert "/dashboard/" not in content
    assert "csrfmiddlewaretoken" not in content
    assert "<form" not in content


def test_guest_http_view_unknown_token_returns_404(guest_ctx) -> None:
    client = Client()
    response = client.get(_guest_url("does-not-exist-at-all"))
    assert response.status_code == 404


def test_guest_http_view_expired_token_returns_404(guest_ctx) -> None:
    tenant, project, *_ = guest_ctx
    with use_tenant(tenant.id):
        expired = create_guest_access(
            project, guest_email="expired@external.example", expires_at=_PAST
        )
    client = Client()
    response = client.get(_guest_url(expired.token))
    assert response.status_code == 404


def test_guest_http_view_revoked_token_returns_404(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    revoke_guest_access(guest_access)
    client = Client()
    response = client.get(_guest_url(guest_access.token))
    assert response.status_code == 404


def test_guest_http_view_404_responses_are_indistinguishable(guest_ctx) -> None:
    """Les 3 causes d'echec (introuvable / expire / revoque) doivent
    produire une reponse RIGOUREUSEMENT identique (statut + corps) — un
    attaquant ne doit jamais pouvoir distinguer "ce token n'a jamais
    existe" de "ce token a existe mais a expire/ete revoque"."""
    tenant, project, *_ = guest_ctx
    with use_tenant(tenant.id):
        expired = create_guest_access(
            project, guest_email="expired2@external.example", expires_at=_PAST
        )
        revoked = create_guest_access(
            project, guest_email="revoked2@external.example", expires_at=_FUTURE
        )
    revoke_guest_access(revoked)

    client = Client()
    resp_unknown = client.get(_guest_url("never-existed-token-xyz"))
    resp_expired = client.get(_guest_url(expired.token))
    resp_revoked = client.get(_guest_url(revoked.token))

    assert resp_unknown.status_code == resp_expired.status_code == resp_revoked.status_code == 404
    assert resp_unknown.content == resp_expired.content == resp_revoked.content


def test_guest_http_view_rejects_post(guest_ctx) -> None:
    _tenant, _project, _task, _milestone, guest_access, _user = guest_ctx
    client = Client()
    response = client.post(_guest_url(guest_access.token), {"anything": "1"})
    assert response.status_code == 405


def test_guest_http_view_cross_tenant_isolation_end_to_end() -> None:
    """Meme scenario que le test service `test_resolve_guest_access_never_
    leaks_across_tenants` mais via le CLIENT HTTP anonyme reel, sur le
    contenu de la page rendue — le cas d'attaque le plus realiste."""
    tenant_a = Tenant.objects.create(code="PRJ-GUEST-HTTP-A", name="Tenant HTTP A")
    tenant_b = Tenant.objects.create(code="PRJ-GUEST-HTTP-B", name="Tenant HTTP B")

    with use_tenant(tenant_a.id):
        project_a = create_project(tenant_a, name="Alpha Confidentiel")
        task_a = create_task(tenant_a, project=project_a, task_type=PrjTask.TYPE_TASK)
        access_a = create_guest_access(
            project_a, guest_email="a@external.example", expires_at=_FUTURE
        )

    with use_tenant(tenant_b.id):
        project_b = create_project(tenant_b, name="Beta Confidentiel")
        task_b = create_task(tenant_b, project=project_b, task_type=PrjTask.TYPE_TASK)
        access_b = create_guest_access(
            project_b, guest_email="b@external.example", expires_at=_FUTURE
        )

    # NB : `task.reference` est une sequence PAR TENANT (cf. `services.
    # sequences.next_reference`) — `task_a.reference` et `task_b.reference`
    # valent tous deux "PRJ-TACHE-2026-0001" (comportement attendu, pas une
    # fuite). La preuve d'isolation porte donc sur l'UUID de la tache
    # (`task.id`, globalement unique, jamais reutilise d'un tenant a
    # l'autre) plutot que sur la reference lisible.
    client = Client()
    response_a = client.get(_guest_url(access_a.token))
    content_a = response_a.content.decode()
    assert response_a.status_code == 200
    assert "Alpha Confidentiel" in content_a
    assert str(task_a.id) in content_a
    assert "Beta Confidentiel" not in content_a
    assert str(task_b.id) not in content_a

    response_b = client.get(_guest_url(access_b.token))
    content_b = response_b.content.decode()
    assert response_b.status_code == 200
    assert "Beta Confidentiel" in content_b
    assert str(task_b.id) in content_b
    assert "Alpha Confidentiel" not in content_b
    assert str(task_a.id) not in content_b


# ---------------------------------------------------------------------------
# Vue interne (authentifiee) de gestion des liens invite
# ---------------------------------------------------------------------------


def test_project_guest_links_create_and_revoke_screen(guest_ctx) -> None:
    tenant, project, *_rest, user = guest_ctx
    grant_role(user, "collaborateur")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        f"/projects/{project.id}/guest-links/",
        {
            "action": "create",
            "guest_email": "new-guest@external.example",
            "expires_at": "2099-01-01T00:00",
        },
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 200
    assert b"guest/" in response.content

    with use_tenant(tenant.id):
        created = PrjGuestAccess.objects.get(guest_email="new-guest@external.example")
    guest_client = Client()
    assert guest_client.get(_guest_url(created.token)).status_code == 200

    revoke_response = client.post(
        f"/projects/{project.id}/guest-links/",
        {"action": "revoke", "guest_access_id": str(created.id)},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert revoke_response.status_code == 200
    assert guest_client.get(_guest_url(created.token)).status_code == 404
