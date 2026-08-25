from __future__ import annotations

import json
from pathlib import Path

from jira_collector.knowledge_db import connect_database, initialize_schema
from jira_collector.knowledge_db.validation import (
    ExpectedCounts,
    expected_counts_from_profile,
    snapshot_database,
    validate_snapshot,
)


def test_expected_counts_are_derived_from_m5_profile(tmp_path: Path) -> None:
    """M7 Gate가 하드코딩 대신 M5 profile metric contract를 재사용하는지 확인합니다."""

    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "integrity": {"ok": True},
                "knowledge": {
                    "issue_count": 30,
                    "total_statement_item_count": 285,
                    "evidence": {"total_evidence_ref_count": 503},
                },
                "review": {"review_file_count": 37},
            }
        ),
        encoding="utf-8",
    )

    assert expected_counts_from_profile(profile) == ExpectedCounts(
        issue_count=30,
        generation_count=30,
        attempt_count=37,
        knowledge_item_count=285,
        evidence_count=503,
        review_count=37,
    )


def test_snapshot_passes_for_one_complete_active_lineage(tmp_path: Path) -> None:
    """SQLite/Evidence/active 상태가 모두 정상인 최소 lineage가 Gate를 통과하는지 확인합니다."""

    database = tmp_path / "knowledge.sqlite3"
    connection = connect_database(database)
    try:
        initialize_schema(connection)
        _seed_one_lineage(connection)
        connection.commit()
    finally:
        connection.close()

    snapshot = snapshot_database(database)
    expected = ExpectedCounts(1, 1, 1, 1, 1, 1)

    assert validate_snapshot(snapshot, expected) == []
    assert snapshot.active_generation_count == 1
    assert snapshot.accepted_evidence_failure_count == 0
    assert snapshot.foreign_key_failure_count == 0
    assert snapshot.integrity_ok is True


def test_snapshot_reports_count_and_state_mismatch(tmp_path: Path) -> None:
    """M5 count 또는 active state가 달라지면 사람이 읽을 수 있는 failure를 반환합니다."""

    database = tmp_path / "knowledge.sqlite3"
    connection = connect_database(database)
    try:
        initialize_schema(connection)
        connection.execute("INSERT INTO pipeline_run(run_id, status) VALUES ('run1', 'completed')")
        connection.commit()
    finally:
        connection.close()

    failures = validate_snapshot(
        snapshot_database(database),
        ExpectedCounts(1, 1, 1, 1, 1, 1),
    )

    assert any("issue_count" in failure for failure in failures)
    assert any("active_generation_count" in failure for failure in failures)


def _seed_one_lineage(connection) -> None:
    connection.execute("INSERT INTO pipeline_run(run_id, status) VALUES ('run1', 'completed')")
    connection.execute(
        "INSERT INTO issue(jira_id, issue_key, project_key) VALUES ('10001', 'ABC-1', 'ABC')"
    )
    connection.execute(
        """
        INSERT INTO issue_version(
            issue_version_id, jira_id, source_hash, source_run_id, source_issue_key, summary
        ) VALUES ('iv_a', '10001', 'sha256:a', 'run1', 'ABC-1', 'summary')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_generation(
            knowledge_generation_id, issue_version_id, jira_id, source_run_id,
            source_issue_key, source_hash, knowledge_contract_hash,
            knowledge_schema_version, skill_version, runtime_version, model_profile, state
        ) VALUES (
            'kg_a', 'iv_a', '10001', 'run1', 'ABC-1', 'sha256:a', 'kc_a',
            '0.1', '0.9', '0.9', 'test', 'candidate'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_attempt(
            knowledge_attempt_id, knowledge_generation_id, attempt_no, content_available
        ) VALUES ('ka_a', 'kg_a', 1, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_item(
            knowledge_item_id, knowledge_attempt_id, category, ordinal, statement
        ) VALUES ('ki_a', 'ka_a', 'issue_summary', 0, 'summary knowledge')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_evidence(
            knowledge_evidence_id, knowledge_item_id, ordinal, evidence_ref,
            evidence_type, source_run_id, source_issue_key, source_entity_key
        ) VALUES ('ke_a', 'ki_a', 0, 'summary', 'summary', 'run1', 'ABC-1', NULL)
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_review(
            knowledge_attempt_id, review_schema_version, review_content_hash,
            score, verdict, critical_error, major_issue_count,
            factual_fidelity_score, evidence_coverage_score,
            certainty_preservation_score, classification_score,
            retrieval_value_score, language_quality_score
        ) VALUES (
            'ka_a', '0.3', 'sha256:r', 9.0, 'PASS', 0, 0,
            2.8, 1.8, 1.3, 1.3, 0.9, 0.9
        )
        """
    )
    connection.execute(
        """
        UPDATE knowledge_generation
        SET accepted_attempt_id='ka_a', state='active'
        WHERE knowledge_generation_id='kg_a'
        """
    )
