from __future__ import annotations

import sqlite3

from .models import KnowledgeDbError


_SOURCE_TYPES = {
    "comment",
    "attachment",
    "relationship",
    "custom_field",
}


def parse_evidence_ref(evidence_ref: str) -> tuple[str, str | None]:
    """Knowledge Schema의 6개 Evidence reference를 type/key로 분해합니다."""

    if evidence_ref in {"summary", "description"}:
        return evidence_ref, None
    if ":" not in evidence_ref:
        raise KnowledgeDbError(f"지원하지 않는 Evidence reference입니다: {evidence_ref}")

    evidence_type, entity_key = evidence_ref.split(":", 1)
    if evidence_type not in _SOURCE_TYPES or not entity_key or ":" in entity_key:
        raise KnowledgeDbError(f"지원하지 않는 Evidence reference입니다: {evidence_ref}")
    return evidence_type, entity_key


def validate_accepted_evidence(connection: sqlite3.Connection) -> list[str]:
    """Accepted Attempt의 모든 Evidence가 실제 source Entity로 복원되는지 검사합니다."""

    rows = connection.execute(
        """
        SELECT e.knowledge_evidence_id, e.evidence_ref, e.evidence_type,
               e.source_run_id, e.source_issue_key, e.source_entity_key,
               g.issue_version_id
        FROM knowledge_evidence AS e
        JOIN knowledge_item AS i
          ON i.knowledge_item_id = e.knowledge_item_id
        JOIN knowledge_attempt AS a
          ON a.knowledge_attempt_id = i.knowledge_attempt_id
        JOIN knowledge_generation AS g
          ON g.knowledge_generation_id = a.knowledge_generation_id
        WHERE g.accepted_attempt_id = a.knowledge_attempt_id
        ORDER BY e.knowledge_evidence_id
        """
    ).fetchall()

    failures: list[str] = []
    for row in rows:
        if not _evidence_exists(connection, row):
            failures.append(
                f"{row['knowledge_evidence_id']}: {row['evidence_ref']} source를 찾을 수 없습니다."
            )
    return failures


def assert_accepted_evidence(connection: sqlite3.Connection) -> None:
    """Evidence round-trip 실패가 하나라도 있으면 materialization을 중단합니다."""

    failures = validate_accepted_evidence(connection)
    if failures:
        preview = "\n".join(failures[:10])
        suffix = "" if len(failures) <= 10 else f"\n... 외 {len(failures) - 10}건"
        raise KnowledgeDbError(f"Evidence round-trip 검증 실패:\n{preview}{suffix}")


def _evidence_exists(connection: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Evidence type별 source lookup 규칙을 적용합니다."""

    evidence_type = str(row["evidence_type"])
    if evidence_type in {"summary", "description"}:
        found = connection.execute(
            "SELECT 1 FROM issue_version WHERE issue_version_id = ?",
            (row["issue_version_id"],),
        ).fetchone()
        return found is not None

    if evidence_type == "comment":
        return _exists(
            connection,
            "SELECT 1 FROM comment WHERE run_id=? AND issue_key=? AND comment_id=?",
            row,
        )
    if evidence_type == "attachment":
        return _attachment_exists(connection, row)
    if evidence_type == "relationship":
        return _relationship_exists(connection, row)
    if evidence_type == "custom_field":
        return _exists(
            connection,
            "SELECT 1 FROM custom_field_value WHERE run_id=? AND issue_key=? AND field_id=?",
            row,
        )
    return False


def _exists(connection: sqlite3.Connection, sql: str, row: sqlite3.Row) -> bool:
    """run/issue/entity key 3개로 source row 존재 여부를 확인합니다."""

    found = connection.execute(
        sql,
        (row["source_run_id"], row["source_issue_key"], row["source_entity_key"]),
    ).fetchone()
    return found is not None


def _attachment_exists(connection: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Attachment ID뿐 아니라 Evidence Issue가 실제 소유 Issue인지 확인합니다."""

    found = connection.execute(
        "SELECT issue_key FROM attachment WHERE run_id=? AND attachment_id=?",
        (row["source_run_id"], row["source_entity_key"]),
    ).fetchone()
    return found is not None and found["issue_key"] == row["source_issue_key"]


def _relationship_exists(connection: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Relationship이 존재하고 현재 Evidence Issue가 edge의 endpoint인지 확인합니다."""

    found = connection.execute(
        """
        SELECT source_issue_key, target_issue_key
        FROM relationship
        WHERE run_id=? AND relationship_id=?
        """,
        (row["source_run_id"], row["source_entity_key"]),
    ).fetchone()
    if found is None:
        return False
    return row["source_issue_key"] in {
        found["source_issue_key"],
        found["target_issue_key"],
    }
