from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jira_collector.embedding.client import EmbeddingBatchResult
from jira_collector.embedding.config import EmbeddingRuntimeSettings
from jira_collector.embedding.operational import (
    OperationalEmbeddingWorker,
    StaleEmbeddingWorkError,
    load_generation_embedding_corpus,
)
from jira_collector.knowledge_db import connect_database, initialize_schema
from jira_collector.state_store import StateStore


class FakeLimiter:
    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


class FakeClient:
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return EmbeddingBatchResult(
            tuple(
                tuple(float(index + 1) for _ in range(self.dimension))
                for index, _ in enumerate(texts)
            )
        )


class FailingClient(FakeClient):
    def embed(self, texts):
        self.calls.append(list(texts))
        raise RuntimeError("embedding unavailable")


class SupersedingClient(FakeClient):
    def __init__(self, state: StateStore, old_work_item_id: str) -> None:
        super().__init__()
        self.state = state
        self.old_work_item_id = old_work_item_id
        self.new_work_item_id: str | None = None

    def embed(self, texts):
        self.calls.append(list(texts))
        run_id = self.state.create_source_sync_run("2026-08-31T02:00:00+00:00")
        self.state.upsert_visible_project(
            source_run_id=run_id,
            project_id="10000",
            project_key="ABC",
            project_name="Alpha",
        )
        self.state.start_source_project_run(
            source_run_id=run_id,
            project_id="10000",
            operation_kind="delta",
            lower_bound="2026-08-31T00:55:00+00:00",
            upper_bound="2026-08-31T02:00:00+00:00",
        )
        work_id = self.state.record_source_candidate(
            source_run_id=run_id,
            project_id="10000",
            jira_id="20000",
            observed_issue_key="ABC-1",
            jira_updated_at="2026-08-31T01:10:00+00:00",
            cursor_updated_at="2026-08-31T01:10:00+00:00",
            cursor_jira_id="20000",
            change_kind="changed",
            source_hash="b" * 64,
        )
        assert work_id is not None
        self.state.commit_source_project(run_id, "10000")
        self.new_work_item_id = work_id
        return EmbeddingBatchResult(
            tuple(
                tuple(float(index + 1) for _ in range(self.dimension))
                for index, _ in enumerate(texts)
            )
        )


def _settings() -> EmbeddingRuntimeSettings:
    return EmbeddingRuntimeSettings(
        endpoint="https://embedding.example/v1/embeddings",
        api_key=None,
        custom_headers={},
        provider="openai_compatible",
        model="BAAI/bge-m3",
        model_profile="test-profile",
        text_profile="statement_v1",
        dimension=3,
        batch_size=64,
        requests_per_minute=200,
        verify_ssl=True,
        timeout_seconds=60,
        max_attempts=3,
        backoff_initial_seconds=1,
    )


def _prepare_state(tmp_path: Path) -> tuple[StateStore, str]:
    state = StateStore(tmp_path / "collector.db")
    source_run_id = state.create_source_sync_run("2026-08-31T01:00:00+00:00")
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
        upper_bound="2026-08-31T01:00:00+00:00",
    )
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id="20000",
        observed_issue_key="ABC-1",
        jira_updated_at="2026-08-31T00:10:00+00:00",
        cursor_updated_at="2026-08-31T00:10:00+00:00",
        cursor_jira_id="20000",
        change_kind="new",
        source_hash="a" * 64,
    )
    assert work_item_id is not None
    state.commit_source_project(source_run_id, "10000")
    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)
    assert state.mark_knowledge_completed(
        work_item_id,
        issue_version_id="iv_test",
        knowledge_generation_id="kg_test",
    )
    return state, work_item_id


def _prepare_knowledge_db(path: Path) -> None:
    connection = connect_database(path)
    try:
        initialize_schema(connection)
        with connection:
            connection.execute(
                """
                INSERT INTO pipeline_run(run_id, status)
                VALUES ('sr_test', 'completed')
                """
            )
            connection.execute(
                """
                INSERT INTO issue(jira_id, issue_key, project_key)
                VALUES ('20000', 'ABC-1', 'ABC')
                """
            )
            connection.execute(
                """
                INSERT INTO issue_version(
                    issue_version_id, jira_id, source_hash,
                    source_run_id, source_issue_key
                ) VALUES ('iv_test', '20000', ?, 'sr_test', 'ABC-1')
                """,
                ("a" * 64,),
            )
            connection.execute(
                """
                INSERT INTO knowledge_generation(
                    knowledge_generation_id, issue_version_id, jira_id,
                    source_run_id, source_issue_key, source_hash,
                    knowledge_contract_hash, knowledge_schema_version,
                    skill_version, runtime_version, model_profile,
                    accepted_attempt_id, state
                ) VALUES (
                    'kg_test', 'iv_test', '20000', 'sr_test', 'ABC-1', ?,
                    'contract', '0.3', 'skill', 'runtime', 'model', NULL, 'candidate'
                )
                """,
                ("a" * 64,),
            )
            connection.execute(
                """
                INSERT INTO knowledge_attempt(
                    knowledge_attempt_id, knowledge_generation_id, attempt_no,
                    knowledge_content_hash, content_available, validator_status
                ) VALUES ('ka_test', 'kg_test', 1, 'hash', 1, 'PASS')
                """
            )
            connection.executemany(
                """
                INSERT INTO knowledge_item(
                    knowledge_item_id, knowledge_attempt_id,
                    category, ordinal, statement
                ) VALUES (?, 'ka_test', ?, ?, ?)
                """,
                [
                    ("ki_1", "issue_summary", 0, "첫 번째 지식"),
                    ("ki_2", "key_findings", 0, "두 번째 지식"),
                ],
            )
            connection.execute(
                """
                UPDATE knowledge_generation
                SET accepted_attempt_id='ka_test'
                WHERE knowledge_generation_id='kg_test'
                """
            )
    finally:
        connection.close()


def test_load_generation_corpus_accepts_candidate_generation(tmp_path: Path) -> None:
    knowledge_db = tmp_path / "knowledge.sqlite3"
    _prepare_knowledge_db(knowledge_db)

    rows = load_generation_embedding_corpus(knowledge_db, "kg_test")

    assert [row.knowledge_item_id for row in rows] == ["ki_1", "ki_2"]
    assert all(row.knowledge_generation_id == "kg_test" for row in rows)
    assert all(row.issue_version_id == "iv_test" for row in rows)


def test_operational_embedding_success_marks_completed_and_writes_artifacts(
    tmp_path: Path,
) -> None:
    state, work_item_id = _prepare_state(tmp_path)
    knowledge_db = tmp_path / "knowledge.sqlite3"
    _prepare_knowledge_db(knowledge_db)
    client = FakeClient()
    limiter = FakeLimiter()
    worker = OperationalEmbeddingWorker(
        state,
        knowledge_db,
        tmp_path / "embedding",
        _settings(),
        client=client,
        rate_limiter=limiter,
    )

    result = worker.process_work(work_item_id)

    assert result.corpus_rows == 2
    assert result.embedding_rows == 2
    assert result.embedding_dimension == 3
    assert result.corpus_path.is_file()
    assert result.embedding_path.is_file()
    assert client.calls == [["첫 번째 지식", "두 번째 지식"]]
    assert limiter.wait_count == 1
    work = state.get_work_item(work_item_id)
    assert work["embedding_status"] == "completed"
    assert work["work_status"] == "running"


def test_newer_source_during_embedding_blocks_old_completion(tmp_path: Path) -> None:
    state, work_item_id = _prepare_state(tmp_path)
    knowledge_db = tmp_path / "knowledge.sqlite3"
    _prepare_knowledge_db(knowledge_db)
    client = SupersedingClient(state, work_item_id)
    worker = OperationalEmbeddingWorker(
        state,
        knowledge_db,
        tmp_path / "embedding",
        _settings(),
        client=client,
        rate_limiter=FakeLimiter(),
    )

    with pytest.raises(StaleEmbeddingWorkError):
        worker.process_work(work_item_id)

    assert client.new_work_item_id is not None
    old_work = state.get_work_item(work_item_id)
    assert old_work["work_status"] == "superseded"
    assert old_work["embedding_status"] != "completed"
    assert not (tmp_path / "embedding" / "work" / work_item_id / "embeddings.jsonl").exists()
    assert state.get_work_item(client.new_work_item_id)["work_status"] == "pending"


def test_embedding_failure_remains_retryable(tmp_path: Path) -> None:
    state, work_item_id = _prepare_state(tmp_path)
    knowledge_db = tmp_path / "knowledge.sqlite3"
    _prepare_knowledge_db(knowledge_db)
    worker = OperationalEmbeddingWorker(
        state,
        knowledge_db,
        tmp_path / "embedding",
        _settings(),
        client=FailingClient(),
        rate_limiter=FakeLimiter(),
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        worker.process_work(work_item_id)

    work = state.get_work_item(work_item_id)
    assert work["embedding_status"] == "failed"
    assert work["work_status"] == "failed"
    assert work["error_stage"] == "embedding"
