"""GW4 : `apps.ai.services.data_query_gateway.ask`. Verifie la discipline
"fallback-first" (stub -> reponse statique immediate, boucle jamais
tentee), le correctif de securite du cadrage (un tool sans permission
n'est JAMAIS meme offert au LLM), la validation d'arguments, et la
terminaison garantie de la boucle bornee meme si le LLM insiste."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission

from apps.ai.models import AiDataQuery, AiRequest
from apps.ai.services.data_query_gateway import ask
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import AIProviderError, ToolCall, ToolCallResult
from apps.core.services.data_query_tool_registry import register_data_query_tool
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="AI-DQ-GW4", name="Tenant Data Query GW4")


@pytest.fixture
def user_with_sales_permission(tenant: Tenant) -> User:
    created_user = User.objects.create_user(
        email="dq-sales@example.com", password="Str0ngPassw0rd!23"
    )
    permission = Permission.objects.get(codename="view_salesorder", content_type__app_label="sales")
    group = Group.objects.create(name="dq-sales-viewers")
    group.permissions.add(permission)
    created_user.groups.add(group)
    return created_user


@pytest.fixture
def user_without_any_permission() -> User:
    return User.objects.create_user(email="dq-noperm@example.com", password="Str0ngPassw0rd!23")


def _register_test_tool(code: str = "test.dq_tool") -> list[dict]:
    calls: list[dict] = []

    def _fn(tenant, user, **kwargs):
        calls.append(kwargs)
        return [{"value": 42}]

    register_data_query_tool(
        code,
        module="test",
        label="Test tool",
        description="Un tool de test pour le gateway.",
        parameters_schema={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": [],
        },
        required_permission="sales.view_salesorder",
        read_only=True,
        function=_fn,
    )
    return calls


# ---------------------------------------------------------------------------
# fallback-first : stub -> reponse statique immediate, boucle jamais tentee
# ---------------------------------------------------------------------------


def test_stub_provider_returns_static_answer_without_attempting_the_loop(
    tenant: Tenant, user_with_sales_permission: User
) -> None:
    with use_tenant(tenant.id):
        record = ask(
            "Quel est le CA du mois dernier ?",
            tenant=tenant,
            user=user_with_sales_permission,
            locale="fr",
        )
        request_count = AiRequest.objects.filter(
            tenant=tenant, feature=AiRequest.FEATURE_DATA_QUERY
        ).count()

    assert isinstance(record, AiDataQuery)
    assert record.succeeded is False
    assert record.tools_called == []
    assert record.provider_backend == "stub"
    assert request_count == 1


# ---------------------------------------------------------------------------
# correctif de securite : un tool sans permission n'est jamais offert au LLM
# ---------------------------------------------------------------------------


def test_tool_never_offered_without_permission(
    tenant: Tenant, user_without_any_permission: User, monkeypatch
) -> None:
    _register_test_tool("test.dq_permission_check")
    offered_tool_names: list[str] = []

    class _RecordingProvider:
        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            offered_tool_names.extend(t.name for t in tools)
            return ToolCallResult(content="Reponse sans tool.", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda tenant: _RecordingProvider(),
    )

    with use_tenant(tenant.id):
        record = ask(
            "Question quelconque ?", tenant=tenant, user=user_without_any_permission, locale="fr"
        )

    assert "test.dq_permission_check" not in offered_tool_names
    assert record.tools_called == []


def test_tool_is_offered_and_invoked_for_a_user_with_permission(
    tenant: Tenant, user_with_sales_permission: User, monkeypatch
) -> None:
    calls = _register_test_tool("test.dq_permission_check_2")

    class _CallingProvider:
        def __init__(self) -> None:
            self._called = False

        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            names = [t.name for t in tools]
            assert "test.dq_permission_check_2" in names
            if not self._called:
                self._called = True
                return ToolCallResult(
                    content=None,
                    tool_calls=[ToolCall(id="1", name="test.dq_permission_check_2", arguments={})],
                )
            return ToolCallResult(content="Voici la reponse finale.", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda tenant: _CallingProvider(),
    )

    with use_tenant(tenant.id):
        record = ask(
            "Question quelconque ?", tenant=tenant, user=user_with_sales_permission, locale="fr"
        )

    assert record.succeeded is True
    assert record.tools_called == [{"code": "test.dq_permission_check_2", "args": {}}]
    assert record.answer == "Voici la reponse finale."
    assert calls == [{}]


# ---------------------------------------------------------------------------
# validation stricte des arguments
# ---------------------------------------------------------------------------


def test_invalid_arguments_skip_the_tool_call_without_raising(
    tenant: Tenant, user_with_sales_permission: User, monkeypatch
) -> None:
    _register_test_tool("test.dq_bad_args")

    class _BadArgsProvider:
        def __init__(self) -> None:
            self._called = False

        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            if not self._called:
                self._called = True
                return ToolCallResult(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="1", name="test.dq_bad_args", arguments={"x": 123}
                        )  # x doit etre string
                    ],
                )
            return ToolCallResult(content="Repli.", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda tenant: _BadArgsProvider(),
    )

    with use_tenant(tenant.id):
        record = ask("Question ?", tenant=tenant, user=user_with_sales_permission, locale="fr")

    assert record.tools_called == []
    assert record.succeeded is True
    assert record.answer == "Repli."


# ---------------------------------------------------------------------------
# terminaison garantie de la boucle bornee
# ---------------------------------------------------------------------------


def test_bounded_loop_terminates_even_if_the_llm_keeps_calling_tools(
    tenant: Tenant, user_with_sales_permission: User, monkeypatch
) -> None:
    _register_test_tool("test.dq_infinite")
    call_count = {"n": 0}

    class _StubbornProvider:
        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            call_count["n"] += 1
            return ToolCallResult(
                content=None,
                tool_calls=[
                    ToolCall(id=str(call_count["n"]), name="test.dq_infinite", arguments={})
                ],
            )

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda tenant: _StubbornProvider(),
    )

    with use_tenant(tenant.id):
        record = ask("Question ?", tenant=tenant, user=user_with_sales_permission, locale="fr")

    # 3 allers-retours maximum (_MAX_TOOL_ROUND_TRIPS) — jamais plus, jamais
    # une boucle infinie ni une exception.
    assert call_count["n"] == 3
    assert len(record.tools_called) == 3
    assert record.succeeded is True


# ---------------------------------------------------------------------------
# degradation propre sur AIProviderError
# ---------------------------------------------------------------------------


def test_provider_error_degrades_cleanly_never_raises(
    tenant: Tenant, user_with_sales_permission: User, monkeypatch
) -> None:
    class _FailingProvider:
        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            raise AIProviderError("panne reseau simulee")

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda tenant: _FailingProvider(),
    )

    with use_tenant(tenant.id):
        record = ask("Question ?", tenant=tenant, user=user_with_sales_permission, locale="fr")

    assert record.succeeded is False
    assert record.tools_called == []
