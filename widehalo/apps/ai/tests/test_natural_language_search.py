"""AI4 : `apps.ai.services.natural_language_search`. Verifie la garantie
"fallback-first" (jamais d'exception, jamais de filtre non valide propage),
et qu'un `global_search` reel renvoie de vrais resultats indexes."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission

from apps.ai.models import AiRequest
from apps.ai.services.natural_language_search import search
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError
from apps.core.services.search import index_object
from apps.core.services.search_registry import register_search_source
from apps.core.tests.models import SampleTenantScopedRecord
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@register_search_source(SampleTenantScopedRecord)
def _extract_sample_record(instance: SampleTenantScopedRecord) -> dict:
    return {
        "reference": instance.label,
        "text": instance.label,
        "url": f"/records/{instance.pk}",
    }


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI-NL-SEARCH", name="Tenant NL Search")


@pytest.fixture
def user(tenant: Tenant) -> User:
    created_user = User.objects.create_user(
        email="nlsearch@example.com", password="Str0ngPassw0rd!23"
    )
    permission = Permission.objects.get(
        codename="view_sampletenantscopedrecord", content_type__app_label="core"
    )
    group = Group.objects.create(name="nl-search-viewers")
    group.permissions.add(permission)
    created_user.groups.add(group)
    return created_user


@pytest.fixture
def indexed_record(tenant: Tenant):
    with use_tenant(tenant.id):
        record = SampleTenantScopedRecord.objects.create(tenant=tenant, label="DEV-2026-0777")
        index_object(record, tenant_id=str(tenant.id))
    return record


def test_stub_provider_returns_plain_global_search_results(
    tenant: Tenant, user: User, indexed_record
) -> None:
    """Aucun provider IA reel configure (settings de test par defaut) ->
    resultats bruts de `global_search`, `is_ai_enhanced=False`,
    `extracted_filters=None`."""
    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")

    assert response["query"] == "DEV-2026-0777"
    assert response["results"]
    assert response["results"][0]["reference"] == "DEV-2026-0777"
    assert response["is_ai_enhanced"] is False
    assert response["extracted_filters"] is None


def test_real_global_search_returns_real_seeded_results(
    tenant: Tenant, user: User, indexed_record
) -> None:
    """Preuve qu'il ne s'agit pas d'un simple "ne plante pas" : le
    resultat contient bien l'enregistrement reellement indexe."""
    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")

    references = [r["reference"] for r in response["results"]]
    assert "DEV-2026-0777" in references


def test_well_formed_extraction_is_validated_and_surfaced(
    tenant: Tenant, user: User, indexed_record, monkeypatch
) -> None:
    """`module="accounting"` appartient a la liste blanche -> valide et
    surface dans `extracted_filters` (jamais "core", volontairement exclu
    de la liste blanche cf. docstring de module : ce n'est pas un module
    "metier" qu'une question en langage naturel designerait)."""

    class _ExtractingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            return '{"module": "accounting", "date_from": "2026-01-01", "amount_threshold": "500000"}'

    monkeypatch.setattr(
        "apps.ai.services.natural_language_search.get_budget_gated_provider",
        lambda tenant: _ExtractingProvider(),
    )

    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")
        assert AiRequest.objects.filter(tenant=tenant, feature=AiRequest.FEATURE_SEARCH).count() == 1

    assert response["is_ai_enhanced"] is True
    assert response["extracted_filters"] == {
        "module": "accounting",
        "date_from": "2026-01-01",
        "amount_threshold": "500000",
    }
    # `SampleTenantScopedRecord` appartient a l'app `core`, pas
    # `accounting` -> ecarte par le narrowing reel applique sur `module`
    # (seul filtre effectivement APPLIQUE dans ce MVP, cf. docstring de
    # module) — preuve que le filtre valide est bien branche, pas juste
    # surface.
    assert response["results"] == []


def test_matching_module_filter_keeps_matching_results(
    tenant: Tenant, user: User, indexed_record, monkeypatch
) -> None:
    """Preuve positive que le narrowing par `module` est bien branche
    (pas seulement qu'il exclut) : `_ALLOWED_MODULES` est etendu pour ce
    test avec l'app_label reel du modele de test (`core`, exclu par defaut
    de la liste blanche de production — cf. docstring de module) afin de
    verifier que, quand l'app_label extrait correspond, le resultat est
    bien conserve plutot qu'ecarte a tort."""
    monkeypatch.setattr(
        "apps.ai.services.natural_language_search._ALLOWED_MODULES",
        frozenset({"core"}),
    )

    class _ExtractingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            return '{"module": "core"}'

    monkeypatch.setattr(
        "apps.ai.services.natural_language_search.get_budget_gated_provider",
        lambda tenant: _ExtractingProvider(),
    )

    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")

    assert response["extracted_filters"] == {"module": "core"}
    assert response["results"]
    assert response["results"][0]["reference"] == "DEV-2026-0777"


def test_malformed_extraction_fields_are_silently_dropped(
    tenant: Tenant, user: User, indexed_record, monkeypatch
) -> None:
    """Module hors liste blanche, date invalide, montant non numerique :
    AUCUN des trois ne doit fuiter dans `extracted_filters`."""

    class _GarbageProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            return (
                '{"module": "not_a_real_module", "date_from": "pas-une-date", '
                '"amount_threshold": "beaucoup d\'argent"}'
            )

    monkeypatch.setattr(
        "apps.ai.services.natural_language_search.get_budget_gated_provider",
        lambda tenant: _GarbageProvider(),
    )

    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")

    assert response["extracted_filters"] is None
    assert response["is_ai_enhanced"] is False
    # Recherche brute non affectee malgre l'echec d'extraction.
    assert response["results"]


def test_non_json_extraction_response_falls_back_gracefully(
    tenant: Tenant, user: User, indexed_record, monkeypatch
) -> None:
    class _ChattyProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            return "Bien sur, voici votre reponse en texte libre, pas du JSON."

    monkeypatch.setattr(
        "apps.ai.services.natural_language_search.get_budget_gated_provider",
        lambda tenant: _ChattyProvider(),
    )

    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")

    assert response["extracted_filters"] is None
    assert response["is_ai_enhanced"] is False
    assert response["results"]


def test_ai_provider_error_during_extraction_degrades_to_plain_search(
    tenant: Tenant, user: User, indexed_record, monkeypatch
) -> None:
    class _FailingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            raise AIProviderError("panne reseau simulee")

    monkeypatch.setattr(
        "apps.ai.services.natural_language_search.get_budget_gated_provider",
        lambda tenant: _FailingProvider(),
    )

    with use_tenant(tenant.id):
        response = search("DEV-2026-0777", tenant=tenant, user=user, locale="fr")
        failed_request = AiRequest.objects.get(tenant=tenant, feature=AiRequest.FEATURE_SEARCH)
        assert failed_request.succeeded is False

    assert response["extracted_filters"] is None
    assert response["is_ai_enhanced"] is False
    assert response["results"]


def test_empty_query_never_raises(tenant: Tenant, user: User) -> None:
    with use_tenant(tenant.id):
        response = search("", tenant=tenant, user=user, locale="fr")

    assert response["results"] == []
    assert response["extracted_filters"] is None
