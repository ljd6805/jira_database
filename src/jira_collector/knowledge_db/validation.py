from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .evidence import validate_accepted_evidence
from .models import KnowledgeDbError
from .schema import connect_database


_COUNT_TABLES = {
    "issue_count": "issue",
    "generation_count": "knowledge_generation",
    "attempt_count": "knowledge_attempt",
    "knowledge_item_count": "knowledge_item",
    "evidence_count": "knowledge_evidence",
    "review_count": "knowledge_review",
}


@dataclass(frozen=True)
class ExpectedCounts:
    issue_count: int
    generation_count: int
    attempt_count: int
    knowledge_item_count: int
    evidence_count: int
    review_count: int


@dataclass(frozen=True)
class DatabaseSnapshot:
    issue_count: int
    generation_count: int
    attempt_count: int
    knowledge_item_count: int
    evidence_count: int
    review_count: int
    active_generation_count: int
    review_required_count: int
    accepted_evidence_failure_count: int
    foreign_key_failure_count: int
    integrity_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_counts_from_profile(path: str | Path) -> ExpectedCounts:
    """M5 profile.json을 M7 materialization의 expected count 계약으로 변환합니다."""

    profile = _read_json(Path(path))
    integrity = profile.get("integrity")
    knowledge = profile.get("knowledge")
    review = profile.get("review")
    if not isinstance(integrity, dict) or integrity.get("ok") is not True:
        raise KnowledgeDbError("M5 profile integrity.ok가 true가 아닙니다.")
    if not isinstance(knowledge, dict) or not isinstance(review, dict):
        raise KnowledgeDbError("M5 profile의 knowledge/review 구조가 잘못됐습니다.")

    evidence = knowledge.get("evidence")
    if not isinstance(evidence, dict):
        raise KnowledgeDbError("M5 profile의 knowledge.evidence 구조가 잘못됐습니다.")

    issue_count = _required_count(knowledge, "issue_count")
    review_count = _required_count(review, "review_file_count")
    return ExpectedCounts(
        issue_count=issue_count,
        generation_count=issue_count,
        attempt_count=review_count,
        knowledge_item_count=_required_count(knowledge, "total_statement_item_count"),
        evidence_count=_required_count(evidence, "total_evidence_ref_count"),
        review_count=review_count,
    )


def snapshot_database(path: str | Path) -> DatabaseSnapshot:
    """M7 Gate에 필요한 row count와 SQLite/Evidence integrity 상태를 한 번에 읽습니다."""

    connection = connect_database(path)
    try:
        counts = {
            name: _table_count(connection, table)
            for name, table in _COUNT_TABLES.items()
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        evidence_failures = validate_accepted_evidence(connection)
        return DatabaseSnapshot(
            **counts,
            active_generation_count=_state_count(connection, "active"),
            review_required_count=_state_count(connection, "review_required"),
            accepted_evidence_failure_count=len(evidence_failures),
            foreign_key_failure_count=len(foreign_keys),
            integrity_ok=bool(integrity and integrity[0] == "ok"),
        )
    finally:
        connection.close()


def validate_snapshot(
    snapshot: DatabaseSnapshot,
    expected: ExpectedCounts,
) -> list[str]:
    """M5 baseline 및 M6/M7 invariant와 다른 값을 사람이 읽을 수 있게 반환합니다."""

    failures: list[str] = []
    for field in _COUNT_TABLES:
        actual = getattr(snapshot, field)
        wanted = getattr(expected, field)
        if actual != wanted:
            failures.append(f"{field}: expected={wanted}, actual={actual}")
    if snapshot.active_generation_count != expected.issue_count:
        failures.append(
            "active_generation_count: "
            f"expected={expected.issue_count}, actual={snapshot.active_generation_count}"
        )
    if snapshot.review_required_count != 0:
        failures.append(f"review_required_count: expected=0, actual={snapshot.review_required_count}")
    if snapshot.accepted_evidence_failure_count != 0:
        failures.append(
            "accepted_evidence_failure_count: "
            f"expected=0, actual={snapshot.accepted_evidence_failure_count}"
        )
    if snapshot.foreign_key_failure_count != 0:
        failures.append(
            f"foreign_key_failure_count: expected=0, actual={snapshot.foreign_key_failure_count}"
        )
    if not snapshot.integrity_ok:
        failures.append("PRAGMA integrity_check != ok")
    return failures


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeDbError(f"M5 profile을 읽을 수 없습니다: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeDbError(f"M5 profile이 JSON object가 아닙니다: {path}")
    return value


def _required_count(document: dict[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise KnowledgeDbError(f"M5 profile count가 잘못됐습니다: {key}")
    return value


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _state_count(connection: sqlite3.Connection, state: str) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM knowledge_generation WHERE state=?",
            (state,),
        ).fetchone()[0]
    )
