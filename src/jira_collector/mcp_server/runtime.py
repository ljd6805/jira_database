from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from jira_collector.embedding.config import load_embedding_settings
from jira_collector.retrieval import embed_query_text, load_retrieval_searcher

from .service import JiraKnowledgeService


class McpRuntimeSettingsError(ValueError):
    """MCP 실행에 필요한 로컬 artifact 설정이 잘못됐을 때 발생합니다."""


def load_service_from_environment(
    *,
    env: Mapping[str, str] | None = None,
) -> JiraKnowledgeService:
    """환경 변수와 검증된 M7/M9 artifact로 read-only MCP service를 구성합니다."""

    environment = os.environ if env is None else env
    db_path = _required_path(environment, "JIRA_KNOWLEDGE_DB_PATH")
    retrieval_dir = _required_path(environment, "JIRA_RETRIEVAL_ARTIFACT_DIR")
    connection = open_knowledge_db_readonly(db_path)
    searcher = load_retrieval_searcher(retrieval_dir)
    embedding_settings = load_embedding_settings(env=environment)

    def query_embedder(query: str) -> tuple[float, ...]:
        return embed_query_text(query, searcher.manifest, embedding_settings)

    return JiraKnowledgeService(connection, searcher, query_embedder)


def open_knowledge_db_readonly(path: str | Path) -> sqlite3.Connection:
    """존재하는 SQLite만 read-only/query-only로 열어 MCP의 쓰기를 DB 레벨에서 차단합니다."""

    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise McpRuntimeSettingsError(f"Knowledge DB를 찾을 수 없습니다: {db_path}")
    connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _required_path(environment: Mapping[str, str], name: str) -> Path:
    value = str(environment.get(name, "")).strip()
    if not value:
        raise McpRuntimeSettingsError(f"필수 환경 변수 {name}가 비어 있습니다.")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise McpRuntimeSettingsError(f"{name} 경로를 찾을 수 없습니다: {path}")
    return path
