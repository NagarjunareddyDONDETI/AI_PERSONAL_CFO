"""Tests for FINZO MCP Server (JSON-RPC 2.0 / MCP compatibility)."""
from __future__ import annotations

import json
import pytest

from mcp_server.server import FinzoMCPServer


@pytest.fixture
def mcp_server() -> FinzoMCPServer:
    return FinzoMCPServer()


def test_mcp_initialize(mcp_server: FinzoMCPServer) -> None:
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "finzo-cfo-engine"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_ping(mcp_server: FinzoMCPServer) -> None:
    req = {"jsonrpc": "2.0", "id": "p1", "method": "ping"}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["result"] == {}


def test_mcp_tools_list(mcp_server: FinzoMCPServer) -> None:
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "calculate_cashflow_summary" in tool_names
    assert "calculate_emergency_runway" in tool_names
    assert "calculate_debt_payoff_timeline" in tool_names


def test_mcp_tool_call_success(mcp_server: FinzoMCPServer) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "calculate_cashflow_summary",
            "arguments": {"income": 5000.0, "expenses": 3000.0},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 3
    assert resp["result"]["isError"] is False
    content_raw = resp["result"]["content"][0]["text"]
    parsed_content = json.loads(content_raw)
    assert parsed_content["status"] == "success"
    assert parsed_content["data"]["net_surplus"] == 2000.0
    assert parsed_content["data"]["savings_rate_pct"] == 40.0


def test_mcp_tool_call_invalid_tool(mcp_server: FinzoMCPServer) -> None:
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool",
            "arguments": {},
        },
    }
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is True


def test_mcp_unknown_method(mcp_server: FinzoMCPServer) -> None:
    req = {"jsonrpc": "2.0", "id": 5, "method": "unknown_rpc_method"}
    resp = mcp_server.handle_request(req)
    assert resp is not None
    assert resp["error"]["code"] == -32601
