from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Iterator, Protocol

from jira_collector.evidence import CandidateEvidenceBuilder, EvidenceResolver
from jira_collector.retrieval import RetrievalCandidate


QueryEmbedder = Callable[[str], Sequence[float]]


class VectorSearcher(Protocol):
    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int | None = None,
    ) -> tuple[RetrievalCandidate, ...]: ...


@dataclass(frozen=True)
class SearchHead:
    """한 MCP 요청이 끝날 때까지 함께 고정되는 query embedder + vector searcher입니다."""

    searcher: VectorSearcher
    query_embedder: QueryEmbedder


SearchHeadProvider = Callable[[sqlite3.Connection], SearchHead]


class JiraKnowledgeService:
    """M9 Retrieval과 M10 Evidence를 MCP가 호출하기 좋은 읽기 API로 묶습니다."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        searcher: VectorSearcher | None = None,
        query_embedder: QueryEmbedder | None = None,
        *,
        search_head_provider: SearchHeadProvider | None = None,
    ) -> None:
        connection.row_factory = sqlite3.Row
        if search_head_provider is None and (searcher is None or query_embedder is None):
            raise ValueError(
                "static searcher/query_embedder 또는 search_head_provider가 필요합니다."
            )
        self._connection = connection
        self._static_head = (
            SearchHead(searcher, query_embedder)
            if searcher is not None and query_embedder is not None
            else None
        )
        self._search_head_provider = search_head_provider
        self._evidence_builder = CandidateEvidenceBuilder(EvidenceResolver(connection))

    def search_jira_knowledge(self, query: str, top_k: int = 3) -> dict[str, object]:
        """한 read snapshot에 Retrieval head와 Evidence를 pin해 Top-k를 반환합니다."""

        normalized = query.strip()
        if not normalized:
            raise ValueError("query는 비어 있을 수 없습니다.")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k는 1 이상의 정수여야 합니다.")

        with self._read_snapshot():
            head = self._search_head()
            vector = head.query_embedder(normalized)
            candidates = head.searcher.search_vector(vector, top_k=top_k)
            built = self._evidence_builder.build(candidates)
            return {
                "query": normalized,
                "results": [asdict(package) for package in built.results],
                "warnings": [asdict(warning) for warning in built.warnings],
            }

    def get_jira_issue(self, issue_key: str) -> dict[str, object]:
        """한 read snapshot에서 현재 active Knowledge의 Jira Issue 원본을 읽습니다."""

        normalized = issue_key.strip()
        if not normalized:
            raise ValueError("issue_key는 비어 있을 수 없습니다.")
        with self._read_snapshot():
            issue = self._load_active_issue(normalized)
            source_run_id = str(issue["source_run_id"])
            source_issue_key = str(issue["source_issue_key"])
            return {
                "issue": _issue_payload(issue),
                "comments": self._load_comments(source_run_id, source_issue_key),
                "attachments": self._load_attachments(source_run_id, source_issue_key),
                "relationships": self._load_relationships(source_run_id, source_issue_key),
                "custom_fields": self._load_custom_fields(source_run_id, source_issue_key),
            }

    def _search_head(self) -> SearchHead:
        if self._search_head_provider is not None:
            return self._search_head_provider(self._connection)
        if self._static_head is None:
            raise RuntimeError("MCP Retrieval head가 구성되지 않았습니다.")
        return self._static_head

    @contextmanager
    def _read_snapshot(self) -> Iterator[None]:
        """Provider의 active-set 조회와 이후 Evidence SELECT를 같은 SQLite snapshot에 묶습니다."""

        owns_transaction = not self._connection.in_transaction
        if owns_transaction:
            self._connection.execute("BEGIN")
        try:
            yield
        finally:
            if owns_transaction and self._connection.in_transaction:
                self._connection.rollback()

    def _load_active_issue(self, issue_key: str) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT i.jira_id, i.issue_key, i.project_key,
                   v.summary, v.description, v.description_format,
                   v.issue_type, v.status, v.priority, v.created_at, v.updated_at,
                   g.source_run_id, g.source_issue_key
            FROM issue AS i
            JOIN knowledge_generation AS g
              ON g.jira_id=i.jira_id AND g.state='active'
            JOIN issue_version AS v
              ON v.issue_version_id=g.issue_version_id
            JOIN knowledge_attempt AS a
              ON a.knowledge_attempt_id=g.accepted_attempt_id
            WHERE i.issue_key=? AND a.content_available=1
            """,
            (issue_key,),
        ).fetchone()
        if row is None:
            raise LookupError(f"active Jira Issue를 찾을 수 없습니다: {issue_key}")
        return row

    def _load_comments(self, run_id: str, issue_key: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT comment_id, sequence, author_name, created_at, updated_at,
                   body, body_format
            FROM comment
            WHERE run_id=? AND issue_key=?
            ORDER BY sequence
            """,
            (run_id, issue_key),
        ).fetchall()
        return [_row_dict(row) for row in rows]

    def _load_attachments(self, run_id: str, issue_key: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT attachment_id, filename, author_name, created_at,
                   size_bytes, mime_type, content_available
            FROM attachment
            WHERE run_id=? AND issue_key=?
            ORDER BY attachment_id
            """,
            (run_id, issue_key),
        ).fetchall()
        return [
            {**_row_dict(row), "content_available": bool(row["content_available"])}
            for row in rows
        ]

    def _load_relationships(self, run_id: str, issue_key: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT relationship_id, relationship_category, relationship_type,
                   relationship_text, source_issue_key, target_issue_key, derived
            FROM relationship
            WHERE run_id=? AND (source_issue_key=? OR target_issue_key=?)
            ORDER BY relationship_id
            """,
            (run_id, issue_key, issue_key),
        ).fetchall()
        return [{**_row_dict(row), "derived": bool(row["derived"])} for row in rows]

    def _load_custom_fields(self, run_id: str, issue_key: str) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT v.field_id, c.field_name, v.actual_type, v.value_kind,
                   v.display_value, v.display_values_json, v.value_id,
                   v.value_ids_json, v.user_keys_json, v.value_shape_json
            FROM custom_field_value AS v
            LEFT JOIN custom_field_catalog AS c
              ON c.run_id=v.run_id AND c.field_id=v.field_id
            WHERE v.run_id=? AND v.issue_key=?
            ORDER BY v.field_id
            """,
            (run_id, issue_key),
        ).fetchall()
        return [_row_dict(row) for row in rows]


def _issue_payload(row: sqlite3.Row) -> dict[str, object]:
    allowed = (
        "jira_id", "issue_key", "project_key", "summary", "description",
        "description_format", "issue_type", "status", "priority",
        "created_at", "updated_at",
    )
    return {key: row[key] for key in allowed}


def _row_dict(row: sqlite3.Row) -> dict[str, object]:
    return {key: row[key] for key in row.keys()}
