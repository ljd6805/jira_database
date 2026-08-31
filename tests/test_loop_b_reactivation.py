from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jira_collector.knowledge_db.ids import KnowledgeContract
from jira_collector.knowledge_processing import (
    KnowledgeProcessResult,
    LoopBKnowledgeWorker,
)
from jira_collector.state_store import StateStore


def _knowledge() -> dict[str, Any]:
    item = {"statement": "문장", "evidence_refs": ["summary"]}
    return {
        "knowledge_schema_version": "0.1",
        "issue_key": "ABC-1",
        "issue_summary": item,
        "problem_or_goal": [],
        "key_findings": [item],
        "actions_and_decisions": [],
        "outcomes": [],
        "open_items": [],
    }


class SuccessProcessor:
    def process(
        self,
        *,
        work_item: Any,
        input_path: Path,
        output_path: Path,
        review_dir: Path,
    ) -> KnowledgeProcessResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_knowledge(), ensure_ascii=False), encoding="utf-8")
        review_path = review_dir / "ABC-1.review.attempt1.json"
        review_path.write_text(
            json.dumps(
                {
                    "issue_key": "ABC-1",
                    "score": 9.0,
                    "verdict": "PASS",
                    "critical_error": False,
                    "major_issue_count": 0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return KnowledgeProcessResult(output_path, (review_path,), 1, 9.0)


def _start_project(
    state: StateStore,
    *,
    run_id: str,
    lower: str | None,
    upper: str,
    operation: str,
) -> None:
    state.upsert_visible_project(
        source_run_id=run_id,
        project_id="10000",
        project_key="ABC",
        project_name="Alpha",
    )
    state.start_source_project_run(
        source_run_id=run_id,
        project_id="10000",
        operation_kind=operation,
        lower_bound=lower,
        upper_bound=upper,
    )


def _record(
    state: StateStore,
    *,
    run_id: str,
    source_hash: str,
    updated: str,
    change_kind: str,
) -> str:
    work_id = state.record_source_candidate(
        source_run_id=run_id,
        project_id="10000",
        jira_id="20000",
        observed_issue_key="ABC-1",
        jira_updated_at=updated,
        cursor_updated_at=updated,
        cursor_jira_id="20000",
        change_kind=change_kind,
        source_hash=source_hash,
    )
    assert work_id is not None
    return work_id


def _write_input(data_root: Path, source_run_id: str, source_hash: str) -> None:
    path = (
        data_root
        / "knowledge_input"
        / "runs"
        / source_run_id
        / "issues"
        / "ABC-1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": source_run_id,
                "issue_key": "ABC-1",
                "source_hash": source_hash,
                "source_hash_profile": "semantic_v2",
                "issue": {"jira_id": "20000", "summary": "summary", "description": "desc"},
                "comments": [],
                "attachments": [],
                "relationships": [],
                "custom_fields": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_reactivated_stale_running_semantic_state_is_retryable(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")

    run_a1 = state.create_source_sync_run("2026-08-31T10:00:00+00:00")
    _start_project(state, run_id=run_a1, lower=None, upper="2026-08-31T10:00:00+00:00", operation="initial_ingest")
    work_a = _record(
        state,
        run_id=run_a1,
        source_hash="sha256:" + "a" * 64,
        updated="2026-08-31T09:30:00+00:00",
        change_kind="new",
    )
    state.commit_source_project(run_a1, "10000")
    processing = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_a, processing)
    assert state.mark_knowledge_running(work_a)

    run_b = state.create_source_sync_run("2026-08-31T11:00:00+00:00")
    _start_project(
        state,
        run_id=run_b,
        lower="2026-08-31T09:55:00+00:00",
        upper="2026-08-31T11:00:00+00:00",
        operation="delta",
    )
    work_b = _record(
        state,
        run_id=run_b,
        source_hash="sha256:" + "b" * 64,
        updated="2026-08-31T10:30:00+00:00",
        change_kind="changed",
    )
    state.commit_source_project(run_b, "10000")
    assert state.get_work_item(work_a)["work_status"] == "superseded"
    assert state.get_work_item(work_a)["knowledge_status"] == "running"

    run_a2 = state.create_source_sync_run("2026-08-31T12:00:00+00:00")
    _start_project(
        state,
        run_id=run_a2,
        lower="2026-08-31T10:55:00+00:00",
        upper="2026-08-31T12:00:00+00:00",
        operation="delta",
    )
    replayed_a = _record(
        state,
        run_id=run_a2,
        source_hash="sha256:" + "a" * 64,
        updated="2026-08-31T11:30:00+00:00",
        change_kind="changed",
    )
    assert replayed_a == work_a
    state.commit_source_project(run_a2, "10000")
    reactivated = state.get_work_item(work_a)
    assert reactivated["work_status"] == "pending"
    assert reactivated["knowledge_status"] == "running"
    assert state.get_work_item(work_b)["work_status"] == "superseded"

    _write_input(data_root, run_a2, "sha256:" + "a" * 64)
    worker = LoopBKnowledgeWorker(
        state,
        data_root,
        SuccessProcessor(),
        knowledge_contract=KnowledgeContract(
            knowledge_schema_version="0.1",
            skill_version="0.9",
            runtime_version="0.9",
            model_profile="test-profile",
        ),
    )
    result = worker.run(limit=1)

    assert result.knowledge_completed_count == 1
    current = state.get_work_item(work_a)
    assert current["knowledge_status"] == "completed"
    assert current["work_status"] == "pending"
    assert current["last_observed_source_run_id"] == run_a2
