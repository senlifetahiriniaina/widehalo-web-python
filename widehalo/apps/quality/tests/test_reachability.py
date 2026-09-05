"""L11 — le module HACCP devient atteignable.

**L'ecart que ces tests ferment.** `apps.quality` etait livre complet et
teste depuis la Phase 3 — plans de controle, points critiques, mesures,
non-conformites, dossiers de rappel, alerte de controle en retard — et
totalement inatteignable : ni `views.py`, ni `urls.py`, ni `api.py`, donc
aucun montage dans `config/urls.py` ni `config/api.py`, et pas une seule
entree dans `rbac_policy.py`. Un responsable qualite ne pouvait declarer
aucun rappel de lot. C'est l'ecart §3.4 de l'audit.

Les tests des services existaient deja et passaient tous — c'est precisement
ce qui rendait le defaut invisible. Ceux-ci portent donc sur ce qu'aucun
d'eux ne verifiait : que le module est REJOIGNABLE, et par les bons roles.

`resp_production` est utilise plutot qu'`admin` : il n'est pas dans
`settings.CORE_MFA_REQUIRED_ROLES`, ce qui evite le detour MFA sans rapport
avec ce qu'on verifie, et c'est un des roles metier reellement vises."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.quality.models import QltControlPlan

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"


def _access_token(client: Client, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": PASSWORD},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def quality_user():
    tenant = Tenant.objects.create(code="QLT-L11", name="Quality Reachability Tenant")
    user = User.objects.create_user(email="qualite-l11@example.com", password=PASSWORD)
    grant_role(user, "resp_production")
    return tenant, user


@pytest.fixture
def outsider():
    """Un role sans aucun droit sur `quality` — `commercial`. La garde doit
    tenir : monter un module ne doit pas l'ouvrir a tout le monde."""
    tenant = Tenant.objects.create(code="QLT-DENY", name="Quality Deny Tenant")
    user = User.objects.create_user(email="hors-qualite@example.com", password=PASSWORD)
    grant_role(user, "commercial")
    return tenant, user


# ---------------------------------------------------------------------------
# Les ecrans
# ---------------------------------------------------------------------------


def _web_client(user: User, tenant: Tenant) -> Client:
    client = Client()
    assert client.post("/login/", {"email": user.email, "password": PASSWORD}).status_code == 302
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_every_quality_screen_answers(quality_user) -> None:
    """Le test le plus bete du lot, et le seul que personne ne pouvait
    ecrire avant : les quatre ecrans repondent."""
    tenant, user = quality_user
    client = _web_client(user, tenant)

    for name in (
        "quality:control_plan_list",
        "quality:non_conformity_list",
        "quality:recall_list",
    ):
        response = client.get(reverse(name), HTTP_X_TENANT_ID=str(tenant.id))
        assert response.status_code == 200, f"{name} -> {response.status_code}"


def test_the_control_plan_screen_shows_overdue_controls(quality_user) -> None:
    """QUA-9 devient consultable. La commande periodique notifiait ; rien ne
    permettait de REGARDER ce qui etait en retard."""
    tenant, user = quality_user
    client = _web_client(user, tenant)

    response = client.get(reverse("quality:control_plan_list"), HTTP_X_TENANT_ID=str(tenant.id))
    assert "Contr" in response.content.decode()
    assert b"retard" in response.content


def test_a_control_plan_can_be_created_from_the_screen(quality_user) -> None:
    tenant, user = quality_user
    client = _web_client(user, tenant)

    response = client.post(
        reverse("quality:control_plan_list"),
        {"name": "Chaine du froid", "frequency_days": "7", "notes": ""},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert QltControlPlan.objects.filter(name="Chaine du froid").exists()


# ---------------------------------------------------------------------------
# L'API
# ---------------------------------------------------------------------------


def test_the_full_haccp_chain_works_over_the_api(quality_user) -> None:
    """Le parcours complet, depuis l'exterieur : plan, point critique, mesure
    hors limites, non-conformite ouverte automatiquement, refus de liberer le
    lot. Aucune de ces regles n'est verifiee ici — elles sont deja testees
    dans les services ; ce qui est verifie, c'est qu'elles sont ATTEIGNABLES."""
    tenant, user = quality_user
    client = Client()
    headers = _headers(_access_token(client, user.email), str(tenant.id))

    plan = client.post(
        "/api/v1/quality/control-plans",
        {"name": "Cuisson", "frequency_days": 1},
        content_type="application/json",
        **headers,
    )
    assert plan.status_code == 200, plan.content
    plan_id = plan.json()["id"]

    point = client.post(
        f"/api/v1/quality/control-plans/{plan_id}/critical-points",
        {"name": "Temperature a coeur", "unit": "C", "limit_min": "75"},
        content_type="application/json",
        **headers,
    )
    assert point.status_code == 200, point.content
    point_id = point.json()["id"]

    measurement = client.post(
        f"/api/v1/quality/critical-points/{point_id}/measurements",
        {"value": "62", "lot_name": "LOT-CUISSON-1"},
        content_type="application/json",
        **headers,
    )
    assert measurement.status_code == 200, measurement.content
    # 62 < 75 : la mesure est hors limites, l'API doit le dire.
    assert measurement.json()["is_within_limits"] is False

    non_conformities = client.get("/api/v1/quality/non-conformities?state=open", **headers).json()[
        "results"
    ]
    assert len(non_conformities) == 1, non_conformities
    assert non_conformities[0]["lot_name"] == "LOT-CUISSON-1"
    # Ouverte par la mesure et non a la main : la non-conformite pointe vers
    # la mesure qui l'a declenchee. C'est le chainon qui rend la chaine
    # verifiable de bout en bout depuis l'exterieur.
    assert non_conformities[0]["measurement_id"] == measurement.json()["id"]


def test_releasing_a_lot_under_an_open_non_conformity_is_refused(quality_user) -> None:
    """La regle metier passe bien la couche API : un refus reste un refus,
    avec son message, pas une erreur 500."""
    tenant, user = quality_user
    client = Client()
    headers = _headers(_access_token(client, user.email), str(tenant.id))

    client.post(
        "/api/v1/quality/non-conformities",
        {
            "description": "Corps etranger detecte",
            "lot_name": "LOT-NC-1",
            "lot_variant_id": "01a07100-0000-7000-8000-000000000001",
        },
        content_type="application/json",
        **headers,
    )
    response = client.post(
        "/api/v1/quality/lots/release",
        {
            "lot_name": "LOT-NC-1",
            "lot_variant_id": "01a07100-0000-7000-8000-000000000001",
            "reason": "Analyse complementaire favorable",
        },
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 400, response.content
    assert "non-conformité" in response.json()["detail"]


def test_a_role_without_quality_permission_is_refused(outsider) -> None:
    """Monter un module ne l'ouvre pas a tous : `commercial` n'a aucun droit
    sur `quality` et doit rester dehors."""
    tenant, user = outsider
    client = Client()
    headers = _headers(_access_token(client, user.email), str(tenant.id))

    assert client.get("/api/v1/quality/control-plans", **headers).status_code == 403
    assert (
        client.post(
            "/api/v1/quality/recalls",
            {
                "lot_name": "X",
                "lot_variant_id": "01a07100-0000-7000-8000-000000000002",
                "reason": "r",
            },
            content_type="application/json",
            **headers,
        ).status_code
        == 403
    )


# ---------------------------------------------------------------------------
# Les evenements
# ---------------------------------------------------------------------------


def test_opening_a_non_conformity_publishes_an_event(quality_user) -> None:
    """Sans evenement, une non-conformite n'est automatisable par rien — ni
    arret de ligne, ni blocage d'expedition, ni alerte client. Le module n'en
    publiait aucun."""
    tenant, user = quality_user
    with use_tenant(tenant.id):
        from apps.quality.services.public import create_non_conformity

        create_non_conformity(
            tenant=tenant,
            opened_by=user,
            description="Temperature hors limite",
            lot_name="LOT-EVT-1",
        )
        events = EventLog.objects.filter(event_type="quality.non_conformity_opened")
        assert events.count() == 1
        payload = events.first().payload
        assert payload["lot_name"] == "LOT-EVT-1"
        # Ouverture MANUELLE : le drapeau doit distinguer les deux chemins.
        assert payload["from_measurement"] is False


def test_every_published_quality_event_is_declared() -> None:
    """Le registre `PUBLISHED_EVENT_TYPES` existe pour qu'un flux ne
    s'abonne jamais a un evenement qui ne sera jamais publie. L'inverse est
    tout aussi silencieux : un evenement publie mais non declare n'apparait
    dans aucun catalogue d'abonnement."""
    import ast
    from pathlib import Path

    from apps.core.events import PUBLISHED_EVENT_TYPES

    published: set[str] = set()
    services = Path(__file__).resolve().parent.parent / "services"
    for path in services.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "publish_event"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                published.add(node.args[0].value)

    assert published, "Aucun evenement publie trouve — le detecteur est muet."
    assert published <= PUBLISHED_EVENT_TYPES, (
        "Evenement(s) publie(s) par `quality` mais absent(s) de "
        f"`PUBLISHED_EVENT_TYPES` : {sorted(published - PUBLISHED_EVENT_TYPES)}"
    )
