from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jira_collector.knowledge_db import connect_database, initialize_schema


def _seed_issue(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO pipeline_run(run_id, status) VALUES ('run1', 'completed')"
    )
    connection.execute(
        "INSERT INTO issue(jira_id, issue_key, project_key) VALUES ('10001', 'ABC-1', 'ABC')"
    )
    for suffix in ("a", "b"):
        connection.execute(
            """
            INSERT INTO issue_version(
                issue_version_id, jira_id, source_hash, source_run_id, source_issue_key
            ) VALUES (?, '10001', ?, 'run1', 'ABC-1')
            """,
            (f"iv_{suffix}", f"sha256:{suffix}"),
        )


def _insert_generation(
    connection: sqlite3.Connection,
    generation_id: str,
    version_id: str,
    state: str,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_generation(
            knowledge_generation_id, issue_version_id, jira_id,
            source_run_id, source_issue_key, source_hash,
            knowledge_contract_hash, knowledge_schema_version,
            skill_version, runtime_version, model_profile, state
        ) VALUES (?, ?, '10001', 'run1', 'ABC-1', ?, 'kc_test', '0.1', '0.9', '0.9', 'test', ?)
        """,
        (generation_id, version_id, f"sha256:{version_id[-1]}", state),
    )


def test_database_rejects_two_active_generations_for_same_issue(tmp_path: Path) -> None:
    """Application bug가 있어도 partial UNIQUE index가 active 중복을 막아야 합니다."""

    connection = connect_database(tmp_path / "knowledge.sqlite3")
    try:
        initialize_schema(connection)
        _seed_issue(connection)
        _insert_generation(connection, "kg_a", "iv_a", "active")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_generation(connection, "kg_b", "iv_b", "active")
    finally:
        connection.close()


def test_database_allows_historical_plus_active_for_same_issue(tmp_path: Path) -> None:
    """History 보존은 허용하되 active만 하나여야 합니다."""

    connection = connect_database(tmp_path / "knowledge.sqlite3")
    try:
        initialize_schema(connection)
        _seed_issue(connection)
        _insert_generation(connection, "kg_a", "iv_a", "historical")
        _insert_generation(connection, "kg_b", "iv_b", "active")
        connection.commit()

        states = connection.execute(
            "SELECT state FROM knowledge_generation ORDER BY knowledge_generation_id"
        ).fetchall()
        assert [row["state"] for row in states] == ["historical", "active"]
    finally:
        connection.close()
