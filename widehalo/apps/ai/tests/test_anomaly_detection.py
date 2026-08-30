"""AI3 : `apps.ai.services.anomaly_detection`. Ne re-teste PAS le registre
lui-meme (deja couvert par `apps.core.tests.test_anomaly_registry`) — se
concentre sur `run_all_checks` : persistance des `AnomalyCandidate`,
isolation des echecs (check qui leve, `content_type_label` invalide),
publication `ai.anomaly_detected` reservee a la severite haute, et
degradation gracieuse de la narrative IA quand aucun provider reel n'est
configure.

**Isolation du registre (autouse fixture `_isolated_registry`)** : le
registre `core.services.anomaly_registry._REGISTRY` est un dict GLOBAL au
processus — sans isolation, un check enregistre par CE fichier de test
resterait visible (et RE-EXECUTE, pour chaque nouveau tenant de chaque
test suivant) pour le reste de la session de test, y compris par d'autres
fichiers. Chaque test de ce fichier tourne donc avec un registre VIDE
(sauf les checks qu'il enregistre lui-meme), restaure automatiquement a
la fin (monkeypatch)."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.ai.models import AiAnomaly
from apps.ai.services.anomaly_detection import run_all_checks
from apps.core.models.event import EventLog
from apps.core.models.tenant import Tenant
from apps.core.services.anomaly_registry import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    AnomalyCandidate,
    register_anomaly_check,
)
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    import apps.core.services.anomaly_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI3-DET", name="Tenant AI3")


@override_settings(AI_PROVIDER_CONFIG={})
def test_run_all_checks_persists_candidates_from_a_registered_check(tenant: Tenant) -> None:
    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_LOW,
                description="Anomalie de test.",
            )
        ]

    register_anomaly_check("test.persist", module="test", label="Persist", function=_check)

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)
        anomaly = AiAnomaly.objects.get(id=created[0].id)

    assert len(created) == 1
    assert anomaly.check_code == "test.persist"
    assert anomaly.severity == SEVERITY_LOW
    assert anomaly.description == "Anomalie de test."
    assert anomaly.object_id == str(tenant.id)
    assert anomaly.content_type is not None
    assert anomaly.content_type.model == "tenant"


@override_settings(AI_PROVIDER_CONFIG={})
def test_run_all_checks_skips_candidate_with_garbage_content_type_label(tenant: Tenant) -> None:
    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="not-a-valid-label",
                object_id=tenant_id,
                severity=SEVERITY_LOW,
                description="Ne doit jamais etre persistee.",
            )
        ]

    register_anomaly_check("test.garbage_label", module="test", label="Garbage", function=_check)

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    assert created == []
    assert not AiAnomaly.objects.filter(check_code="test.garbage_label").exists()


@override_settings(AI_PROVIDER_CONFIG={})
def test_run_all_checks_isolates_a_failing_check_from_the_others(tenant: Tenant) -> None:
    def _failing_check(tenant_id: str) -> list[AnomalyCandidate]:
        raise RuntimeError("bug dans l'adaptateur d'un module")

    def _working_check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_LOW,
                description="Toujours execute malgre l'echec du check precedent.",
            )
        ]

    register_anomaly_check(
        "test.isolation_failing", module="test", label="Failing", function=_failing_check
    )
    register_anomaly_check(
        "test.isolation_working", module="test", label="Working", function=_working_check
    )

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    codes = {anomaly.check_code for anomaly in created}
    assert codes == {"test.isolation_working"}


@override_settings(AI_PROVIDER_CONFIG={})
def test_run_all_checks_publishes_event_only_for_high_severity(tenant: Tenant) -> None:
    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_LOW,
                description="Faible — ne doit pas publier d'evenement.",
            ),
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_HIGH,
                description="Haute — doit publier ai.anomaly_detected.",
            ),
        ]

    register_anomaly_check("test.event_severity", module="test", label="Events", function=_check)

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    assert len(created) == 2
    events = EventLog.objects.filter(event_type="ai.anomaly_detected", tenant_id=str(tenant.id))
    assert events.count() == 1
    high_anomaly = next(a for a in created if a.severity == SEVERITY_HIGH)
    assert events.first().payload["anomaly_id"] == str(high_anomaly.id)
    assert events.first().payload["check_code"] == "test.event_severity"


@override_settings(AI_PROVIDER_CONFIG={})
def test_narrative_stays_empty_without_a_real_provider(tenant: Tenant) -> None:
    """Politique disclosed : narrative generee UNIQUEMENT pour severite
    haute, ET uniquement si un provider reel est configure/disponible.
    `AI_PROVIDER_CONFIG={}` -> `StubAIProvider` -> `ai_narrative` reste
    vide, jamais un texte fabrique."""

    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_HIGH,
                description="Haute, sans provider reel configure.",
            )
        ]

    register_anomaly_check("test.no_provider", module="test", label="No provider", function=_check)

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    assert len(created) == 1
    assert created[0].ai_narrative == ""


@override_settings(AI_PROVIDER_CONFIG={})
def test_narrative_is_never_generated_for_non_high_severity(tenant: Tenant, monkeypatch) -> None:
    """Meme avec un provider reel disponible, seule la severite haute
    declenche un appel LLM (bornage du cout, cf. docstring de module)."""

    class _CountingProvider:
        calls = 0

        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            type(self).calls += 1
            return "Narrative generee."

    monkeypatch.setattr(
        "apps.ai.services.anomaly_detection.get_budget_gated_provider",
        lambda tenant: _CountingProvider(),
    )

    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_LOW,
                description="Faible, ne doit jamais appeler le provider.",
            )
        ]

    register_anomaly_check("test.no_narrative_low", module="test", label="Low", function=_check)

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    assert len(created) == 1
    assert created[0].ai_narrative == ""
    assert _CountingProvider.calls == 0


@override_settings(AI_PROVIDER_CONFIG={})
def test_narrative_generation_failure_never_blocks_anomaly_creation(
    tenant: Tenant, monkeypatch
) -> None:
    from apps.core.services.ai_assistant import AIProviderError

    class _FailingProvider:
        def complete(self, prompt: str, *, max_tokens: int = 500) -> str:
            raise AIProviderError("panne reseau simulee")

    monkeypatch.setattr(
        "apps.ai.services.anomaly_detection.get_budget_gated_provider",
        lambda tenant: _FailingProvider(),
    )

    def _check(tenant_id: str) -> list[AnomalyCandidate]:
        return [
            AnomalyCandidate(
                content_type_label="core.tenant",
                object_id=tenant_id,
                severity=SEVERITY_HIGH,
                description="Haute, provider en echec.",
            )
        ]

    register_anomaly_check(
        "test.narrative_failure", module="test", label="Failure", function=_check
    )

    with use_tenant(tenant.id):
        created = run_all_checks(tenant)

    assert len(created) == 1
    assert created[0].ai_narrative == ""
    # L'evenement HIGH doit neanmoins etre publie malgre l'echec narrative.
    assert EventLog.objects.filter(
        event_type="ai.anomaly_detected", tenant_id=str(tenant.id)
    ).exists()
