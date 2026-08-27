from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .runtime import load_service_from_environment
from .service import JiraKnowledgeService


READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=False,
)


def create_mcp_server(service: JiraKnowledgeService) -> MCPServer:
    """검증된 Jira Knowledge service를 읽기 전용 MCP 2-tool surface로 노출합니다."""

    mcp = MCPServer(
        "jira-knowledge",
        instructions=(
            "Jira Knowledge를 검색하고 근거를 조회하는 읽기 전용 서버입니다. "
            "최종 답변은 반환된 Knowledge와 Evidence를 근거로 작성하세요."
        ),
    )

    @mcp.tool(
        title="Search Jira knowledge",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def search_jira_knowledge(query: str, top_k: int = 3) -> dict[str, object]:
        """자연어 질문과 관련된 Knowledge와 실제 Jira Evidence를 찾습니다."""

        return service.search_jira_knowledge(query, top_k)

    @mcp.tool(
        title="Get Jira issue",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def get_jira_issue(issue_key: str) -> dict[str, object]:
        """정확한 Issue key의 현재 active Jira snapshot과 source 정보를 읽습니다."""

        return service.get_jira_issue(issue_key)

    return mcp


def main() -> None:
    """환경 설정으로 stdio MCP 서버를 실행합니다."""

    service = load_service_from_environment()
    create_mcp_server(service).run()


if __name__ == "__main__":
    main()
