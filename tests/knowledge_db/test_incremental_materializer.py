from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from jira_collector.knowledge_db import (
    KnowledgeContract,
    issue_version_id,
    knowledge_generation_id,
    validate_accepted_evidence,
)
from jira_collector.state_store import StateStore


SOURCE_HASH = "sha256:" + "a" * 64


def test_incremental_materializer_imports_with_current_loader_contract() -> None:
    """Real G3에서 발견된 private helper ImportError가 다시 생기지 않게 보호합니다."""

    module = importlib.import_module("jira_collector.knowledge_db.incremental")

    assert hasattr(module, "IncrementalKnowledgeDbMaterializer")


def test_materialize_work_builds_idempotent_candidate_generation(tmp_path: Path) -> None:
    """실제 운영 artifact + State에서 candidate Generation까지 한 번에 검증합니다."""

    module = importlib.import_module("jira_collector.knowledge_db.incremental")
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")
    source_run_id, work_item_id = _seed_completed_work(state, data_root)
    db_path = data_root / "knowledge_db" / "knowledge.sqlite3"

    materializer = module.IncrementalKnowledgeDbMaterializer(
        state,
        data_root,
        db_path,
        skill_version="0.9",
        runtime_version="0.9",
        model_profile="test-profile",
    )

    first = materializer.materialize_work(work_item_id)
    second = materializer.materialize_work(work_item_id)

    assert first == second
    assert first.source_run_id == source_run_id
    assert first.issue_key == "ABC-1"
    assert first.attempt_count == 1
    assert first.knowledge_item_count == 2
    assert first.evidence_count == 6
    assert first.review_count == 1
    assert first.generation_state == "candidate"

    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "pending"
    assert work["knowledge_status"] == "completed"
    assert work["embedding_status"] == "pending"
    assert work["publish_status"] == "pending"

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        generation = connection.execute(
            """
            SELECT state, accepted_attempt_id
            FROM knowledge_generation
            WHERE knowledge_generation_id=?
            """,
            (first.knowledge_generation_id,),
        ).fetchone()
        assert generation is not None
        assert generation["state"] == "candidate"
        assert generation["accepted_attempt_id"] == first.final_attempt_id
        assert _count(connection, "issue") == 1
        assert _count(connection, "issue_version") == 1
        assert _count(connection, "knowledge_generation") == 1
        assert _count(connection, "knowledge_attempt") == 1
        assert _count(connection, "knowledge_item") == 2
        assert _count(connection, "knowledge_evidence") == 6
        assert _count(connection, "knowledge_review") == 1
        assert validate_accepted_evidence(connection) == []


def _seed_completed_work(state: StateStore, data_root: Path) -> tuple[str, str]:
    source_run_id = state.create_source_sync_run("2026-09-01T10:00:00+00:00")
    state.upsert_visible_project(
        source_run_id=source_run_id,
        project_id="10000",
        project_key="ABC",
        project_name="Alpha",
    )
    state.start_source_project_run(
        source_run_id=source_run_id,
        project_id="10000",
        operation_kind="initial_ingest",
        lower_bound=None,
        upper_bound="2026-09-01T10:00:00+00:00",
    )
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id="20000",
        observed_issue_key="ABC-1",
        jira_updated_at="2026-09-01T09:50:00+00:00",
        cursor_updated_at="2026-09-01T09:50:00+00:00",
        cursor_jira_id="20000",
        change_kind="new",
        source_hash=SOURCE_HASH,
    )
    assert work_item_id is not None
    state.commit_source_project(source_run_id, "10000")

    _write_operational_artifacts(data_root, source_run_id)
    contract = KnowledgeContract("0.1", "0.9", "0.9", "test-profile")
    version_id = issue_version_id("20000", SOURCE_HASH)
    generation_id = knowledge_generation_id(version_id, contract.logical_hash())
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)
    assert state.mark_knowledge_completed(
        work_item_id,
        issue_version_id=version_id,
        knowledge_generation_id=generation_id,
    )
    _release_completed_knowledge_work(state, work_item_id, processing_run_id)
    return source_run_id, work_item_id


def _release_completed_knowledge_work(
    state: StateStore,
    work_item_id: str,
    processing_run_id: str,
) -> None:
    """LoopBKnowledgeWorker의 Knowledge checkpoint 이후 handoff 상태를 재현합니다."""

    with state.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE sync_issue_change
            SET work_status='pending'
            WHERE work_item_id=?
              AND last_processing_run_id=?
              AND work_status='running'
              AND knowledge_status='completed'
              AND last_source_committed_run_id=last_observed_source_run_id
              AND superseded_by_work_item_id IS NULL
            """,
            (work_item_id, processing_run_id),
        )
        assert cursor.rowcount == 1
    state.finish_processing_run(
        processing_run_id,
        run_status="partial",
        published_count=0,
        failed_count=0,
        superseded_count=0,
        backlog_after=0,
    )


def _write_operational_artifacts(data_root: Path, source_run_id: str) -> None:
    analysis = _analysis_document(source_run_id)
    package = _input_package(source_run_id)
    knowledge = _knowledge_document()
    review = _pass_review()

    _write_json(
        data_root
        / "analysis"
        / source_run_id
        / "projects"
        / "ABC"
        / "issues"
        / "ABC-1"
        / "analysis.json",
        analysis,
    )
    _write_json(
        data_root
        / "knowledge_input"
        / "runs"
        / source_run_id
        / "issues"
        / "ABC-1.json",
        package,
    )
    _write_json(
        data_root / "knowledge" / "runs" / source_run_id / "issues" / "ABC-1.json",
        knowledge,
    )
    _write_json(
        data_root
        / "knowledge"
        / "runs"
        / source_run_id
        / "reviews"
        / "ABC-1.review.attempt1.json",
        review,
    )


def _analysis_document(source_run_id: str) -> dict[str, Any]:
    issue_path = f"raw/runs/{source_run_id}/projects/ABC/issues/ABC-1/issue.json"
    return {
        "source_run_id": source_run_id,
        "project_id": "10000",
        "project_key": "ABC",
        "issue": {
            "run_id": source_run_id,
            "project_key": "ABC",
            "issue_key": "ABC-1",
            "jira_id": "20000",
            "summary": "테스트 이슈",
            "description_text": "설명 원문",
            "description_format": "text",
            "issue_type": "Bug",
            "status": "Closed",
            "priority": "Major",
            "created_at": "2026-09-01T09:00:00+00:00",
            "updated_at": "2026-09-01T09:50:00+00:00",
            "source_path": issue_path,
        },
        "comments": [
            {
                "run_id": source_run_id,
                "issue_key": "ABC-1",
                "comment_id": "10",
                "sequence": 1,
                "author_name": "Tester",
                "author_key": "tester",
                "created_at": "2026-09-01T09:10:00+00:00",
                "updated_at": "2026-09-01T09:10:00+00:00",
                "body_text": "댓글 근거",
                "body_format": "text",
                "source_path": issue_path,
                "source_page": "page_0001.json",
            }
        ],
        "attachments": [
            {
                "run_id": source_run_id,
                "issue_key": "ABC-1",
                "attachment_id": "20",
                "filename": "trace.txt",
                "author_name": "Tester",
                "author_key": "tester",
                "created_at": "2026-09-01T09:20:00+00:00",
                "size_bytes": 123,
                "mime_type": "text/plain",
                "content_available": False,
                "source_path": issue_path,
            }
        ],
        "relationships": [
            {
                "run_id": source_run_id,
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
        "custom_field_catalog": {
            "customfield_1": {
                "run_id": source_run_id,
                "field_id": "customfield_1",
                "field_name": "Revision",
                "schema_type": "option",
                "schema_items": None,
                "schema_custom": "select",
                "schema_custom_id": None,
                "source_path": issue_path,
            }
        },
        "custom_fields": [
            {
                "run_id": source_run_id,
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
        "warnings": [],
    }


def _input_package(source_run_id: str) -> dict[str, Any]:
    return {
        "package_schema_version": "1.0",
        "run_id": source_run_id,
        "project_key": "ABC",
        "issue_key": "ABC-1",
        "source_hash_profile": "semantic_v2",
        "source_hash": SOURCE_HASH,
        "issue": {
            "jira_id": "20000",
            "summary": "테스트 이슈",
            "description": "설명 원문",
            "description_format": "text",
            "issue_type": "Bug",
            "status": "Closed",
            "priority": "Major",
            "created_at": "2026-09-01T09:00:00+00:00",
            "updated_at": "2026-09-01T09:50:00+00:00",
            "source_path": "raw/runs/source/projects/ABC/issues/ABC-1/issue.json",
        },
        "comments": [],
        "attachments": [],
        "relationships": [],
        "custom_fields": [],
    }


def _knowledge_document() -> dict[str, Any]:
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
                "statement": "모든 source entity를 복원할 수 있다.",
                "evidence_refs": [
                    "description",
                    "comment:10",
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


def _pass_review() -> dict[str, Any]:
    return {
        "issue_key": "ABC-1",
        "score": 9.0,
        "verdict": "PASS",
        "critical_error": False,
        "major_issue_count": 0,
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
        "major_issues": [],
        "improvement_points": [],
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
