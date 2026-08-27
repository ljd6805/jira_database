from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TOOLS = {"search_jira_knowledge", "get_jira_issue"}


async def _validate_stdio_transport() -> None:
    """실제 subprocess stdio 경계에서 MCP initialize와 tools/list를 검증합니다."""

    stage = "spawn_or_initialize"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jira_collector.mcp_server.server"],
        cwd=PROJECT_ROOT,
    )

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                stage = "list_tools"
                listed = await session.list_tools()
                tool_names = {tool.name for tool in listed.tools}

        if tool_names != EXPECTED_TOOLS:
            raise RuntimeError(
                "MCP tool surface가 예상과 다릅니다: "
                f"expected={sorted(EXPECTED_TOOLS)}, actual={sorted(tool_names)}"
            )

        print(f"python_executable: {sys.executable}")
        print(f"tool_count: {len(tool_names)}")
        print(f"tools: {', '.join(sorted(tool_names))}")
        print("M11_STDIO_HANDSHAKE = PASS")
    except Exception as exc:
        print(f"failure_stage: {stage}")
        print(f"error_type: {type(exc).__name__}")
        print("M11_STDIO_HANDSHAKE = FAIL")
        raise SystemExit(1) from None


def main() -> None:
    asyncio.run(_validate_stdio_transport())


if __name__ == "__main__":
    main()
