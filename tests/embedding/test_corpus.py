from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jira_collector.embedding import (
    TEXT_PROFILE_STATEMENT_V1,
    export_embedding_corpus,
    load_active_embedding_corpus,
)
from jira_collector.knowledge_db import connect_database, initialize_schema


def test_active_accepted_corpus_filters_and_orders_items(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    _seed_database(database)

    rows = load_active_embedding_corpus(database)

    assert len(rows) == 3
    assert [row.category for row in rows] == [
        "issue_summary",
        "key_findings",
        "outcomes",
    ]
    assert [row.ordinal for row in rows] == [0, 0, 0]
    assert {row.jira_id for row in rows} == {"10001"}
    assert all(row.text_profile == TEXT_PROFILE_STATEMENT_V1 for row in rows)


def test_statement_profile_strips_and_hashes_deterministically(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    output_a = tmp_path / "a.jsonl"
    output_b = tmp_path / "b.jsonl"
    _seed_database(database)

    first = export_embedding_corpus(database, output_a)
    second = export_embedding_corpus(database, output_b)

    assert first == second
    assert output_a.read_bytes() == output_b.read_bytes()
    assert first[0].embedding_text == "Issue 요약"
    assert first[0].embedding_text_hash == hashlib.sha256(
        "Issue 요약".encode("utf-8")
    ).hexdigest()

    documents = [
        json.loads(line)
        for line in output_a.read_text(encoding="utf-8").splitlines()
    ]
    assert len(documents) == 3
    assert documents[0]["corpus_schema_version"] == "0.1"
    assert documents[0]["knowledge_item_id"] == "ki_summary"


def test_unknown_text_profile_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.sqlite3"
    _seed_database(database)

    with pytest.raises(ValueError, match="text profile"):
        load_active_embedding_corpus(database, text_profile="unknown_v1")


def _seed_database(database: Path) -> None:
    connection = connect_database(database)
    try:
        initialize_schema(connection)
        connection.execute(
            "INSERT INTO pipeline_run(run_id, status) VALUES ('run1', 'completed')"
        )
        _seed_lineage(
            connection,
            jira_id="10001",
            issue_key="ABC-1",
            generation_id="kg_active",
            attempt_id="ka_active",
            state="active",
            content_available=1,
            items=(
                ("ki_finding", "key_findings", 0, "  핵심 발견  "),
                ("ki_outcome", "outcomes", 0, "최종 결과"),
                ("ki_summary", "issue_summary", 0, "  Issue 요약  "),
            ),
            accept=True,
        )
        _seed_lineage(
            connection,
            jira_id="10002",
            issue_key="ABC-2",
            generation_id="kg_historical",
            attempt_id="ka_historical",
            state="historical",
            content_available=1,
            items=(("ki_old", "issue_summary", 0, "과거 지식"),),
            accept=True,
        )
        _seed_lineage(
            connection,
            jira_id="10003",
            issue_key="ABC-3",
            generation_id="kg_candidate",
            attempt_id="ka_candidate",
            state="candidate",
            content_available=1,
            items=(("ki_candidate", "issue_summary", 0, "후보 지식"),),
            accept=False,
        )
        _seed_lineage(
            connection,
            jira_id="10004",
            issue_key="ABC-4",
            generation_id="kg_empty",
            attempt_id="ka_empty",
            state="active",
            content_available=0,
            items=(("ki_empty", "issue_summary", 0, "내용 없음 상태"),),
            accept=True,
        )
        connection.commit()
    finally:
        connection.close()


def _seed_lineage(
    connection,
    *,
    jira_id: str,
    issue_key: str,
    generation_id: str,
    attempt_id: str,
    state: str,
    content_available: int,
    items: tuple[tuple[str, str, int, str], ...],
    accept: bool,
) -> None:
    version_id = f"iv_{jira_id}"
    connection.execute(
        "INSERT INTO issue(jira_id, issue_key) VALUES (?, ?)",
        (jira_id, issue_key),
    )
    connection.execute(
        """
        INSERT INTO issue_version(
            issue_version_id, jira_id, source_hash, source_run_id, source_issue_key
        ) VALUES (?, ?, ?, 'run1', ?)
        """,
        (version_id, jira_id, f"hash-{jira_id}", issue_key),
    )
    connection.execute(
        """
        INSERT INTO knowledge_generation(
            knowledge_generation_id, issue_version_id, jira_id, source_run_id,
            source_issue_key, source_hash, knowledge_contract_hash,
            knowledge_schema_version, skill_version, runtime_version, model_profile, state
        ) VALUES (?, ?, ?, 'run1', ?, ?, ?, '0.1', '0.9', '0.9', 'test', ?)
        """,
        (
            generation_id,
            version_id,
            jira_id,
            issue_key,
            f"hash-{jira_id}",
            f"kc-{jira_id}",
            state,
        ),
    )
    connection.execute(
        """
        INSERT INTO knowledge_attempt(
            knowledge_attempt_id, knowledge_generation_id, attempt_no, content_available
        ) VALUES (?, ?, 1, ?)
        """,
        (attempt_id, generation_id, content_available),
    )
    for item_id, category, ordinal, statement in items:
        connection.execute(
            """
            INSERT INTO knowledge_item(
                knowledge_item_id, knowledge_attempt_id, category, ordinal, statement
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (item_id, attempt_id, category, ordinal, statement),
        )
    if accept:
        connection.execute(
            "UPDATE knowledge_generation SET accepted_attempt_id=? WHERE knowledge_generation_id=?",
            (attempt_id, generation_id),
        )
