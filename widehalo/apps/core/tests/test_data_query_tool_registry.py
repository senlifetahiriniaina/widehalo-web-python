"""GW2 (passerelle IA locale d'analyse de donnees) — registre central des
tools de question-donnees, meme patron que `test_anomaly_registry.py`/
`test_advisor_rule_registry.py`."""

from __future__ import annotations

from apps.core.services.data_query_tool_registry import (
    get_data_query_tool,
    list_data_query_tools,
    register_data_query_tool,
)


def _noop_tool(tenant, user):  # noqa: ANN001 - signature de test minimale
    return []


_SCHEMA = {"type": "object", "properties": {}, "required": []}


def test_register_and_get_tool() -> None:
    register_data_query_tool(
        "test.noop",
        module="test",
        label="No-op",
        description="Un tool de test.",
        parameters_schema=_SCHEMA,
        required_permission="test.view_test",
        function=_noop_tool,
    )
    tool = get_data_query_tool("test.noop")
    assert tool is not None
    assert tool.module == "test"
    assert tool.required_permission == "test.view_test"
    assert tool.function is _noop_tool


def test_register_is_idempotent_replaces_entry() -> None:
    register_data_query_tool(
        "test.replace",
        module="test",
        label="V1",
        description="V1",
        parameters_schema=_SCHEMA,
        required_permission="test.view_test",
        function=_noop_tool,
    )
    register_data_query_tool(
        "test.replace",
        module="test",
        label="V2",
        description="V2",
        parameters_schema=_SCHEMA,
        required_permission="test.view_test",
        function=_noop_tool,
    )
    tool = get_data_query_tool("test.replace")
    assert tool is not None
    assert tool.label == "V2"


def test_unknown_tool_returns_none() -> None:
    assert get_data_query_tool("does.not.exist") is None


def test_list_data_query_tools_is_sorted_by_code() -> None:
    register_data_query_tool(
        "test.zzz",
        module="test",
        label="Z",
        description="Z",
        parameters_schema=_SCHEMA,
        required_permission="test.view_test",
        function=_noop_tool,
    )
    register_data_query_tool(
        "test.aaa",
        module="test",
        label="A",
        description="A",
        parameters_schema=_SCHEMA,
        required_permission="test.view_test",
        function=_noop_tool,
    )
    codes = [t.code for t in list_data_query_tools()]
    assert codes == sorted(codes)
