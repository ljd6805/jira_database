from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jira_collector.knowledge_db import (
    KnowledgeDbError,
    KnowledgeDbMaterializer,
    validate_accepted_evidence,
)
from jira_collector.knowledge_input import IssueKnowledgeInputBuilder


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_analysis(data_root: Path) -> None:
    """6개 Evidence type을 모두 만들 수 있는 최소 ANALYSIS Run을 구성합니다."""

    run = data_root / "analysis" / "run1"
    run.mkdir(parents=True)
    raw = data_root / "raw" / "runs" / "run1" / "ABC-1"
    issue_path = str(raw / "issue.json")
    (run / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run1",
                "issues": {"status": "completed"},
                "comments": {"status": "completed"},
                "attachments": {"status": "completed"},
                "relationships": {"status": "completed"},
                "custom_fields": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        run / "issues.jsonl",
        [
            {
                "run_id": "run1",
                "project_key": "ABC",
                "issue_key": "ABC-1",
                "jira_id": "10001",
                "summary": "테스트 이슈",
                "description_text": "설명 원문",
                "description_format": "text",
                "issue_type": "Bug",
                "status": "Closed",
                "priority": "Major",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-02T00:00:00Z",
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "comments.jsonl",
        [
            {
                "run_id": "run1",
                "issue_key": "ABC-1",
                "comment_id": "10",
                "sequence": 1,
                "author_name": "Tester",
                "author_key": "tester",
                "created_at": "2026-08-01T01:00:00Z",
                "updated_at": "2026-08-01T01:00:00Z",
                "body_text": "댓글 근거",
                "body_format": "text",
                "source_path": str(raw / "comments" / "page_0001.json"),
                "source_page": "page_0001.json",
            }
        ],
    )
    _write_structure_rows(run, issue_path)


def _write_structure_rows(run: Path, issue_path: str) -> None:
    _write_jsonl(
        run / "attachments.jsonl",
        [
            {
                "run_id": "run1",
                "issue_key": "ABC-1",
                "attachment_id": "20",
                "filename": "trace.txt",
                "author_name": "Tester",
                "author_key": "tester",
                "created_at": "2026-08-01T02:00:00Z",
                "size_bytes": 123,
                "mime_type": "text/plain",
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "issue_relationships.jsonl",
        [
            {
                "run_id": "run1",
                "relationship_id": "30",
                "relationship_category": "issue_link",
                "relationship_type": "Blocks",
                "relationship_text": "blocks",
                "source_issue_key": "ABC-1",
                "target_issue_key": "ABC-9",
                "derived": False,
                "source_path": issue_path,
            }
        ],
    )
    _write_custom_fields(run, issue_path)


def _write_custom_fields(run: Path, issue_path: str) -> None:
    _write_jsonl(
        run / "custom_field_catalog.jsonl",
        [
            {
                "run_id": "run1",
                "field_id": "customfield_1",
                "field_name": "Revision",
                "schema_type": "option",
                "schema_items": None,
                "schema_custom": "select",
                "schema_custom_id": None,
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "custom_field_values.jsonl",
        [
            {
                "run_id": "run1",
                "issue_key": "ABC-1",
                "field_id": "customfield_1",
                "actual_type": "object",
                "value_kind": "option",
                "display_value": "EVT",
                "display_values": [],
                "value_id": "1",
                "value_ids": [],
                "user_keys": [],
                "value_shape": ["id", "value"],
                "source_path": issue_path,
            }
        ],
    )


def _knowledge_document(comment_ref: str = "comment:10") -> dict[str, object]:
    return {
        "knowledge_schema_version": "0.1",
        "issue_key": "ABC-1",
        "issue_summary": {
            "statement": "테스트 이슈의 요약이다.",
            "evidence_refs": ["summary"],
        },
        "problem_or_goal": [],
        "key_findings": [
            {
                "statement": "여러 원문 Entity에서 확인된 핵심 지식이다.",
                "evidence_refs": [
                    "description",
                    comment_ref,
                    "attachment:20",
                    "relationship:30",
                    "custom_field:customfield_1",
                ],
            }
        ],
        "actions_and_decisions": [],
        "outcomes": [],
        "open_items": [],
    }


def _review(verdict: str) -> dict[str, object]:
    passed = verdict == "PASS"
    return {
        "issue_key": "ABC-1",
        "score": 9.0 if passed else 8.0,
        "verdict": verdict,
        "critical_error": False,
        "major_issue_count": 0 if passed else 1,
        "category_scores": {
            "factual_fidelity": 2.8,
            "evidence_coverage": 1.8,
            "certainty_preservation": 1.3,
            "classification": 1.3,
            "retrieval_value": 0.9,
            "language_quality": 0.9,
        },
        "audit_findings": {
            "fact_audit": [],
            "causal_claim_audit": [],
            "evidence_audit": [],
            "classification_audit": [],
            "missing_knowledge_audit": [],
            "duplication_audit": [],
        },
        "critical_issues": [],
        "major_issues": (
            []
            if passed
            else [
                {
                    "type": "coverage",
                    "location": "key_findings[0]",
                    "message": "근거를 보완해야 한다.",
                }
            ]
        ),
        "improvement_points": [],
    }


def _write_knowledge_artifacts(
    data_root: Path,
    *,
    comment_ref: str = "comment:10",
) -> None:
    root = data_root / "knowledge" / "runs" / "run1"
    issue_root = root / "issues"
    review_root = root / "reviews"
    issue_root.mkdir(parents=True)
    review_root.mkdir(parents=True)
    (issue_root / "ABC-1.json").write_text(
        json.dumps(_knowledge_document(comment_ref), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt_no, verdict in ((1, "REGENERATE"), (2, "PASS")):
        path = review_root / f"ABC-1.review.attempt{attempt_no}.json"
        path.write_text(
            json.dumps(_review(verdict), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _fixture(data_root: Path, *, comment_ref: str = "comment:10") -> None:
    _write_analysis(data_root)
    IssueKnowledgeInputBuilder(data_root).build_run("run1")
    _write_knowledge_artifacts(data_root, comment_ref=comment_ref)


def _materializer(data_root: Path, db_path: Path) -> KnowledgeDbMaterializer:
    return KnowledgeDbMaterializer(
        data_root,
        db_path,
        skill_version="0.9",
        runtime_version="0.9",
        model_profile="test-profile",
    )


def test_materializes_idempotently_and_round_trips_all_evidence(tmp_path: Path) -> None:
    """M7 핵심 Gate: 재적재 무중복과 6종 Evidence round-trip을 함께 검증합니다."""

    data_root = tmp_path / "data"
    db_path = tmp_path / "knowledge.sqlite3"
    _fixture(data_root)
    materializer = _materializer(data_root, db_path)

    first = materializer.materialize_run("run1")
    second = materializer.materialize_run("run1")

    assert first == second
    assert first.issue_count == 1
    assert first.generation_count == 1
    assert first.attempt_count == 2
    assert first.knowledge_item_count == 2
    assert first.evidence_count == 6
    assert first.review_count == 2

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        assert _count(connection, "issue") == 1
        assert _count(connection, "issue_version") == 1
        assert _count(connection, "knowledge_generation") == 1
        assert _count(connection, "knowledge_attempt") == 2
        assert _count(connection, "knowledge_item") == 2
        assert _count(connection, "knowledge_evidence") == 6
        assert _count(connection, "knowledge_review") == 2
        assert validate_accepted_evidence(connection) == []

        generation = connection.execute(
            "SELECT state, accepted_attempt_id FROM knowledge_generation"
        ).fetchone()
        attempts = connection.execute(
            "SELECT attempt_no, content_available FROM knowledge_attempt ORDER BY attempt_no"
        ).fetchall()
        assert generation["state"] == "active"
        assert generation["accepted_attempt_id"] is not None
        assert [(row["attempt_no"], row["content_available"]) for row in attempts] == [
            (1, 0),
            (2, 1),
        ]


def test_materializes_legacy_object_and_string_critical_findings(tmp_path: Path) -> None:
    """M4 legacy object와 current string Critical Finding을 모두 손실 없이 저장합니다."""

    data_root = tmp_path / "data"
    db_path = tmp_path / "knowledge.sqlite3"
    _fixture(data_root)
    review_path = (
        data_root
        / "knowledge"
        / "runs"
        / "run1"
        / "reviews"
        / "ABC-1.review.attempt1.json"
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["critical_error"] = True
    review["critical_issues"] = [
        {
            "type": "certainty",
            "location": "issue_summary",
            "message": "가능성을 확정 사실로 승격했다.",
        },
        "문자열 형식 Critical Finding도 보존한다.",
    ]
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _materializer(data_root, db_path).materialize_run("run1")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT finding_type, location, message
            FROM review_finding
            WHERE finding_group='critical'
            ORDER BY ordinal
            """
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("certainty", "issue_summary", "가능성을 확정 사실로 승격했다."),
        ("", "", "문자열 형식 Critical Finding도 보존한다."),
    ]


def test_materializes_legacy_duplicate_evidence_once(tmp_path: Path) -> None:
    """M4 historical duplicate Evidence는 첫 occurrence의 raw ordinal만 보존합니다."""

    data_root = tmp_path / "data"
    db_path = tmp_path / "knowledge.sqlite3"
    _fixture(data_root)
    knowledge_path = data_root / "knowledge" / "runs" / "run1" / "issues" / "ABC-1.json"
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    refs = knowledge["key_findings"][0]["evidence_refs"]
    refs.insert(2, "comment:10")
    knowledge_path.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = _materializer(data_root, db_path).materialize_run("run1")

    assert result.evidence_count == 6
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT e.ordinal, e.evidence_ref
            FROM knowledge_evidence e
            JOIN knowledge_item i ON i.knowledge_item_id=e.knowledge_item_id
            WHERE i.category='key_findings' AND i.ordinal=0
            ORDER BY e.ordinal
            """
        ).fetchall()

    assert rows == [
        (0, "description"),
        (1, "comment:10"),
        (3, "attachment:20"),
        (4, "relationship:30"),
        (5, "custom_field:customfield_1"),
    ]


def test_missing_evidence_rolls_back_run_materialization(tmp_path: Path) -> None:
    """Accepted Knowledge가 존재하지 않는 source를 참조하면 DB 적재를 성공 처리하지 않습니다."""

    data_root = tmp_path / "data"
    db_path = tmp_path / "knowledge.sqlite3"
    _fixture(data_root, comment_ref="comment:999")

    with pytest.raises(KnowledgeDbError, match="Evidence round-trip"):
        _materializer(data_root, db_path).materialize_run("run1")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pipeline_run").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM knowledge_generation").fetchone()[0] == 0


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
