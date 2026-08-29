"""5 fonctions d'assistance IA de `projects` (PJ12) — `apps.projects.
services.ai_assistant`. Sans configuration IA (defaut du projet), chaque
fonction doit retourner une reponse coherente et EXPLICITEMENT etiquetee
"non configuree", jamais une exception, jamais du texte genere qui se
ferait passer pour une vraie analyse."""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.projects.models import PrjTask
from apps.projects.services.ai_assistant import (
    estimate_task_duration,
    generate_status_report,
    generate_tasks_from_spec,
    identify_risks,
    suggest_prioritization,
)
from apps.projects.services.dependencies import add_dependency
from apps.projects.services.projects import create_project
from apps.projects.services.tasks import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx():
    tenant = Tenant.objects.create(code="PRJ-AI-T1", name="Projects AI Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="pm-ai@example.com", password="Str0ngPassw0rd!23")
        project = create_project(
            tenant,
            name="Projet assiste par IA",
            owner=user,
            start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31),
        )
        yield tenant, project, user


# ---------------------------------------------------------------------------
# Degradation gracieuse vers le stub — aucune configuration IA
# ---------------------------------------------------------------------------


def test_estimate_task_duration_returns_labeled_stub_response_without_config(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        result = estimate_task_duration(task)
    assert result.is_ai_generated is False
    assert "non configuree" in result.estimate_text.lower()
    assert result.similar_tasks_sample_size == 0


def test_estimate_task_duration_counts_similar_completed_tasks(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        done_task = create_task(tenant, project=project, duration_days=5)
        done_task.state = PrjTask.STATE_DONE
        done_task.save(update_fields=["state"])
        task = create_task(tenant, project=project)
        result = estimate_task_duration(task)
    assert result.similar_tasks_sample_size == 1


def test_identify_risks_returns_labeled_stub_response_with_real_signal(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        overdue = create_task(
            tenant,
            project=project,
            start_date=dt.date(2020, 1, 1),
            end_date=dt.date(2020, 1, 5),
        )
        assert overdue.end_date < dt.date.today()
        text = identify_risks(project)
    assert "non configuree" in text.lower()
    assert "1" in text  # nombre de taches en retard


def test_generate_status_report_returns_labeled_stub_response(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        create_task(tenant, project=project)
        text = generate_status_report(project)
    assert "non configuree" in text.lower()
    assert project.name not in text  # le stub ne redige pas de prose nominative


def test_generate_tasks_from_spec_returns_empty_list_without_config(ctx) -> None:
    """Sans connecteur IA, aucune heuristique fiable n'existe pour deviner
    des taches a partir d'un texte libre — liste VIDE plutot qu'une
    decomposition inventee."""
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        proposals = generate_tasks_from_spec(project, "Construire un site vitrine avec blog.")
    assert proposals == []


def test_suggest_prioritization_returns_labeled_stub_response_with_real_signal(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        task_a = create_task(tenant, project=project, end_date=dt.date(2026, 2, 1))
        task_b = create_task(tenant, project=project, end_date=dt.date(2026, 3, 1))
        add_dependency(task_a, task_b)
        text = suggest_prioritization(project)
    assert "non configuree" in text.lower()
    assert "Dependances declarees sur le projet : 1" in text


# ---------------------------------------------------------------------------
# Connecteur configure (mocke) — jamais de vrai appel reseau en test
# ---------------------------------------------------------------------------


@override_settings(
    AI_PROVIDER_CONFIG={"base_url": "https://api.deepseek.com/v1", "api_key": "secret"}
)
def test_estimate_task_duration_uses_real_provider_when_configured(ctx) -> None:
    tenant, project, user = ctx
    with use_tenant(tenant.id):
        task = create_task(tenant, project=project)
        with patch(
            "apps.core.services.ai_assistant.OpenAICompatibleAIProvider.complete",
            return_value="Estimation : 3 jours.",
        ):
            result = estimate_task_duration(task)
    assert result.is_ai_generated is True
    assert result.estimate_text == "Estimation : 3 jours."


@override_settings(
    AI_PROVIDER_CONFIG={"base_url": "https://api.deepseek.com/v1", "api_key": "secret"}
)
def test_identify_risks_degrades_cleanly_on_provider_error(ctx) -> None:
    from apps.core.services.ai_assistant import AIProviderError

    tenant, project, user = ctx
    with (
        use_tenant(tenant.id),
        patch(
            "apps.core.services.ai_assistant.OpenAICompatibleAIProvider.complete",
            side_effect=AIProviderError("panne reseau"),
        ),
    ):
        text = identify_risks(project)
    assert "indisponible" in text.lower()


@override_settings(
    AI_PROVIDER_CONFIG={"base_url": "https://api.deepseek.com/v1", "api_key": "secret"}
)
def test_generate_tasks_from_spec_parses_json_proposals_when_configured(ctx) -> None:
    tenant, project, user = ctx
    with (
        use_tenant(tenant.id),
        patch(
            "apps.core.services.ai_assistant.OpenAICompatibleAIProvider.complete",
            return_value=(
                '[{"title": "Maquette", "description": "Wireframes", "story_points": 3}, '
                '{"title": "Backend API"}]'
            ),
        ),
    ):
        proposals = generate_tasks_from_spec(project, "Site vitrine avec blog.")
    assert proposals == [
        {"title": "Maquette", "description": "Wireframes", "story_points": 3},
        {"title": "Backend API", "description": "", "story_points": None},
    ]


@override_settings(
    AI_PROVIDER_CONFIG={"base_url": "https://api.deepseek.com/v1", "api_key": "secret"}
)
def test_generate_tasks_from_spec_returns_empty_list_on_malformed_json(ctx) -> None:
    tenant, project, user = ctx
    with (
        use_tenant(tenant.id),
        patch(
            "apps.core.services.ai_assistant.OpenAICompatibleAIProvider.complete",
            return_value="ceci n'est pas du JSON",
        ),
    ):
        proposals = generate_tasks_from_spec(project, "Site vitrine.")
    assert proposals == []
