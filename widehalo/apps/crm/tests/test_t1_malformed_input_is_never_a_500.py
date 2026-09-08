"""T1 (côté `crm`) — trois opérations rendaient 500, et la première le
faisait sur une entrée parfaitement valide.

`POST /crm/leads` échouait non pas sur une entrée malformée mais sur une
SOCIÉTÉ NEUVE : `create_lead_quick` levait `ValueError` quand aucun tunnel
de vente n'existait, et le tunnel par défaut n'était posé que par une
commande de déploiement lancée à la main. Toute première opportunité d'une
société fraîchement créée rendait donc « une erreur inattendue est
survenue ». C'est le pire des cas — un 500 sur le parcours d'accueil.

Les deux rapports, eux, étaient le défaut de format partagé par 41
endpoints du dépôt : `format: str` laissait passer n'importe quelle valeur
jusqu'au dictionnaire de types MIME, qui levait un `KeyError` sec.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.crm.models import CrmLead, CrmPipeline

pytestmark = pytest.mark.django_db

MOT_DE_PASSE = "Str0ngPassw0rd!23"  # noqa: S105 — mot de passe de test.


@pytest.fixture
def api():
    tenant = Tenant.objects.create(code="T1-CRM", name="Première opportunité SARL")
    user = User.objects.create_user(email="t1-crm@example.com", password=MOT_DE_PASSE)
    grant_role(user, "commercial")
    client = Client()
    jeton = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": MOT_DE_PASSE},
        content_type="application/json",
    ).json()["access"]
    entetes = {"HTTP_AUTHORIZATION": f"Bearer {jeton}", "HTTP_X_TENANT_ID": str(tenant.id)}
    return client, entetes, tenant


def test_the_very_first_lead_of_a_brand_new_company_succeeds(api) -> None:
    """LE défaut, et il n'a rien d'un cas limite : une société neuve n'a
    aucun tunnel, et c'est son état NORMAL.

    Le tunnel par défaut à sept étapes est créé à la volée — `ensure_
    default_pipeline` existait depuis L4, idempotente, et n'était appelée
    que par une commande de déploiement."""
    client, entetes, tenant = api
    with use_tenant(tenant.id):
        assert not CrmPipeline.objects.filter(tenant=tenant).exists(), (
            "La société de test n'est pas neuve : le défaut mesuré ici ne "
            "peut pas se produire, et ce test passerait pour rien."
        )

    reponse = client.post(
        "/api/v1/crm/leads",
        {"name": "Première affaire"},
        content_type="application/json",
        **entetes,
    )
    assert reponse.status_code in {200, 201}, (
        f"La première opportunité d'une société neuve rend "
        f"{reponse.status_code} : {reponse.content[:300]!r}"
    )
    with use_tenant(tenant.id):
        assert CrmLead.objects.count() == 1
        assert CrmPipeline.objects.filter(tenant=tenant, is_default=True).exists()


def test_a_pipeline_without_any_stage_is_refused_with_its_reason(api) -> None:
    """Le cas qui subsiste, et qui doit rester lisible : un tunnel créé à la
    main sans étape. `ValidationError` — donc 422 avec son message — et non
    `ValueError`, qui ressortait en 500 muet."""
    from django.core.exceptions import ValidationError

    from apps.crm.services.leads import create_lead_quick

    _client, _entetes, tenant = api
    with use_tenant(tenant.id):
        vide = CrmPipeline.objects.create(tenant=tenant, name="Tunnel vide", is_default=True)
        with pytest.raises(ValidationError) as refus:
            create_lead_quick(tenant=tenant, name="Affaire", pipeline=vide)
    assert "Tunnel vide" in " ".join(refus.value.messages)


@pytest.mark.parametrize(
    "chemin",
    ["/api/v1/crm/reports/activities", "/api/v1/crm/reports/lost"],
)
def test_an_export_format_outside_the_menu_is_refused_not_crashed(api, chemin: str) -> None:
    """`format: str` laissait la valeur atteindre `{...}[format]`, qui levait
    `KeyError` — un 500 pour « pdf », qui est simplement hors du menu de ces
    rapports."""
    client, entetes, _tenant = api
    reponse = client.get(f"{chemin}?format=pdf", **entetes)
    assert reponse.status_code == 422, (
        f"{chemin} rend {reponse.status_code} sur un format hors menu : {reponse.content[:200]!r}"
    )


@pytest.mark.parametrize(
    "chemin",
    ["/api/v1/crm/reports/activities", "/api/v1/crm/reports/lost"],
)
def test_the_three_formats_of_the_menu_still_work(api, chemin: str) -> None:
    """Le témoin. Sans lui, refuser TOUS les formats donnerait le même vert
    que refuser les bons."""
    client, entetes, _tenant = api
    for format_ in ("json", "csv", "xlsx"):
        reponse = client.get(f"{chemin}?format={format_}", **entetes)
        assert reponse.status_code == 200, f"{chemin}?format={format_} -> {reponse.status_code}"
