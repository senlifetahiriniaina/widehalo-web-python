"""Mecanisme generique `apps.core.services.ai_assistant` (chantier
`projects`, PJ12). Le test le plus important de ce fichier est
`test_stub_provider_never_performs_any_network_call` — il verifie
explicitement que `StubAIProvider`/`get_ai_provider` (sans configuration)
n'ouvrent RIGOUREUSEMENT AUCUN socket reseau, meme si le code appelant
tentait d'en ouvrir un (patch de `socket.socket` qui echoue le test si
invoque) — meme patron que `apps.purchase.tests.test_price_watch::
test_stub_provider_never_performs_any_network_call`."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from apps.core.services.ai_assistant import (
    AIProviderError,
    OpenAICompatibleAIProvider,
    StubAIProvider,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    get_ai_provider,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# get_ai_provider — stub par defaut, connecteur reel seulement si configure
# ---------------------------------------------------------------------------


def test_get_ai_provider_returns_stub_by_default() -> None:
    """Defaut du projet : `settings.AI_PROVIDER_CONFIG = {}` -> stub."""
    assert isinstance(get_ai_provider(), StubAIProvider)


@override_settings(AI_PROVIDER_CONFIG={"base_url": "https://api.example.test/v1"})
def test_get_ai_provider_stays_stub_when_api_key_missing() -> None:
    assert isinstance(get_ai_provider(), StubAIProvider)


@override_settings(AI_PROVIDER_CONFIG={"api_key": "secret"})
def test_get_ai_provider_stays_stub_when_base_url_missing() -> None:
    assert isinstance(get_ai_provider(), StubAIProvider)


@override_settings(
    AI_PROVIDER_CONFIG={
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "secret",
        "model": "deepseek-chat",
    }
)
def test_get_ai_provider_switches_to_real_connector_when_fully_configured() -> None:
    provider = get_ai_provider()
    assert isinstance(provider, OpenAICompatibleAIProvider)
    assert provider.base_url == "https://api.deepseek.com/v1"
    assert provider.api_key == "secret"
    assert provider.model == "deepseek-chat"


@override_settings(
    AI_PROVIDER_CONFIG={"base_url": "https://api.moonshot.cn/v1", "api_key": "secret"}
)
def test_get_ai_provider_defaults_model_when_omitted() -> None:
    """`model` est optionnel dans la configuration — un defaut neutre est
    applique, jamais une exception pour ce seul champ manquant."""
    provider = get_ai_provider()
    assert isinstance(provider, OpenAICompatibleAIProvider)
    assert provider.model


# ---------------------------------------------------------------------------
# StubAIProvider — reserve de securite : aucun appel reseau
# ---------------------------------------------------------------------------


def test_stub_provider_never_performs_any_network_call() -> None:
    def _forbidden_socket(*args, **kwargs):
        raise AssertionError(
            "Un socket reseau a ete ouvert par le stub — violation de la reserve "
            "de securite (aucun appel reseau sans connecteur IA configure)."
        )

    original_socket = socket.socket
    socket.socket = _forbidden_socket  # type: ignore[assignment]
    try:
        result = StubAIProvider().complete("Un prompt quelconque")
    finally:
        socket.socket = original_socket  # type: ignore[assignment]

    assert "non configuree" in result.lower()


def test_stub_provider_message_is_translatable_not_an_exception() -> None:
    # Ne doit jamais lever, meme avec un prompt vide/absurde.
    assert StubAIProvider().complete("") != ""


# ---------------------------------------------------------------------------
# OpenAICompatibleAIProvider — jamais de VRAI appel reseau en test, mock uniquement
# ---------------------------------------------------------------------------


def _fake_http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_openai_compatible_provider_builds_correct_request_and_parses_response() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    fake_response = _fake_http_response(
        {"choices": [{"message": {"content": "Reponse generee par le modele."}}]}
    )

    with patch("requests.post", return_value=fake_response) as mocked_post:
        result = provider.complete("Estime la duree de cette tache.", max_tokens=250)

    assert result == "Reponse generee par le modele."
    assert mocked_post.call_count == 1
    _args, kwargs = mocked_post.call_args
    assert _args[0] == "https://api.deepseek.com/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert kwargs["json"]["model"] == "deepseek-chat"
    assert kwargs["json"]["max_tokens"] == 250
    assert kwargs["json"]["messages"] == [
        {"role": "user", "content": "Estime la duree de cette tache."}
    ]


def test_openai_compatible_provider_raises_ai_provider_error_on_network_failure() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    with (
        patch("requests.post", side_effect=requests.ConnectionError("connexion refusee")),
        pytest.raises(AIProviderError),
    ):
        provider.complete("prompt")


def test_openai_compatible_provider_raises_ai_provider_error_on_malformed_response() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    fake_response = _fake_http_response({"unexpected": "shape"})
    with patch("requests.post", return_value=fake_response), pytest.raises(AIProviderError):
        provider.complete("prompt")


# ---------------------------------------------------------------------------
# GW1 — complete_with_tools (passerelle IA locale d'analyse de donnees)
# ---------------------------------------------------------------------------

_A_TOOL = ToolDefinition(
    name="sales.revenue_report",
    description="Chiffre d'affaires par periode.",
    parameters_schema={"type": "object", "properties": {}, "required": []},
)


def test_stub_provider_complete_with_tools_never_performs_any_network_call() -> None:
    def _forbidden_socket(*args, **kwargs):
        raise AssertionError(
            "Un socket reseau a ete ouvert par le stub (complete_with_tools) — violation de "
            "la reserve de securite."
        )

    original_socket = socket.socket
    socket.socket = _forbidden_socket  # type: ignore[assignment]
    try:
        result = StubAIProvider().complete_with_tools([{"role": "user", "content": "?"}], [_A_TOOL])
    finally:
        socket.socket = original_socket  # type: ignore[assignment]

    assert isinstance(result, ToolCallResult)
    assert result.tool_calls == []
    assert result.content is not None
    assert "non configuree" in result.content.lower()


def test_openai_compatible_provider_complete_with_tools_builds_request_and_parses_tool_calls() -> (
    None
):
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    fake_response = _fake_http_response(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "sales.revenue_report",
                                    "arguments": '{"date_from": "2026-01-01"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )

    with patch("requests.post", return_value=fake_response) as mocked_post:
        result = provider.complete_with_tools(
            [{"role": "user", "content": "CA de janvier ?"}], [_A_TOOL]
        )

    assert result.content is None
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert isinstance(call, ToolCall)
    assert call.id == "call_1"
    assert call.name == "sales.revenue_report"
    assert call.arguments == {"date_from": "2026-01-01"}

    _args, kwargs = mocked_post.call_args
    assert kwargs["json"]["tool_choice"] == "auto"
    assert kwargs["json"]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "sales.revenue_report",
                "description": "Chiffre d'affaires par periode.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]


def test_complete_with_tools_returns_plain_content_without_tool_calls() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    fake_response = _fake_http_response(
        {"choices": [{"message": {"content": "Voici votre reponse.", "tool_calls": []}}]}
    )
    with patch("requests.post", return_value=fake_response):
        result = provider.complete_with_tools([{"role": "user", "content": "?"}], [])

    assert result.content == "Voici votre reponse."
    assert result.tool_calls == []


def test_openai_compatible_provider_complete_with_tools_raises_on_network_failure() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    with (
        patch("requests.post", side_effect=requests.ConnectionError("connexion refusee")),
        pytest.raises(AIProviderError),
    ):
        provider.complete_with_tools([{"role": "user", "content": "?"}], [_A_TOOL])


def test_complete_with_tools_raises_on_malformed_tool_call_arguments() -> None:
    provider = OpenAICompatibleAIProvider(
        base_url="https://api.deepseek.com/v1", api_key="secret-key", model="deepseek-chat"
    )
    fake_response = _fake_http_response(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "sales.revenue_report",
                                    "arguments": "not-json",
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    with patch("requests.post", return_value=fake_response), pytest.raises(AIProviderError):
        provider.complete_with_tools([{"role": "user", "content": "?"}], [_A_TOOL])
