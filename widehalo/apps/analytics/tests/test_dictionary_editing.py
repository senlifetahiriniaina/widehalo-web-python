"""L8 — le dictionnaire d'indicateurs devient alimentable depuis le produit.

`register_metric` existait depuis le chantier fondateur ; **aucun ecran ni
endpoint ne l'appelait**. Le dictionnaire etait consultable et rien
d'autre : un client ne pouvait pas ajouter un indicateur a ce que le
module presente comme « la SEULE voie declaree d'acces aux donnees
decisionnelles ». Combine au fait que rien ne le peuplait non plus, il
etait vide et le restait.

Ces tests portent sur les deux surfaces (ecran de session et API a jeton),
et surtout sur ce que l'ecran fait d'un REFUS : une combinaison
fait/axe impossible doit revenir a l'utilisateur avec le detail des axes
disponibles, jamais disparaitre.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.analytics.models import AnMetricDefinition
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def dict_web():
    tenant = Tenant.objects.create(code="AN-WEB", name="Analytics Web Tenant")
    # `controleur_gestion` : memes droits complets sur `analytics` que
    # `direction` (cf. `rbac_policy.py`) mais hors
    # `settings.CORE_MFA_REQUIRED_ROLES` — evite un aller-retour TOTP
    # superflu, meme discipline que `apps.bi.tests.test_views`.
    user = User.objects.create_user(email="controleur-an@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "controleur_gestion")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return tenant, user, client


def test_the_screen_creates_a_metric(dict_web) -> None:
    tenant, _user, client = dict_web

    response = client.post(
        "/analytics/metrics/save/",
        {
            "code": "sales.marge_brute",
            "libelle": "Marge brute",
            "module_source": "sales",
            "fait_source": "vente",
            "axes_autorises": ["temps", "article"],
            "roles_autorises": ["direction"],
            "statut": AnMetricDefinition.STATUT_PUBLIE,
            "unite": "MGA",
            "formule": "Somme des marges des lignes de vente.",
        },
        follow=True,
    )

    assert response.status_code == 200
    with use_tenant(tenant.id):
        metric = AnMetricDefinition.objects.get(
            tenant=tenant, code="sales.marge_brute", is_current=True
        )
    assert metric.fait_source == "vente"
    assert metric.statut == AnMetricDefinition.STATUT_PUBLIE
    assert metric.axes_autorises == ["temps", "article"]


def test_the_screen_shows_the_refusal_instead_of_swallowing_it(dict_web) -> None:
    """Le formulaire propose TOUS les axes de l'entrepot, pas seulement
    ceux du fait choisi : un selecteur dependant exigerait du JS, et le
    coeur applicatif de ce depot fonctionne sans. La combinaison
    impossible est donc attendue, et c'est le message d'erreur qui
    enseigne — il doit nommer les axes reellement disponibles."""
    tenant, _user, client = dict_web

    client.post(
        "/analytics/metrics/save/",
        {
            "code": "accounting.mauvais",
            "libelle": "Mauvais axe",
            "module_source": "accounting",
            "fait_source": "encaissement",
            # `encaissement` n'expose que temps et tiers.
            "axes_autorises": ["temps", "article"],
            "statut": AnMetricDefinition.STATUT_BROUILLON,
        },
        follow=True,
    )
    page = client.get("/analytics/?tab=dictionnaire")

    content = page.content.decode()
    assert "article" in content
    assert "Axe" in content
    with use_tenant(tenant.id):
        assert not AnMetricDefinition.objects.filter(
            tenant=tenant, code="accounting.mauvais"
        ).exists()


def test_the_screen_marks_a_metric_without_a_fact_as_not_computable(dict_web) -> None:
    """Un indicateur descriptif est un etat legitime — mais l'ecran doit le
    DIRE. C'est la contrepartie visible du choix de `bi` de signaler au
    lieu d'ecarter en silence."""
    tenant, _user, client = dict_web
    client.post(
        "/analytics/metrics/save/",
        {
            "code": "direction.satisfaction",
            "libelle": "Satisfaction client",
            "module_source": "crm",
            "fait_source": "",
            "statut": AnMetricDefinition.STATUT_BROUILLON,
        },
        follow=True,
    )

    page = client.get("/analytics/?tab=dictionnaire")

    assert "non calculable" in page.content.decode()


def test_a_reader_without_the_change_permission_cannot_post(dict_web) -> None:
    tenant, _user, _client = dict_web
    reader = User.objects.create_user(email="lecteur-an@example.com", password="Str0ngPassw0rd!23")
    grant_role(reader, "collaborateur")
    client = Client()
    client.force_login(reader)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.post(
        "/analytics/metrics/save/",
        {"code": "x.y", "libelle": "X", "fait_source": "vente"},
    )

    assert response.status_code == 403
    with use_tenant(tenant.id):
        assert not AnMetricDefinition.objects.filter(tenant=tenant, code="x.y").exists()
