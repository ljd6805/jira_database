from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

from jira_collector.embedding.config import load_embedding_settings
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval import embed_query_text, load_retrieval_searcher
from jira_collector.retrieval_head import (
    active_generation_ids_from_connection,
    retrieval_artifact_dir_for_generation_set,
)

from .service import JiraKnowledgeService, SearchHead, SearchHeadProvider


class McpRuntimeSettingsError(ValueError):
    """MCP 실행에 필요한 로컬 artifact 설정이 잘못됐을 때 발생합니다."""


def load_service_from_environment(
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = ".env",
) -> JiraKnowledgeService:
    """환경 변수와 request-pinned active Knowledge/Retrieval head로 MCP를 구성합니다."""

    environment = _load_runtime_environment(env=env, dotenv_path=dotenv_path)
    db_path = _required_path(environment, "JIRA_KNOWLEDGE_DB_PATH")
    connection = open_knowledge_db_readonly(db_path)
    embedding_settings = load_embedding_settings(dotenv_path=None, env=environment)
    retrieval_root = _optional_path(environment, "JIRA_RETRIEVAL_ARTIFACT_ROOT")

    if retrieval_root is not None:
        provider = _build_operational_search_head_provider(
            retrieval_root,
            embedding_settings,
        )
        return JiraKnowledgeService(
            connection,
            search_head_provider=provider,
        )

    retrieval_dir = _required_path(environment, "JIRA_RETRIEVAL_ARTIFACT_DIR")
    searcher = load_retrieval_searcher(retrieval_dir)

    def query_embedder(query: str) -> tuple[float, ...]:
        return embed_query_text(query, searcher.manifest, embedding_settings)

    return JiraKnowledgeService(connection, searcher, query_embedder)


def _build_operational_search_head_provider(
    retrieval_root: Path,
    embedding_settings,
) -> SearchHeadProvider:
    """한 read snapshot의 active set에 맞는 검증 bundle을 선택하고 searcher를 cache합니다."""

    cache: dict[tuple[str, ...], object] = {}

    def provide(connection: sqlite3.Connection) -> SearchHead:
        generations = active_generation_ids_from_connection(connection)
        key = tuple(sorted(generations))
        if not key:
            raise McpRuntimeSettingsError("active Knowledge Generation이 아직 없습니다.")
        searcher = cache.get(key)
        if searcher is None:
            try:
                artifact_dir = retrieval_artifact_dir_for_generation_set(
                    retrieval_root,
                    generations,
                )
                searcher = load_retrieval_searcher(artifact_dir)
            except (KnowledgeDbError, sqlite3.Error, OSError) as exc:
                raise McpRuntimeSettingsError(
                    "현재 MCP read snapshot의 active Generation 집합과 일치하는 "
                    f"Retrieval bundle을 찾지 못했습니다: {exc}"
                ) from exc
            cache.clear()
            cache[key] = searcher

        def query_embedder(query: str) -> tuple[float, ...]:
            return embed_query_text(query, searcher.manifest, embedding_settings)

        return SearchHead(searcher=searcher, query_embedder=query_embedder)

    return provide


def _load_runtime_environment(
    *,
    env: Mapping[str, str] | None,
    dotenv_path: str | Path | None,
) -> Mapping[str, str]:
    """서비스 실행은 .env를 기본으로 읽고 기존 OS 환경 변수는 우선 보존합니다."""

    if env is not None:
        return env
    if dotenv_path is not None:
        load_dotenv(Path(dotenv_path), override=False)
    return os.environ


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
    path = _optional_path(environment, name)
    if path is None:
        raise McpRuntimeSettingsError(f"필수 환경 변수 {name}가 비어 있습니다.")
    return path


def _optional_path(environment: Mapping[str, str], name: str) -> Path | None:
    value = str(environment.get(name, "")).strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise McpRuntimeSettingsError(f"{name} 경로를 찾을 수 없습니다: {path}")
    return path
