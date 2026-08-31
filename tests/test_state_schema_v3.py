from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jira_collector.state_schema import (
    LEGACY_SCHEMA_STATEMENTS,
    OPERATIONAL_TABLES,
    STATE_SCHEMA_VERSION,
    StateMigrationRequiredError,
    UnknownStateSchemaError,
    migrate_legacy_state_database,
    verify_state_schema_v3,
)
from jira_collector.state_store import StateStore, make_work_item_id


def _create_known_legacy_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in LEGACY_SCHEMA_STATEMENTS:
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO collection_runs(
                run_id, started_at, status, issues_per_project,
                project_count, success_count, failure_count
            ) VALUES ('legacy-run', '2026-08-01T00:00:00+00:00', 'partial', 30, 1, 0, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO project_runs(
                run_id, project_key, project_name, status,
                requested_count, collected_count, error_message
            ) VALUES ('legacy-run', 'ABC', 'Alpha', 'partial', 30, 7, 'legacy failure')
            """
        )
        connection.execute(
            """
            INSERT INTO issue_checkpoints(
                run_id, project_key, issue_key, status, updated_at, error_message
            ) VALUES (
                'legacy-run', 'ABC', 'ABC-1', 'completed',
                '2026-08-01T00:01:00+00:00', NULL
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def _begin_project(
    state: StateStore,
    *,
    source_run_id: str,
    project_id: str = "10000",
    upper_bound: str,
    lower_bound: str | None,
    operation_kind: str,
) -> None:
    state.upsert_visible_project(
        source_run_id=source_run_id,
        project_id=project_id,
        project_key="ABC",
        project_name="Alpha",
    )
    state.start_source_project_run(
        source_run_id=source_run_id,
        project_id=project_id,
        operation_kind=operation_kind,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


def _record_changed(
    state: StateStore,
    *,
    source_run_id: str,
    source_hash: str,
    updated_at: str,
    jira_id: str = "20000",
) -> str:
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id=jira_id,
        observed_issue_key="ABC-1",
        jira_updated_at=updated_at,
        cursor_updated_at=updated_at,
        cursor_jira_id=jira_id,
        change_kind="changed",
        source_hash=source_hash,
    )
    assert work_item_id is not None
    return work_item_id


def test_new_database_starts_at_v3_and_legacy_collector_api_still_works(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"

    state = StateStore(database)

    assert state.schema_version == STATE_SCHEMA_VERSION
    inspection = verify_state_schema_v3(database)
    assert inspection.is_current
    assert set(OPERATIONAL_TABLES).issubset(set(inspection.user_tables))

    state.create_run("run1", 30)
    state.add_projects("run1", [("ABC", "Alpha")], 30)
    state.start_project("run1", "ABC")
    state.complete_project("run1", "ABC", 1)
    assert state.finish_run("run1") == "completed"
    assert state.get_run_summary("run1")["status"] == "completed"


def test_known_legacy_requires_explicit_migration_and_preserves_rows(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"
    backup = tmp_path / "collector.pre-v3.bak"
    _create_known_legacy_database(database)

    with pytest.raises(StateMigrationRequiredError):
        StateStore(database)

    result = migrate_legacy_state_database(database, backup_path=backup)

    assert result.migrated is True
    assert result.from_version == 0
    assert result.to_version == 3
    assert result.backup_path == backup
    assert backup.is_file()
    assert verify_state_schema_v3(database).is_current

    state = StateStore(database)
    summary = state.get_run_summary("legacy-run")
    assert summary["status"] == "partial"
    projects = state.list_all_projects("legacy-run")
    assert len(projects) == 1
    assert projects[0].collected_count == 7
    assert state.issue_is_complete("legacy-run", "ABC", "ABC-1")


def test_migration_is_idempotent_after_v3(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"
    _create_known_legacy_database(database)
    first = migrate_legacy_state_database(database)
    assert first.migrated is True
    assert first.backup_path is not None

    second = migrate_legacy_state_database(database)

    assert second.migrated is False
    assert second.from_version == 3
    assert second.to_version == 3
    assert second.backup_path is None


def test_unknown_version_zero_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE mystery(id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(UnknownStateSchemaError):
        StateStore(database)
    with pytest.raises(UnknownStateSchemaError):
        migrate_legacy_state_database(database)


def test_work_item_id_is_deterministic_and_profile_sensitive() -> None:
    left = make_work_item_id("20000", "a" * 64, "semantic_v2")
    right = make_work_item_id("20000", "a" * 64, "semantic_v2")
    other = make_work_item_id("20000", "a" * 64, "semantic_v3")

    assert left == right
    assert left.startswith("sw_")
    assert len(left) == 67
    assert left != other


def test_source_commit_opens_ready_gate_and_supersedes_only_older_unpublished_work(
    tmp_path: Path,
) -> None:
    state = StateStore(tmp_path / "collector.db")

    run1 = state.create_source_sync_run("2026-08-31T01:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run1,
        upper_bound="2026-08-31T01:00:00+00:00",
        lower_bound=None,
        operation_kind="initial_ingest",
    )
    work_v1 = _record_changed(
        state,
        source_run_id=run1,
        source_hash="1" * 64,
        updated_at="2026-08-31T00:10:00+00:00",
    )
    assert state.count_latest_ready_work_items() == 0
    state.commit_source_project(run1, "10000")
    assert [item.work_item_id for item in state.list_latest_ready_work_items()] == [work_v1]

    processing = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_v1, processing)

    run2 = state.create_source_sync_run("2026-08-31T02:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run2,
        upper_bound="2026-08-31T02:00:00+00:00",
        lower_bound="2026-08-31T00:55:00+00:00",
        operation_kind="delta",
    )
    work_v2 = _record_changed(
        state,
        source_run_id=run2,
        source_hash="2" * 64,
        updated_at="2026-08-31T01:10:00+00:00",
    )
    state.commit_source_project(run2, "10000")

    assert state.get_work_item(work_v1)["work_status"] == "superseded"
    assert state.get_work_item(work_v1)["superseded_by_work_item_id"] == work_v2
    assert state.work_item_is_latest(work_v1) is False
    assert state.mark_knowledge_completed(
        work_v1,
        issue_version_id="iv_old",
        knowledge_generation_id="kg_old",
    ) is False
    assert [item.work_item_id for item in state.list_latest_ready_work_items()] == [work_v2]


def test_source_commit_watermark_and_ready_gate_rollback_together(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "collector.db")
    run_id = state.create_source_sync_run("2026-08-31T01:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run_id,
        upper_bound="2026-08-31T01:00:00+00:00",
        lower_bound=None,
        operation_kind="initial_ingest",
    )
    work_item = _record_changed(
        state,
        source_run_id=run_id,
        source_hash="a" * 64,
        updated_at="2026-08-31T00:10:00+00:00",
    )

    # Source Commit CHECK를 고의로 실패시켜 같은 transaction의 Watermark/Gate도 rollback되는지 확인합니다.
    with state.connect() as connection:
        connection.execute(
            """
            UPDATE source_project_run
            SET candidate_count = candidate_count + 1
            WHERE source_run_id = ? AND project_id = '10000'
            """,
            (run_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        state.commit_source_project(run_id, "10000")

    project = state.get_project_state("10000")
    work = state.get_work_item(work_item)
    assert project["committed_watermark"] is None
    assert project["last_source_success_run_id"] is None
    assert work["last_source_committed_run_id"] is None
    assert state.count_latest_ready_work_items() == 0


def test_published_semantic_state_can_be_reactivated_when_it_becomes_latest_again(
    tmp_path: Path,
) -> None:
    state = StateStore(tmp_path / "collector.db")

    run_a1 = state.create_source_sync_run("2026-08-31T01:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run_a1,
        upper_bound="2026-08-31T01:00:00+00:00",
        lower_bound=None,
        operation_kind="initial_ingest",
    )
    work_a = _record_changed(
        state,
        source_run_id=run_a1,
        source_hash="a" * 64,
        updated_at="2026-08-31T00:10:00+00:00",
    )
    state.commit_source_project(run_a1, "10000")

    processing = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_a, processing)
    assert state.mark_knowledge_running(work_a)
    assert state.mark_knowledge_completed(
        work_a,
        issue_version_id="iv_a",
        knowledge_generation_id="kg_a",
    )
    assert state.mark_embedding_running(work_a)
    assert state.mark_embedding_completed(work_a)
    assert state.mark_publish_running(work_a)
    assert state.mark_published(work_a)

    run_b = state.create_source_sync_run("2026-08-31T02:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run_b,
        upper_bound="2026-08-31T02:00:00+00:00",
        lower_bound="2026-08-31T00:55:00+00:00",
        operation_kind="delta",
    )
    work_b = _record_changed(
        state,
        source_run_id=run_b,
        source_hash="b" * 64,
        updated_at="2026-08-31T01:10:00+00:00",
    )
    state.commit_source_project(run_b, "10000")
    assert state.get_work_item(work_a)["work_status"] == "published"

    run_a2 = state.create_source_sync_run("2026-08-31T03:00:00+00:00")
    _begin_project(
        state,
        source_run_id=run_a2,
        upper_bound="2026-08-31T03:00:00+00:00",
        lower_bound="2026-08-31T01:55:00+00:00",
        operation_kind="delta",
    )
    replayed_a = _record_changed(
        state,
        source_run_id=run_a2,
        source_hash="a" * 64,
        updated_at="2026-08-31T02:10:00+00:00",
    )
    assert replayed_a == work_a
    state.commit_source_project(run_a2, "10000")

    current_a = state.get_work_item(work_a)
    assert current_a["work_status"] == "pending"
    assert current_a["knowledge_status"] == "completed"
    assert current_a["embedding_status"] == "completed"
    assert current_a["publish_status"] == "pending"
    assert state.get_work_item(work_b)["work_status"] == "superseded"
    assert [item.work_item_id for item in state.list_latest_ready_work_items()] == [work_a]
