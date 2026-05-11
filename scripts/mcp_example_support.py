"""
scripts/mcp_example_support.py
文件说明：MCP client 示例共享的标准库辅助函数。
主要职责：提供 JSON-RPC stdio client、resource URI 构造和轻量 risk schema 校验。
依赖边界：仅供本仓库示例脚本和测试复用，不访问真实 Keepa API。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from keepa_cli.risk_schema import RISK_SCHEMA_URI, risk_schema_summary, validate_risk_taxonomy



class McpClientError(RuntimeError):
    """MCP client 示例中的协议或工具调用错误。"""


class KeepaMcpClient:
    """最小 JSON-RPC stdio client；生产集成可替换为宿主 Agent 的 MCP SDK。"""

    def __init__(self, command: Sequence[str]) -> None:
        self._next_id = 1
        self._process = subprocess.Popen(
            list(command),
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": message_id, "method": method, "params": dict(params or {})}
        if not self._process.stdin or not self._process.stdout:
            raise McpClientError("MCP subprocess pipes are not available")
        self._process.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._process.stdin.flush()
        raw = self._process.stdout.readline()
        if not raw:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise McpClientError(f"MCP subprocess closed before response; stderr={stderr.strip()}")
        response = json.loads(raw)
        if response.get("error"):
            raise McpClientError(json.dumps(response["error"], ensure_ascii=False, separators=(",", ":")))
        return response["result"]

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None, *, allow_error: bool = False) -> dict[str, Any]:
        result = self.call_tool_result(name, arguments, allow_error=allow_error)
        return result["structuredContent"]

    def call_tool_result(self, name: str, arguments: Mapping[str, Any] | None = None, *, allow_error: bool = False) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": dict(arguments or {})})
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            raise McpClientError(f"tool {name} did not return structuredContent")
        if not allow_error and not payload.get("ok"):
            raise McpClientError(json.dumps(payload.get("error", payload), ensure_ascii=False, separators=(",", ":")))
        result["structuredContent"] = payload
        return result

    def read_resource_json(self, uri: str) -> dict[str, Any]:
        result = self.request("resources/read", {"uri": uri})
        contents = result.get("contents") or []
        if not contents:
            raise McpClientError(f"resource {uri} returned no contents")
        text = contents[0].get("text")
        if not isinstance(text, str):
            raise McpClientError(f"resource {uri} is not a text JSON resource")
        return json.loads(text)

    def read_resource_text(self, uri: str) -> tuple[str, str]:
        result = self.request("resources/read", {"uri": uri})
        contents = result.get("contents") or []
        if not contents:
            raise McpClientError(f"resource {uri} returned no contents")
        text = contents[0].get("text")
        if not isinstance(text, str):
            raise McpClientError(f"resource {uri} is not a text resource")
        return text, str(contents[0].get("mimeType") or "")


def tool_names(result: Mapping[str, Any]) -> list[str]:
    tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    return [str(tool.get("name")) for tool in tools if isinstance(tool, Mapping)]


def research_resource_uri(cache_key: str, suffix: str = "") -> str:
    return f"keepa://research/{cache_key}{suffix}"


def graph_counts(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), Mapping) else {}
    graph = data.get("research_graph") if isinstance(data.get("research_graph"), Mapping) else {}
    counts = summary.get("entity_counts") or graph.get("entity_counts") or {}
    return dict(counts) if isinstance(counts, Mapping) else {}


def add_common_example_args(parser: Any) -> None:
    parser.add_argument("--save-summary", help="Optional path to write the compact example summary JSON.")


def emit_summary(summary: Mapping[str, Any], save_summary: str | None) -> None:
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if save_summary:
        path = Path(save_summary)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
