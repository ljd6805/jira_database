#!/usr/bin/env python3
"""실제 M7/M9/BGE-M3를 MCP로 연결해 M10 end-to-end Gate를 안전한 집계만 출력하며 검증합니다."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Mapping

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from mcp import Client

from jira_collector.mcp_server import create_mcp_server, load_service_from_environment
from jira_collector.mcp_server.validation import validate_m10_payloads


async def _run_real_gate(environment: Mapping[str, str]) -> int:
    query = str(environment.get("M10_REAL_RUN_QUERY", "")).strip()
    if not query:
        print("오류: M10_REAL_RUN_QUERY 환경 변수가 비어 있습니다.", file=sys.stderr)
        return 1

    service = load_service_from_environment(env=environment)
    server = create_mcp_server(service)
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        tool_names = {tool.name for tool in listed.tools}
        expected = {"search_jira_knowledge", "get_jira_issue"}
        if tool_names != expected:
            print(f"tool_surface: FAIL ({len(tool_names)} tools)")
            return 1

        search = await client.call_tool(
            "search_jira_knowledge",
            {"query": query, "top_k": 3},
        )
        search_payload = _structured(search.structured_content, "search_jira_knowledge")
        issue_key = _first_issue_key(search_payload)
        if issue_key is None:
            print("search_result_count: 0")
            print("M10_REAL_RUN = FAIL")
            return 1

        issue = await client.call_tool("get_jira_issue", {"issue_key": issue_key})
        issue_payload = _structured(issue.structured_content, "get_jira_issue")
        validation = validate_m10_payloads(search_payload, issue_payload)

    print("tool_count: 2")
    print(f"search_result_count: {validation.search_result_count}")
    print(f"evidence_count: {validation.evidence_count}")
    print(f"warning_count: {validation.warning_count}")
    print(f"path_leak_count: {validation.path_leak_count}")
    print(f"issue_lookup_ok: {str(validation.issue_lookup_ok).lower()}")
    print(f"failure_count: {len(validation.failures)}")
    print(f"M10_REAL_RUN = {'PASS' if validation.passed else 'FAIL'}")
    return 0 if validation.passed else 1


def _structured(value: object, tool_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{tool_name} structured_content가 object가 아닙니다.")
    return value


def _first_issue_key(payload: Mapping[str, object]) -> str | None:
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, Mapping):
        return None
    issue = first.get("issue")
    if not isinstance(issue, Mapping):
        return None
    issue_key = issue.get("issue_key")
    return issue_key if isinstance(issue_key, str) and issue_key else None


def main() -> int:
    try:
        return asyncio.run(_run_real_gate(os.environ))
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        print("M10_REAL_RUN = FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
