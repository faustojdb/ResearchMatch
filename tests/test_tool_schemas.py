"""
Offline tests for the input schemas the server advertises.

FastMCP describes ``params: SomeModel`` with ``$ref``/``$defs``. Some MCP hosts drop
``$defs`` and show the argument as an empty ``{}``, leaving the model without field names.
The server inlines the definitions, so every advertised schema must be self-contained.

Run standalone with:
    pytest tests/test_tool_schemas.py -q
"""

from __future__ import annotations

import asyncio
import json

import pytest

import src.research_match_server as server
from src.research_match_server import _inline_tool_schemas, _resolve_schema_refs


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_all_27_tools_are_registered(tools):
    assert len(tools) == 27
    assert all(name.startswith("research_match_") for name in tools)


def test_no_tool_schema_has_unresolved_references(tools):
    offenders = [n for n, t in tools.items() if "$ref" in json.dumps(t.inputSchema) or "$defs" in t.inputSchema]
    assert offenders == []


def test_tools_with_arguments_expose_their_fields(tools):
    for name, tool in tools.items():
        props = tool.inputSchema.get("properties", {})
        if name == "research_match_inbox" or not props:
            continue  # tools without arguments (inbox, my_profile, analyze_work)
        params = props["params"]
        assert params.get("properties"), f"{name}: 'params' has no fields in its advertised schema"


def test_cold_search_schema_names_its_fields_and_limits(tools):
    params = tools["research_match_cold_search"].inputSchema["properties"]["params"]
    assert params["required"] == ["query"]
    assert params["properties"]["query"]["type"] == "string"
    assert params["properties"]["max_results"]["maximum"] == 25
    assert "query" in params["properties"] and "description" in params["properties"]["query"]


def test_deep_search_schema_names_include_scoring(tools):
    params = tools["research_match_deep_search"].inputSchema["properties"]["params"]
    assert {"repo_url", "include_scoring"} <= set(params["properties"])
    assert params["properties"]["include_scoring"]["type"] == "boolean"


def test_nested_models_and_enums_are_inlined(tools):
    """submit_commit nests models and enums; none of them may remain a reference."""
    schema = tools["research_match_submit_commit"].inputSchema
    assert "$ref" not in json.dumps(schema)
    assert "solidity_levels" in schema["properties"]["params"]["properties"]


def test_inlining_is_idempotent():
    assert _inline_tool_schemas(server.mcp) == 0   # everything was already rewritten at import


def test_resolve_leaves_recursive_definitions_alone():
    defs = {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}}
    resolved = _resolve_schema_refs({"$ref": "#/$defs/Node"}, defs)
    assert "$ref" in json.dumps(resolved)          # cycle: the caller keeps FastMCP's original schema


def test_resolve_keeps_sibling_keys_such_as_descriptions():
    defs = {"Thing": {"type": "object", "properties": {"a": {"type": "string"}}}}
    resolved = _resolve_schema_refs({"$ref": "#/$defs/Thing", "description": "the thing"}, defs)
    assert resolved["description"] == "the thing"
    assert resolved["properties"]["a"]["type"] == "string"
