"""MCP surface: all eight tools, exercised through an in-memory MCP client.

These tests speak the protocol rather than calling Python functions directly,
so they cover tool registration, schemas, serialisation and error shaping -
the things that break silently when a client, not a test, is the caller.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from contextslim import service as service_module
from contextslim.server import mcp

EXPECTED_TOOLS = {
    "extract_session_state",
    "load_capsule",
    "list_capsules",
    "get_stats",
    "check_context_health",
    "update_capsule",
    "search_capsules",
    "export_capsule",
}


@pytest.fixture
def server(settings):
    """Point the module-level service at the test's temporary directory."""
    service_module.reset_service()
    service_module.get_service(settings)
    yield mcp
    service_module.reset_service()


@pytest.fixture
async def client(server):
    async with Client(server) as connected:
        yield connected


async def call(client, name, **arguments):
    result = await client.call_tool(name, arguments)
    return result.data


# --- registration ----------------------------------------------------------


async def test_all_eight_tools_are_registered(client):
    names = {tool.name for tool in await client.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_every_tool_documents_when_to_use_it(client):
    for tool in await client.list_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) > 80, f"{tool.name} description is too thin"


async def test_extract_tool_schema_exposes_its_arguments(client):
    tool = next(t for t in await client.list_tools() if t.name == "extract_session_state")
    properties = tool.inputSchema["properties"]
    assert {"chat_history", "mode", "project", "title", "file_paths"} <= set(properties)


async def test_mode_options_are_documented_in_the_tool(client):
    tool = next(t for t in await client.list_tools() if t.name == "extract_session_state")
    assert "slim" in tool.description and "deep" in tool.description


# --- happy path across the whole flow --------------------------------------


async def test_extract_then_load_over_the_protocol(client, sample_chat):
    created = await call(client, "extract_session_state", chat_history=sample_chat)
    assert created["ok"] is True
    session_id = created["session_id"]

    loaded = await call(client, "load_capsule", session_id=session_id)
    assert loaded["ok"] is True
    assert "CONTEXT CAPSULE RESTORED" in loaded["restore_prompt"]
    assert loaded["capsule"]["decisions"]


async def test_list_capsules_over_the_protocol(client, sample_chat):
    await call(client, "extract_session_state", chat_history=sample_chat)
    listed = await call(client, "list_capsules")
    assert listed["count"] == 1
    assert listed["capsules"][0]["mode"] == "slim"


async def test_get_stats_over_the_protocol(client, sample_chat):
    await call(client, "extract_session_state", chat_history=sample_chat)
    stats = await call(client, "get_stats")
    assert stats["total_sessions"] == 1
    assert stats["total_tokens_saved"] > 0


async def test_check_context_health_over_the_protocol(client):
    healthy = await call(client, "check_context_health", token_count=1000)
    critical = await call(client, "check_context_health", token_count=94_000)
    assert healthy["status"] == "HEALTHY"
    assert critical["status"] == "CRITICAL"
    assert critical["should_compress"] is True


async def test_update_capsule_over_the_protocol(client, sample_chat):
    created = await call(client, "extract_session_state", chat_history=sample_chat)
    updated = await call(
        client,
        "update_capsule",
        session_id=created["session_id"],
        chat_history="Decision: we chose Locust for load testing.",
    )
    assert updated["version"] == 2
    assert any("Locust" in item for item in updated["capsule"]["decisions"])


async def test_search_capsules_over_the_protocol(client, sample_chat):
    await call(client, "extract_session_state", chat_history=sample_chat)
    found = await call(client, "search_capsules", query="PostgreSQL")
    assert found["count"] == 1
    assert found["capsules"][0]["excerpt"]


async def test_export_capsule_over_the_protocol(client, sample_chat, tmp_path):
    created = await call(client, "extract_session_state", chat_history=sample_chat)
    exported = await call(
        client,
        "export_capsule",
        session_id=created["session_id"],
        format="json",
        destination=str(tmp_path / "out.json"),
    )
    assert exported["ok"] is True
    assert (tmp_path / "out.json").exists()


async def test_file_ingestion_through_the_protocol(client, tmp_path):
    doc = tmp_path / "spec.md"
    doc.write_text(
        "# API spec\n\nDecision: we chose cursor pagination over offset pagination.",
        encoding="utf-8",
    )
    created = await call(client, "extract_session_state", file_paths=[str(doc)])
    assert created["ingestion"]["file_count"] == 1
    assert created["ok"] is True


# --- errors are data, not exceptions ---------------------------------------


async def test_unknown_capsule_returns_structured_error(client):
    result = await call(client, "load_capsule", session_id="ZZZZZZZZ")
    assert result["ok"] is False
    assert result["error"]["code"] == "capsule_not_found"
    assert "ZZZZZZZZ" in result["error"]["message"]


async def test_invalid_mode_returns_structured_error(client, sample_chat):
    result = await call(client, "extract_session_state", chat_history=sample_chat, mode="turbo")
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"


async def test_empty_input_returns_structured_error(client):
    result = await call(client, "extract_session_state", chat_history="")
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"


async def test_bad_export_format_returns_structured_error(client, sample_chat):
    created = await call(client, "extract_session_state", chat_history=sample_chat)
    result = await call(
        client, "export_capsule", session_id=created["session_id"], format="docx"
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"


async def test_tool_errors_do_not_break_the_connection(client, sample_chat):
    await call(client, "load_capsule", session_id="ZZZZZZZZ")
    healthy = await call(client, "extract_session_state", chat_history=sample_chat)
    assert healthy["ok"] is True


async def test_no_tool_call_raises_through_the_protocol(client):
    """Every failure path must surface as data the model can read."""
    for name, arguments in [
        ("load_capsule", {"session_id": "nope"}),
        ("search_capsules", {"query": " "}),
        ("update_capsule", {"session_id": "ZZZZZZZZ", "chat_history": "x"}),
        ("export_capsule", {"session_id": "ZZZZZZZZ"}),
        ("check_context_health", {}),
    ]:
        result = await client.call_tool(name, arguments)
        assert result.data["ok"] is False, name
        assert result.data["error"]["message"]
