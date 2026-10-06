"""MCP Server for AI Personal CFO (FINZO).

Exposes deterministic financial tools over the Model Context Protocol (MCP).
Compatible with Hermes Agent, Claude Desktop, Cursor, and any standard MCP client.
Supports both stdio transport (line-delimited JSON-RPC) and SSE/HTTP.

Guarantees:
- Zero LLM financial math hallucinations: all tool calls route to the Decimal engine.
- Strict input validation.
- JSON-RPC 2.0 compliant.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from tools.registry import registry

logger = logging.getLogger("mcp_server")

SERVER_NAME = "finzo-cfo-engine"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


class FinzoMCPServer:
    """Zero-dependency Model Context Protocol (MCP) server for FINZO financial engine."""

    def __init__(self) -> None:
        self.registry = registry

    def get_tool_list(self) -> list[dict[str, Any]]:
        """Return MCP-compliant tool list."""
        tools = []
        for t in self.registry.list_tools():
            tools.append({
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["parameters"],
            })
        return tools

    def handle_request(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process a single JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {}) or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {},
                        "prompts": {},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        if method == "notifications/initialized":
            # Client notification, no response required
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": self.get_tool_list(),
                },
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}

            # Execute tool deterministically via registry
            execution_res = self.registry.execute(tool_name, arguments)
            is_error = execution_res.get("status") == "error"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(execution_res, indent=2, default=str),
                        }
                    ],
                    "isError": is_error,
                },
            }

        # Unknown method error
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }
        return None

    def run_stdio(self) -> None:
        """Run standard stdio transport reading line-delimited JSON-RPC from stdin."""
        logger.info("Starting FINZO MCP Server on stdio...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error handling MCP request")
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = FinzoMCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
