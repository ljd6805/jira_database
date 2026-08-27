from __future__ import annotations

from .runtime import McpRuntimeSettingsError, load_service_from_environment, open_knowledge_db_readonly
from .service import JiraKnowledgeService


def create_mcp_server(service: JiraKnowledgeService):
    """server 모듈을 지연 import해 ``python -m ...server`` 실행 경고를 방지합니다."""

    from .server import create_mcp_server as _create_mcp_server

    return _create_mcp_server(service)


__all__ = [
    "JiraKnowledgeService",
    "McpRuntimeSettingsError",
    "create_mcp_server",
    "load_service_from_environment",
    "open_knowledge_db_readonly",
]
