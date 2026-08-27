from __future__ import annotations

import json
import sqlite3

import pytest

from jira_collector.evidence import (
    CandidateEvidenceBuilder,
    EvidenceResolutionError,
    EvidenceResolver,
    NoUsableEvidenceError,
    StaleKnowledgeError,
)
from jira_collector.knowledge_db import initialize_schema
from jira_collector.retrieval import RetrievalCandidate


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)
    _seed_core(connection)
    _seed_sources(connection)
    _seed_evidence(connection)
    connection.commit()
    return connection


def _seed_core(connection: sqlite3.Connection) -> None:
    connection.execute("INSERT INTO pipeline_run(run_id, status) VALUES('run1', 'completed')")
    connection.execute("INSERT INTO issue(jira_id, issue_key, project_key) VALUES('10001', 'ABC-1', 'ABC')")
    connection.execute(
        """
        INSERT INTO issue_version(
            issue_version_id, jira_id, source_hash, source_run_id, source_issue_key,
            summary, description, description_format, issue_type, status
        ) VALUES('iv_1', '10001', 'hash1', 'run1', 'ABC-1',
                 '테스트 이슈', '설명 원문', 'text', 'Bug', 'Closed')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_generation(
            knowledge_generation_id, issue_version_id, jira_id, source_run_id,
            source_issue_key, source_hash, knowledge_contract_hash,
            knowledge_schema_version, skill_version, runtime_version,
            model_profile, accepted_attempt_id, state
        ) VALUES('kg_1', 'iv_1', '10001', 'run1', 'ABC-1', 'hash1', 'kc_1',
                 '0.1', '0.9', '0.9', 'test-profile', NULL, 'active')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_attempt(
            knowledge_attempt_id, knowledge_generation_id, attempt_no,
            content_available, validator_status
        ) VALUES('ka_1', 'kg_1', 1, 1, 'PASS')
        """
    )
    connection.execute(
        "UPDATE knowledge_generation SET accepted_attempt_id='ka_1' WHERE knowledge_generation_id='kg_1'"
    )
    connection.execute(
        """
        INSERT INTO knowledge_item(
            knowledge_item_id, knowledge_attempt_id, category, ordinal, statement
        ) VALUES('ki_1', 'ka_1', 'key_findings', 0, 'retry 적용 후 문제가 재현되지 않았다.')
        """
    )


def _seed_sources(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO comment(
            run_id, issue_key, comment_id, sequence, author_name,
            created_at, updated_at, body, body_format
        ) VALUES('run1', 'ABC-1', '10', 1, 'Tester',
                 '2026-08-01T01:00:00Z', '2026-08-01T01:10:00Z', '댓글 근거', 'text')
        """
    )
    connection.execute(
        """
        INSERT INTO attachment(
            run_id, issue_key, attachment_id, filename, size_bytes,
            mime_type, content_available
        ) VALUES('run1', 'ABC-1', '20', 'trace.txt', 123, 'text/plain', 0)
        """
    )
    connection.execute(
        """
        INSERT INTO relationship(
            run_id, relationship_id, relationship_category, relationship_type,
            relationship_text, source_issue_key, target_issue_key, derived
        ) VALUES('run1', '30', 'issue_link', 'Blocks', 'blocks', 'ABC-1', 'ABC-9', 0)
        """
    )
    connection.execute(
        """
        INSERT INTO custom_field_catalog(run_id, field_id, field_name, schema_type)
        VALUES('run1', 'customfield_1', 'Revision', 'option')
        """
    )
    connection.execute(
        """
        INSERT INTO custom_field_value(
            run_id, issue_key, field_id, actual_type, value_kind,
            display_value, display_values_json, value_id, value_ids_json,
            user_keys_json, value_shape_json
        ) VALUES('run1', 'ABC-1', 'customfield_1', 'object', 'option',
                 'EVT', '[]', '1', '[]', '[]', '["id", "value"]')
        """
    )


def _seed_evidence(connection: sqlite3.Connection) -> None:
    rows = (
        ("ke_1", 0, "summary", "summary", None),
        ("ke_2", 1, "description", "description", None),
        ("ke_3", 2, "comment:10", "comment", "10"),
        ("ke_4", 3, "attachment:20", "attachment", "20"),
        ("ke_5", 4, "relationship:30", "relationship", "30"),
        ("ke_6", 5, "custom_field:customfield_1", "custom_field", "customfield_1"),
    )
    connection.executemany(
        """
        INSERT INTO knowledge_evidence(
            knowledge_evidence_id, knowledge_item_id, ordinal, evidence_ref,
            evidence_type, source_run_id, source_issue_key, source_entity_key
        ) VALUES(?, 'ki_1', ?, ?, ?, 'run1', 'ABC-1', ?)
        """,
        rows,
    )


def _candidate(item_id: str = "ki_1", *, rank: int = 1) -> RetrievalCandidate:
    return RetrievalCandidate(
        rank=rank,
        score=0.84,
        faiss_position=rank - 1,
        embedding_id=f"emb_{item_id}",
        knowledge_item_id=item_id,
        category="key_findings",
    )


def test_resolves_active_candidate_and_all_six_evidence_types() -> None:
    connection = _database()
    package = EvidenceResolver(connection).resolve_candidate(_candidate())

    assert package.knowledge_item_id == "ki_1"
    assert package.statement == "retry 적용 후 문제가 재현되지 않았다."
    assert package.issue.issue_key == "ABC-1"
    assert [evidence.evidence_type for evidence in package.evidence] == [
        "summary",
        "description",
        "comment",
        "attachment",
        "relationship",
        "custom_field",
    ]
    assert package.evidence[2].text == "댓글 근거"
    assert package.evidence[3].metadata["filename"] == "trace.txt"
    assert package.evidence[5].metadata["display_values"] == []
    assert all("source_path" not in evidence.metadata for evidence in package.evidence)


def test_rejects_stale_candidate() -> None:
    connection = _database()
    connection.execute("UPDATE knowledge_generation SET state='historical' WHERE knowledge_generation_id='kg_1'")

    with pytest.raises(StaleKnowledgeError) as caught:
        EvidenceResolver(connection).resolve_candidate(_candidate())

    assert caught.value.code == "STALE_RETRIEVAL_INDEX"


def test_missing_source_is_resolution_failure() -> None:
    connection = _database()
    connection.execute("DELETE FROM comment WHERE run_id='run1' AND issue_key='ABC-1' AND comment_id='10'")

    with pytest.raises(EvidenceResolutionError) as caught:
        EvidenceResolver(connection).resolve_candidate(_candidate())

    assert caught.value.code == "EVIDENCE_SOURCE_MISSING"


def test_invalid_evidence_ref_is_typed_resolution_failure() -> None:
    connection = _database()
    connection.execute(
        "UPDATE knowledge_evidence SET evidence_ref='comment:10:bad' WHERE knowledge_evidence_id='ke_3'"
    )

    with pytest.raises(EvidenceResolutionError) as caught:
        EvidenceResolver(connection).resolve_candidate(_candidate())

    assert caught.value.code == "EVIDENCE_REF_INVALID"


def test_builder_keeps_valid_candidate_and_warns_for_broken_candidate() -> None:
    connection = _database()
    builder = CandidateEvidenceBuilder(EvidenceResolver(connection))

    result = builder.build((_candidate("ki_missing", rank=1), _candidate(rank=2)))

    assert len(result.results) == 1
    assert result.results[0].knowledge_item_id == "ki_1"
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "KNOWLEDGE_NOT_FOUND"


def test_builder_raises_when_all_candidates_are_broken() -> None:
    connection = _database()
    builder = CandidateEvidenceBuilder(EvidenceResolver(connection))

    with pytest.raises(NoUsableEvidenceError):
        builder.build((_candidate("ki_missing"),))


def test_custom_field_json_is_structured_not_raw_string() -> None:
    connection = _database()
    package = EvidenceResolver(connection).resolve_candidate(_candidate())
    custom_field = package.evidence[-1]

    assert custom_field.metadata["value_shape"] == ["id", "value"]
    json.dumps(custom_field.metadata, ensure_ascii=False)
