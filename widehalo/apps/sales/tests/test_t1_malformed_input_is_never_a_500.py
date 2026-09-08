"""T1 — une entrée malformée rend 422, jamais 500.

**Le critère, et il ne souffre pas d'exception.** Le cahier de la Phase 4
décrit le premier de ses trois profils nouveaux, le système tiers, en ces
termes : « Appelle l'API publique ou reçoit une notification. Ne lit aucune
documentation contextuelle, ne devine rien, ne pardonne rien. » Ce qu'on lui
doit en retour : « des codes d'erreur explicites ». Un 500 n'en est pas un —
il dit « le produit est cassé » là où la vérité est « votre demande n'entre
pas dans le menu ».

**Ce que ces tests reproduisent, et pourquoi il fallait Hypothesis pour le
trouver.** Reproduire à la main donnait 422 : un développeur qui teste
`partner_id` tape un UUID, éventuellement un UUID inexistant, jamais
`"\\x00"` ni une chaîne de deux cents caractères. La campagne de contrat,
elle, génère précisément cela — et c'est ainsi que quatre opérations de
`sales` et trois de `crm` ont été mesurées à 500. Les cas ci-dessous sont
ces entrées-là, figées : une fois trouvées, elles n'ont plus besoin d'être
générées.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role
from apps.sales.models import SalesTarget

pytestmark = pytest.mark.django_db

MOT_DE_PASSE = "Str0ngPassw0rd!23"  # noqa: S105 — mot de passe de test.


@pytest.fixture
def api():
    tenant = Tenant.objects.create(code="T1-SALES", name="Entrées malformées SARL")
    user = User.objects.create_user(email="t1-sales@example.com", password=MOT_DE_PASSE)
    grant_role(user, "commercial")
    client = Client()
    jeton = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": MOT_DE_PASSE},
        content_type="application/json",
    ).json()["access"]
    entetes = {"HTTP_AUTHORIZATION": f"Bearer {jeton}", "HTTP_X_TENANT_ID": str(tenant.id)}
    return client, entetes, tenant


def _post(api, chemin, corps):
    client, entetes, _tenant = api
    return client.post(chemin, corps, content_type="application/json", **entetes)


def test_a_partner_id_that_is_not_a_uuid_is_refused_not_crashed(api) -> None:
    """`uuid.UUID(payload.partner_id)` sur un champ déclaré `str` : la
    chaîne traversait la validation de schéma puis levait `ValueError` dans
    le corps de la vue, où plus rien ne la rattrapait."""
    for chemin in ("/api/v1/sales/quotations", "/api/v1/sales/orders"):
        reponse = _post(api, chemin, {"partner_id": "pas-un-uuid", "date": str(dt.date.today())})
        assert reponse.status_code == 422, (
            f"{chemin} rend {reponse.status_code} sur un identifiant malformé "
            f"au lieu de 422 : {reponse.content[:300]!r}"
        )


def test_an_optional_id_that_is_not_a_uuid_is_refused_too(api) -> None:
    """Les identifiants FACULTATIFS étaient le même défaut, une ligne plus
    bas : `uuid.UUID(x) if x else None` protège du vide, pas du malformé."""
    reponse = _post(
        api,
        "/api/v1/sales/orders",
        {
            "partner_id": "01a08028-a792-71db-be70-ebfc0e98c5ab",
            "date": str(dt.date.today()),
            "pricelist_id": "-",
        },
    )
    assert reponse.status_code == 422


def test_a_target_period_longer_than_the_column_is_refused(api) -> None:
    """`SalesTarget.period` est un `CharField(max_length=7)` — le bucket
    mensuel « AAAA-MM ». `objects.create()` sans validation laissait Postgres
    répondre à sa place, par une `DataError`, donc un 500."""
    reponse = _post(
        api,
        "/api/v1/sales/targets",
        {"period": "2026-06-jamais-de-la-vie", "amount_mga": "1000"},
    )
    assert reponse.status_code == 422
    assert not SalesTarget.objects.filter(period__startswith="2026-06-j").exists()


def test_a_target_amount_beyond_the_column_capacity_is_refused(api) -> None:
    """Dix-huit chiffres, pas dix-neuf : au-delà, `DecimalField` fait lever
    Postgres. Le schéma le borne désormais avant la base."""
    reponse = _post(
        api,
        "/api/v1/sales/targets",
        {"period": "2026-06", "amount_mga": "9" * 20},
    )
    assert reponse.status_code == 422


def test_a_target_scope_outside_the_declared_choices_is_refused(api) -> None:
    """Un `choices` que rien ne vérifie est un `choices` décoratif : l'objectif
    était écrit avec une portée inconnue, puis invisible de tout écran qui
    filtre par portée."""
    reponse = _post(
        api,
        "/api/v1/sales/targets",
        {"period": "2026-06", "scope": "galaxie", "amount_mga": "1000"},
    )
    assert reponse.status_code == 422
    assert not SalesTarget.objects.filter(scope="galaxie").exists()


def test_the_model_itself_refuses_an_unknown_scope(api) -> None:
    """La garde vit dans `save()`, pas seulement dans le schéma d'entrée :
    l'endpoint n'est pas la seule porte — un import, une commande de reprise
    ou un shell passent à côté."""
    from django.core.exceptions import ValidationError

    _client, _entetes, tenant = api
    with pytest.raises(ValidationError):
        SalesTarget.objects.create(tenant=tenant, period="2026-06", scope="galaxie")


def test_a_forecast_variant_filter_that_is_not_a_uuid_is_refused(api) -> None:
    """`GET /sales/forecast` convertissait lui-même son paramètre de filtre :
    `uuid.UUID(variant)` sur une chaîne libre."""
    client, entetes, _tenant = api
    reponse = client.get("/api/v1/sales/forecast?variant=pas-un-uuid", **entetes)
    assert reponse.status_code == 422
