from __future__ import annotations

import json
import sqlite3

from jira_collector.knowledge_db import KnowledgeDbError, parse_evidence_ref
from jira_collector.retrieval import RetrievalCandidate

from .models import (
    EvidencePackage,
    EvidenceResolutionError,
    IssueContext,
    ResolvedEvidence,
    StaleKnowledgeError,
)


class EvidenceResolver:
    """M9 RetrievalCandidate를 M7 SQLite의 실제 Evidence까지 복원합니다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        self._connection = connection

    def resolve_candidate(self, candidate: RetrievalCandidate) -> EvidencePackage:
        """한 M9 candidate를 active Knowledge + canonical Evidence package로 변환합니다."""

        knowledge = self._load_active_knowledge(candidate)
        evidence_rows = self._load_evidence_rows(candidate.knowledge_item_id)
        evidence = tuple(
            self._resolve_evidence(row, knowledge) for row in evidence_rows
        )
        return EvidencePackage(
            rank=candidate.rank,
            score=candidate.score,
            faiss_position=candidate.faiss_position,
            embedding_id=candidate.embedding_id,
            knowledge_item_id=candidate.knowledge_item_id,
            category=str(knowledge["category"]),
            statement=str(knowledge["statement"]),
            issue=IssueContext(
                issue_key=str(knowledge["source_issue_key"]),
                status=_optional_text(knowledge["status"]),
                issue_type=_optional_text(knowledge["issue_type"]),
            ),
            evidence=evidence,
        )

    def _load_active_knowledge(self, candidate: RetrievalCandidate) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT i.knowledge_item_id, i.category, i.statement,
                   i.knowledge_attempt_id,
                   a.content_available,
                   g.state, g.accepted_attempt_id, g.issue_version_id,
                   v.source_issue_key, v.summary, v.description,
                   v.description_format, v.status, v.issue_type
            FROM knowledge_item AS i
            JOIN knowledge_attempt AS a
              ON a.knowledge_attempt_id = i.knowledge_attempt_id
            JOIN knowledge_generation AS g
              ON g.knowledge_generation_id = a.knowledge_generation_id
            JOIN issue_version AS v
              ON v.issue_version_id = g.issue_version_id
            WHERE i.knowledge_item_id = ?
            """,
            (candidate.knowledge_item_id,),
        ).fetchone()
        if row is None:
            raise EvidenceResolutionError(
                "KNOWLEDGE_NOT_FOUND",
                candidate.knowledge_item_id,
                f"Knowledge Item을 찾을 수 없습니다: {candidate.knowledge_item_id}",
            )
        if not _is_active_accepted(row):
            raise StaleKnowledgeError(
                "STALE_RETRIEVAL_INDEX",
                candidate.knowledge_item_id,
                f"M9 candidate가 active accepted Knowledge가 아닙니다: {candidate.knowledge_item_id}",
            )
        if str(row["category"]) != candidate.category:
            raise EvidenceResolutionError(
                "CATEGORY_MISMATCH",
                candidate.knowledge_item_id,
                "M9 mapping category와 M7 Knowledge category가 다릅니다.",
            )
        return row

    def _load_evidence_rows(self, knowledge_item_id: str) -> tuple[sqlite3.Row, ...]:
        rows = self._connection.execute(
            """
            SELECT knowledge_evidence_id, knowledge_item_id, ordinal,
                   evidence_ref, evidence_type, source_run_id,
                   source_issue_key, source_entity_key
            FROM knowledge_evidence
            WHERE knowledge_item_id = ?
            ORDER BY ordinal
            """,
            (knowledge_item_id,),
        ).fetchall()
        if not rows:
            raise EvidenceResolutionError(
                "EVIDENCE_NOT_FOUND",
                knowledge_item_id,
                f"Knowledge Item에 Evidence가 없습니다: {knowledge_item_id}",
            )
        return tuple(rows)

    def _resolve_evidence(
        self,
        row: sqlite3.Row,
        knowledge: sqlite3.Row,
    ) -> ResolvedEvidence:
        try:
            evidence_type, entity_key = parse_evidence_ref(str(row["evidence_ref"]))
        except KnowledgeDbError as exc:
            raise self._error(row, "EVIDENCE_REF_INVALID", str(exc)) from exc

        if evidence_type != row["evidence_type"] or entity_key != row["source_entity_key"]:
            raise self._error(row, "EVIDENCE_REF_MISMATCH", "Evidence ref와 DB source key가 다릅니다.")

        if evidence_type in {"summary", "description"}:
            return self._resolve_issue_text(row, knowledge, evidence_type)
        if evidence_type == "comment":
            return self._resolve_comment(row)
        if evidence_type == "attachment":
            return self._resolve_attachment(row)
        if evidence_type == "relationship":
            return self._resolve_relationship(row)
        if evidence_type == "custom_field":
            return self._resolve_custom_field(row)
        raise self._error(row, "EVIDENCE_TYPE_UNSUPPORTED", f"지원하지 않는 Evidence type: {evidence_type}")

    def _resolve_issue_text(
        self,
        row: sqlite3.Row,
        knowledge: sqlite3.Row,
        evidence_type: str,
    ) -> ResolvedEvidence:
        text = knowledge[evidence_type]
        text_format = knowledge["description_format"] if evidence_type == "description" else None
        if text is None:
            raise self._error(row, "EVIDENCE_SOURCE_MISSING", f"{evidence_type} 원문이 비어 있습니다.")
        return self._record(row, text=str(text), text_format=_optional_text(text_format))

    def _resolve_comment(self, row: sqlite3.Row) -> ResolvedEvidence:
        source = self._connection.execute(
            """
            SELECT comment_id, author_name, created_at, updated_at, body, body_format
            FROM comment
            WHERE run_id=? AND issue_key=? AND comment_id=?
            """,
            _source_key(row),
        ).fetchone()
        if source is None:
            raise self._error(row, "EVIDENCE_SOURCE_MISSING", "Comment source를 찾을 수 없습니다.")
        return self._record(
            row,
            text=_optional_text(source["body"]),
            text_format=_optional_text(source["body_format"]),
            metadata={
                "comment_id": source["comment_id"],
                "author_name": source["author_name"],
                "created_at": source["created_at"],
                "updated_at": source["updated_at"],
            },
        )

    def _resolve_attachment(self, row: sqlite3.Row) -> ResolvedEvidence:
        source = self._connection.execute(
            """
            SELECT issue_key, attachment_id, filename, author_name, created_at,
                   size_bytes, mime_type, content_available
            FROM attachment
            WHERE run_id=? AND attachment_id=?
            """,
            (row["source_run_id"], row["source_entity_key"]),
        ).fetchone()
        if source is None or source["issue_key"] != row["source_issue_key"]:
            raise self._error(row, "EVIDENCE_SOURCE_MISSING", "Attachment source를 찾을 수 없습니다.")
        return self._record(
            row,
            metadata={
                "attachment_id": source["attachment_id"],
                "filename": source["filename"],
                "author_name": source["author_name"],
                "created_at": source["created_at"],
                "size_bytes": source["size_bytes"],
                "mime_type": source["mime_type"],
                "content_available": bool(source["content_available"]),
            },
        )

    def _resolve_relationship(self, row: sqlite3.Row) -> ResolvedEvidence:
        source = self._connection.execute(
            """
            SELECT relationship_id, relationship_category, relationship_type,
                   relationship_text, source_issue_key, target_issue_key, derived
            FROM relationship
            WHERE run_id=? AND relationship_id=?
            """,
            (row["source_run_id"], row["source_entity_key"]),
        ).fetchone()
        endpoints = set() if source is None else {source["source_issue_key"], source["target_issue_key"]}
        if source is None or row["source_issue_key"] not in endpoints:
            raise self._error(row, "EVIDENCE_SOURCE_MISSING", "Relationship source를 찾을 수 없습니다.")
        return self._record(
            row,
            text=_optional_text(source["relationship_text"]),
            metadata={
                "relationship_id": source["relationship_id"],
                "relationship_category": source["relationship_category"],
                "relationship_type": source["relationship_type"],
                "source_issue_key": source["source_issue_key"],
                "target_issue_key": source["target_issue_key"],
                "derived": bool(source["derived"]),
            },
        )

    def _resolve_custom_field(self, row: sqlite3.Row) -> ResolvedEvidence:
        source = self._connection.execute(
            """
            SELECT v.field_id, c.field_name, v.actual_type, v.value_kind,
                   v.display_value, v.display_values_json, v.value_id,
                   v.value_ids_json, v.user_keys_json, v.value_shape_json
            FROM custom_field_value AS v
            LEFT JOIN custom_field_catalog AS c
              ON c.run_id=v.run_id AND c.field_id=v.field_id
            WHERE v.run_id=? AND v.issue_key=? AND v.field_id=?
            """,
            _source_key(row),
        ).fetchone()
        if source is None:
            raise self._error(row, "EVIDENCE_SOURCE_MISSING", "Custom Field source를 찾을 수 없습니다.")
        return self._record(
            row,
            text=_optional_text(source["display_value"]),
            metadata={
                "field_id": source["field_id"],
                "field_name": source["field_name"],
                "actual_type": source["actual_type"],
                "value_kind": source["value_kind"],
                "display_values": self._json_field(row, source["display_values_json"]),
                "value_id": source["value_id"],
                "value_ids": self._json_field(row, source["value_ids_json"]),
                "user_keys": self._json_field(row, source["user_keys_json"]),
                "value_shape": self._json_field(row, source["value_shape_json"]),
            },
        )

    def _json_field(self, row: sqlite3.Row, value: object) -> object:
        if value is None:
            return None
        try:
            return json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise self._error(row, "EVIDENCE_SOURCE_INVALID", "Custom Field JSON이 손상됐습니다.") from exc

    @staticmethod
    def _record(
        row: sqlite3.Row,
        *,
        text: str | None = None,
        text_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResolvedEvidence:
        return ResolvedEvidence(
            knowledge_evidence_id=str(row["knowledge_evidence_id"]),
            ordinal=int(row["ordinal"]),
            evidence_ref=str(row["evidence_ref"]),
            evidence_type=str(row["evidence_type"]),
            source_issue_key=str(row["source_issue_key"]),
            source_entity_key=_optional_text(row["source_entity_key"]),
            text=text,
            text_format=text_format,
            metadata={} if metadata is None else metadata,
        )

    @staticmethod
    def _error(row: sqlite3.Row, code: str, message: str) -> EvidenceResolutionError:
        return EvidenceResolutionError(code, str(row["knowledge_item_id"]), message)


def _is_active_accepted(row: sqlite3.Row) -> bool:
    return (
        row["state"] == "active"
        and row["accepted_attempt_id"] == row["knowledge_attempt_id"]
        and bool(row["content_available"])
    )


def _source_key(row: sqlite3.Row) -> tuple[object, object, object]:
    return row["source_run_id"], row["source_issue_key"], row["source_entity_key"]


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)
