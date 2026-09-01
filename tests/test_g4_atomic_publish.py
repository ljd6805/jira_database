from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from jira_collector.embedding.contract import EmbeddingContract, embedding_id
from jira_collector.knowledge_db import connect_database, initialize_schema
from jira_collector.publishing import (
    OperationalPublishWorker,
    active_retrieval_artifact_dir,
    load_active_retrieval_searcher,
)
from jira_collector.retrieval import load_retrieval_mapping
from jira_collector.state_store import StateStore


DIMENSION = 3


def test_initial_atomic_publish_sets_one_coherent_head(tmp_path: Path) -> None:
    state, db_path, embedding_root, retrieval_root = _environment(tmp_path)
    work = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=1,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="a",
        statement="첫 번째 active knowledge",
        vector=[1.0, 0.0, 0.0],
    )
    worker = OperationalPublishWorker(
        state,
        db_path,
        embedding_root,
        retrieval_root,
    )

    result = worker.run()

    assert result.status == "completed"
    assert result.selected_count == 1
    assert result.published_count == 1
    assert result.failed_count == 0
    assert result.superseded_count == 0
    assert result.publish_result is not None
    assert result.publish_result.knowledge_generation_id == work["generation_id"]
    assert result.publish_result.vector_count == 1
    assert result.publish_result.dimension == DIMENSION
    assert result.publish_result.generation_count == 1

    state_work = state.get_work_item(work["work_item_id"])
    assert state_work["work_status"] == "published"
    assert state_work["publish_status"] == "published"
    assert state_work["knowledge_status"] == "completed"
    assert state_work["embedding_status"] == "completed"
    assert state_work["last_processing_run_id"] == result.processing_run_id

    assert _generation_state(db_path, work["generation_id"]) == "active"
    assert active_retrieval_artifact_dir(state, retrieval_root) == result.publish_result.artifact_dir
    searcher = load_active_retrieval_searcher(state, retrieval_root)
    candidates = searcher.search_vector([1.0, 0.0, 0.0], top_k=1)
    assert len(candidates) == 1
    assert candidates[0].knowledge_item_id == work["knowledge_item_id"]

    with state.connect() as connection:
        run = connection.execute(
            "SELECT * FROM processing_run WHERE processing_run_id=?",
            (result.processing_run_id,),
        ).fetchone()
    assert run is not None
    assert run["run_status"] == "completed"
    assert run["published_count"] == 1

    repeated = worker.run()
    assert repeated.selected_count == 0
    assert repeated.published_count == 0
    assert active_retrieval_artifact_dir(state, retrieval_root) == result.publish_result.artifact_dir


def test_publish_rebuilds_full_snapshot_and_replaces_only_target_issue(tmp_path: Path) -> None:
    state, db_path, embedding_root, retrieval_root = _environment(tmp_path)
    worker = OperationalPublishWorker(state, db_path, embedding_root, retrieval_root)

    issue_a_v1 = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=1,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="a",
        statement="issue A version 1",
        vector=[1.0, 0.0, 0.0],
    )
    first = worker.run()
    assert first.published_count == 1

    issue_b = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=2,
        jira_id="20001",
        issue_key="ABC-2",
        source_hash_char="b",
        statement="issue B",
        vector=[0.0, 1.0, 0.0],
    )
    second = worker.run()
    assert second.published_count == 1
    second_generations = {
        row.knowledge_generation_id
        for row in load_retrieval_mapping(active_retrieval_artifact_dir(state, retrieval_root))
    }
    assert second_generations == {
        issue_a_v1["generation_id"],
        issue_b["generation_id"],
    }
    assert _generation_state(db_path, issue_a_v1["generation_id"]) == "active"
    assert _generation_state(db_path, issue_b["generation_id"]) == "active"

    issue_a_v2 = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=3,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="c",
        statement="issue A version 2",
        vector=[0.0, 0.0, 1.0],
    )
    third = worker.run()
    assert third.published_count == 1

    third_generations = {
        row.knowledge_generation_id
        for row in load_retrieval_mapping(active_retrieval_artifact_dir(state, retrieval_root))
    }
    assert third_generations == {
        issue_a_v2["generation_id"],
        issue_b["generation_id"],
    }
    assert issue_a_v1["generation_id"] not in third_generations
    assert _generation_state(db_path, issue_a_v1["generation_id"]) == "historical"
    assert _generation_state(db_path, issue_a_v2["generation_id"]) == "active"
    assert _generation_state(db_path, issue_b["generation_id"]) == "active"


def test_wal_mode_blocks_cross_db_atomic_publish_before_active_switch(tmp_path: Path) -> None:
    state, db_path, embedding_root, retrieval_root = _environment(tmp_path)
    work = _seed_ready_work(
        state,
        db_path,
        embedding_root,
        sequence=1,
        jira_id="20000",
        issue_key="ABC-1",
        source_hash_char="a",
        statement="WAL safety gate",
        vector=[1.0, 0.0, 0.0],
    )
    with sqlite3.connect(db_path) as connection:
        mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
    if mode != "wal":
        pytest.skip("이 SQLite runtime은 WAL mode 전환을 지원하지 않습니다.")

    worker = OperationalPublishWorker(state, db_path, embedding_root, retrieval_root)
    result = worker.run()

    assert result.published_count == 0
    assert result.failed_count == 1
    assert _generation_state(db_path, work["generation_id"]) == "candidate"
    failed_work = state.get_work_item(work["work_item_id"])
    assert failed_work["work_status"] == "failed"
    assert failed_work["publish_status"] == "failed"
    with pytest.raises(Exception, match="Published Retrieval head"):
        active_retrieval_artifact_dir(state, retrieval_root)


def _environment(tmp_path: Path) -> tuple[StateStore, Path, Path, Path]:
    state = StateStore(tmp_path / "state" / "collector.db")
    db_path = tmp_path / "knowledge" / "knowledge.sqlite3"
    connection = connect_database(db_path)
    try:
        initialize_schema(connection)
        connection.commit()
    finally:
        connection.close()
    return (
        state,
        db_path,
        tmp_path / "embedding" / "operational",
        tmp_path / "retrieval" / "operational",
    )


def _seed_ready_work(
    state: StateStore,
    db_path: Path,
    embedding_root: Path,
    *,
    sequence: int,
    jira_id: str,
    issue_key: str,
    source_hash_char: str,
    statement: str,
    vector: list[float],
) -> dict[str, str]:
    source_hash = "sha256:" + source_hash_char * 64
    upper_bound = f"2026-09-01T10:{sequence:02d}:00+00:00"
    source_run_id = state.create_source_sync_run(upper_bound)
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
        upper_bound=upper_bound,
    )
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id=jira_id,
        observed_issue_key=issue_key,
        jira_updated_at=upper_bound,
        cursor_updated_at=upper_bound,
        cursor_jira_id=jira_id,
        change_kind="new" if sequence <= 2 else "changed",
        source_hash=source_hash,
    )
    assert work_item_id is not None
    state.commit_source_project(source_run_id, "10000")

    issue_version_id = f"iv_test_{jira_id}_{sequence}"
    generation_id = f"kg_test_{jira_id}_{sequence}"
    attempt_id = f"ka_test_{jira_id}_{sequence}"
    knowledge_item_id = f"ki_test_{jira_id}_{sequence}"
    _seed_knowledge_db(
        db_path,
        source_run_id=source_run_id,
        jira_id=jira_id,
        issue_key=issue_key,
        source_hash=source_hash,
        issue_version_id=issue_version_id,
        generation_id=generation_id,
        attempt_id=attempt_id,
        knowledge_item_id=knowledge_item_id,
        statement=statement,
    )

    processing_run_id = state.create_processing_run(selected_count=1, backlog_before=1)
    assert state.claim_work_item(work_item_id, processing_run_id)
    assert state.mark_knowledge_running(work_item_id)
    assert state.mark_knowledge_completed(
        work_item_id,
        issue_version_id=issue_version_id,
        knowledge_generation_id=generation_id,
    )
    assert state.mark_embedding_running(work_item_id)
    assert state.mark_embedding_completed(work_item_id)
    with state.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE sync_issue_change
            SET work_status='pending'
            WHERE work_item_id=?
              AND last_processing_run_id=?
              AND work_status='running'
              AND knowledge_status='completed'
              AND embedding_status='completed'
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
        backlog_after=1,
    )
    _write_embedding_artifact(
        embedding_root,
        work_item_id=work_item_id,
        jira_id=jira_id,
        issue_version_id=issue_version_id,
        generation_id=generation_id,
        attempt_id=attempt_id,
        knowledge_item_id=knowledge_item_id,
        statement=statement,
        vector=vector,
    )
    return {
        "work_item_id": work_item_id,
        "generation_id": generation_id,
        "knowledge_item_id": knowledge_item_id,
    }


def _seed_knowledge_db(
    db_path: Path,
    *,
    source_run_id: str,
    jira_id: str,
    issue_key: str,
    source_hash: str,
    issue_version_id: str,
    generation_id: str,
    attempt_id: str,
    knowledge_item_id: str,
    statement: str,
) -> None:
    connection = connect_database(db_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO pipeline_run(
                    run_id, status, generated_at,
                    analysis_schema_version, knowledge_input_schema_version
                ) VALUES (?, 'completed', NULL, 'test', 'test')
                """,
                (source_run_id,),
            )
            connection.execute(
                """
                INSERT INTO issue(jira_id, issue_key, project_key)
                VALUES (?, ?, 'ABC')
                ON CONFLICT(jira_id) DO UPDATE SET issue_key=excluded.issue_key
                """,
                (jira_id, issue_key),
            )
            connection.execute(
                """
                INSERT INTO issue_version(
                    issue_version_id, jira_id, source_hash, source_run_id,
                    source_issue_key, summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (issue_version_id, jira_id, source_hash, source_run_id, issue_key, statement),
            )
            connection.execute(
                """
                INSERT INTO knowledge_generation(
                    knowledge_generation_id, issue_version_id, jira_id,
                    source_run_id, source_issue_key, source_hash,
                    knowledge_contract_hash, knowledge_schema_version,
                    skill_version, runtime_version, model_profile,
                    accepted_attempt_id, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '0.1', 'test', 'test', 'test', NULL, 'candidate')
                """,
                (
                    generation_id,
                    issue_version_id,
                    jira_id,
                    source_run_id,
                    issue_key,
                    source_hash,
                    f"contract-{generation_id}",
                ),
            )
            connection.execute(
                """
                INSERT INTO knowledge_attempt(
                    knowledge_attempt_id, knowledge_generation_id, attempt_no,
                    knowledge_content_hash, content_available, validator_status
                ) VALUES (?, ?, 1, ?, 1, 'PASS')
                """,
                (attempt_id, generation_id, f"content-{generation_id}"),
            )
            connection.execute(
                """
                INSERT INTO knowledge_item(
                    knowledge_item_id, knowledge_attempt_id, category, ordinal, statement
                ) VALUES (?, ?, 'key_findings', 0, ?)
                """,
                (knowledge_item_id, attempt_id, statement),
            )
            connection.execute(
                """
                UPDATE knowledge_generation
                SET accepted_attempt_id=?
                WHERE knowledge_generation_id=?
                """,
                (attempt_id, generation_id),
            )
    finally:
        connection.close()


def _write_embedding_artifact(
    embedding_root: Path,
    *,
    work_item_id: str,
    jira_id: str,
    issue_version_id: str,
    generation_id: str,
    attempt_id: str,
    knowledge_item_id: str,
    statement: str,
    vector: list[float],
) -> None:
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model="BAAI/bge-m3",
        embedding_model_profile="test-profile",
        embedding_dimension=DIMENSION,
    )
    contract_hash = contract.logical_hash()
    text_hash = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    corpus = {
        "corpus_schema_version": "0.1",
        "text_profile": "statement_v1",
        "knowledge_item_id": knowledge_item_id,
        "knowledge_attempt_id": attempt_id,
        "knowledge_generation_id": generation_id,
        "issue_version_id": issue_version_id,
        "jira_id": jira_id,
        "category": "key_findings",
        "ordinal": 0,
        "embedding_text": statement,
        "embedding_text_hash": text_hash,
    }
    embedding = {
        "embedding_schema_version": "0.1",
        "embedding_contract_version": "0.1",
        "embedding_contract_hash": contract_hash,
        "embedding_id": embedding_id(knowledge_item_id, text_hash, contract_hash),
        "knowledge_item_id": knowledge_item_id,
        "knowledge_attempt_id": attempt_id,
        "knowledge_generation_id": generation_id,
        "issue_version_id": issue_version_id,
        "jira_id": jira_id,
        "category": "key_findings",
        "ordinal": 0,
        "text_profile": "statement_v1",
        "embedding_text_hash": text_hash,
        "embedding_model": "BAAI/bge-m3",
        "embedding_model_profile": "test-profile",
        "embedding_dimension": DIMENSION,
        "vector": vector,
    }
    work_root = embedding_root / "work" / work_item_id
    work_root.mkdir(parents=True, exist_ok=True)
    _write_jsonl(work_root / "corpus.jsonl", [corpus])
    _write_jsonl(work_root / "embeddings.jsonl", [embedding])


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _generation_state(db_path: Path, generation_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT state FROM knowledge_generation WHERE knowledge_generation_id=?",
            (generation_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])
