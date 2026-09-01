from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jira_collector.stale_recovery import recover_stale_inflight
from jira_collector.state_store import StateStore


def _seed_ready_work(state: StateStore) -> str:
    source_run_id = state.create_source_sync_run("2026-09-01T08:00:00+00:00")
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
        upper_bound="2026-09-01T08:00:00+00:00",
    )
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id="20000",
        observed_issue_key="ABC-1",
        jira_updated_at="2026-09-01T07:50:00+00:00",
        cursor_updated_at="2026-09-01T07:50:00+00:00",
        cursor_jira_id="20000",
        change_kind="new",
        source_hash="sha256:" + "a" * 64,
    )
    assert work_item_id is not None
    state.commit_source_project(source_run_id, "10000")
    return work_item_id


def _set_updated_at(state: StateStore, work_item_id: str, value: str) -> None:
    with state.connect() as connection:
        connection.execute(
            "UPDATE sync_issue_change SET updated_at = ? WHERE work_item_id = ?",
            (value, work_item_id),
        )


def test_stale_knowledge_running_is_recovered_to_failed_backlog(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state" / "collector.db")
    work_item_id = _seed_ready_work(state)
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)
    _set_updated_at(state, work_item_id, "2026-09-01T08:00:00+00:00")

    result = recover_stale_inflight(
        state,
        stage="knowledge",
        stale_after_seconds=300,
        now=datetime(2026, 9, 1, 8, 10, tzinfo=timezone.utc),
    )

    assert result.recovered_work_count == 1
    assert result.recovered_processing_run_count == 1
    assert result.work_item_ids == (work_item_id,)
    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "failed"
    assert work["knowledge_status"] == "failed"
    assert work["error_stage"] == "knowledge"
    assert "stale in-flight recovery" in str(work["error_message"])

    with state.connect() as connection:
        run = connection.execute(
            "SELECT * FROM processing_run WHERE processing_run_id = ?",
            (processing_run_id,),
        ).fetchone()
    assert run is not None
    assert run["run_status"] == "failed"
    assert run["finished_at"] is not None
    assert run["failed_count"] == 1
    assert run["backlog_after"] == 1


def test_fresh_knowledge_running_is_not_recovered(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state" / "collector.db")
    work_item_id = _seed_ready_work(state)
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)
    _set_updated_at(state, work_item_id, "2026-09-01T08:09:30+00:00")

    result = recover_stale_inflight(
        state,
        stage="knowledge",
        stale_after_seconds=300,
        now=datetime(2026, 9, 1, 8, 10, tzinfo=timezone.utc),
    )

    assert result.recovered_work_count == 0
    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "running"
    assert work["knowledge_status"] == "running"


def test_force_recovery_with_zero_seconds_recovers_current_smoke_stuck_work(
    tmp_path: Path,
) -> None:
    state = StateStore(tmp_path / "state" / "collector.db")
    work_item_id = _seed_ready_work(state)
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)

    result = recover_stale_inflight(
        state,
        stage="knowledge",
        stale_after_seconds=0,
        now=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )

    assert result.recovered_work_count == 1
    assert state.get_work_item(work_item_id)["work_status"] == "failed"


def test_stale_embedding_running_preserves_completed_knowledge(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state" / "collector.db")
    work_item_id = _seed_ready_work(state)

    knowledge_run = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, knowledge_run)
    assert state.mark_knowledge_running(work_item_id)
    assert state.mark_knowledge_completed(
        work_item_id,
        issue_version_id="iv_test",
        knowledge_generation_id="kg_test",
    )
    with state.connect() as connection:
        connection.execute(
            "UPDATE sync_issue_change SET work_status = 'pending' WHERE work_item_id = ?",
            (work_item_id,),
        )
    state.finish_processing_run(
        knowledge_run,
        run_status="partial",
        published_count=0,
        failed_count=0,
        superseded_count=0,
        backlog_after=0,
    )

    embedding_run = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, embedding_run)
    assert state.mark_embedding_running(work_item_id)
    _set_updated_at(state, work_item_id, "2026-09-01T08:00:00+00:00")

    result = recover_stale_inflight(
        state,
        stage="embedding",
        stale_after_seconds=300,
        now=datetime(2026, 9, 1, 8, 10, tzinfo=timezone.utc),
    )

    assert result.recovered_work_count == 1
    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "failed"
    assert work["knowledge_status"] == "completed"
    assert work["embedding_status"] == "failed"
    assert work["error_stage"] == "embedding"
