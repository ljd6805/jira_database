from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Sequence

import pytest
from mcp import Client

from jira_collector.knowledge_db import initialize_schema
from jira_collector.mcp_server import (
    JiraKnowledgeService,
    create_mcp_server,
    open_knowledge_db_readonly,
)
from jira_collector.mcp_server.service import SearchHead
from jira_collector.mcp_server.validation import validate_m10_payloads
from jira_collector.retrieval import RetrievalCandidate


class FakeSearcher:
    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int | None = None,
    ) -> tuple[RetrievalCandidate, ...]:
        assert tuple(query_vector) == (1.0, 0.0)
        assert top_k is not None and top_k >= 1
        return (
            RetrievalCandidate(
                rank=1,
                score=0.91,
                faiss_position=0,
                embedding_id="emb_1",
                knowledge_item_id="ki_1",
                category="key_findings",
            ),
        )


def _query_embedder(query: str) -> tuple[float, float]:
    assert query == "retry timeout"
    return (1.0, 0.0)


def _database(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:" if path is None else path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)
    _seed_database(connection)
    connection.commit()
    return connection


def _seed_database(connection: sqlite3.Connection) -> None:
    connection.execute("INSERT INTO pipeline_run(run_id, status) VALUES('run1', 'completed')")
    connection.execute("INSERT INTO issue(jira_id, issue_key, project_key) VALUES('10001', 'ABC-1', 'ABC')")
    connection.execute(
        """
        INSERT INTO issue_version(
            issue_version_id, jira_id, source_hash, source_run_id, source_issue_key,
            summary, description, description_format, issue_type, status, priority
        ) VALUES('iv_1', '10001', 'hash1', 'run1', 'ABC-1',
                 'Timeout issue', 'Issue description', 'text', 'Bug', 'Closed', 'High')
        """
    )
    connection.execute(
        """
        INSERT INTO knowledge_generation(
            knowledge_generation_id, issue_version_id, jira_id, source_run_id,
            source_issue_key, source_hash, knowledge_contract_hash,
            knowledge_schema_version, skill_version, runtime_version,
            model_profile, state
        ) VALUES('kg_1', 'iv_1', '10001', 'run1', 'ABC-1', 'hash1', 'kc_1',
                 '0.1', '0.9', '0.9', 'test', 'active')
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
        ) VALUES('ki_1', 'ka_1', 'key_findings', 0, 'retry 적용 후 timeout이 재현되지 않았다.')
        """
    )
    connection.execute(
        """
        INSERT INTO comment(
            run_id, issue_key, comment_id, sequence, author_name, body, body_format
        ) VALUES('run1', 'ABC-1', '10', 1, 'Tester', 'retry를 적용한 뒤 재현되지 않음', 'text')
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
        INSERT INTO knowledge_evidence(
            knowledge_evidence_id, knowledge_item_id, ordinal, evidence_ref,
            evidence_type, source_run_id, source_issue_key, source_entity_key
        ) VALUES('ke_1', 'ki_1', 0, 'comment:10', 'comment', 'run1', 'ABC-1', '10')
        """
    )


def _service() -> JiraKnowledgeService:
    return JiraKnowledgeService(_database(), FakeSearcher(), _query_embedder)


def test_service_search_builds_evidence_package() -> None:
    result = _service().search_jira_knowledge(" retry timeout ", top_k=3)

    assert result["query"] == "retry timeout"
    assert result["warnings"] == []
    package = result["results"][0]
    assert package["knowledge_item_id"] == "ki_1"
    assert package["statement"] == "retry 적용 후 timeout이 재현되지 않았다."
    assert package["evidence"][0]["text"] == "retry를 적용한 뒤 재현되지 않음"


def test_request_read_snapshot_survives_concurrent_head_switch(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    creator = _database(db_path)
    assert str(creator.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
    creator.close()

    reader = open_knowledge_db_readonly(db_path)
    writer = sqlite3.connect(db_path)
    switched = False

    def provider(connection: sqlite3.Connection) -> SearchHead:
        nonlocal switched
        row = connection.execute(
            "SELECT state FROM knowledge_generation WHERE knowledge_generation_id='kg_1'"
        ).fetchone()
        assert row is not None and row[0] == "active"
        writer.execute(
            "UPDATE knowledge_generation SET state='historical' WHERE knowledge_generation_id='kg_1'"
        )
        writer.commit()
        switched = True
        return SearchHead(FakeSearcher(), _query_embedder)

    service = JiraKnowledgeService(reader, search_head_provider=provider)
    try:
        result = service.search_jira_knowledge("retry timeout")
    finally:
        reader.close()
        writer.close()

    assert switched is True
    assert result["warnings"] == []
    assert result["results"][0]["knowledge_item_id"] == "ki_1"
    with sqlite3.connect(db_path) as verification:
        state = verification.execute(
            "SELECT state FROM knowledge_generation WHERE knowledge_generation_id='kg_1'"
        ).fetchone()
    assert state is not None and state[0] == "historical"


def test_service_get_issue_returns_safe_current_snapshot() -> None:
    result = _service().get_jira_issue("ABC-1")

    assert result["issue"]["issue_key"] == "ABC-1"
    assert result["comments"][0]["comment_id"] == "10"
    assert result["attachments"][0]["filename"] == "trace.txt"
    serialized = repr(result)
    assert "source_path" not in serialized and "source_page" not in serialized


def test_readonly_database_rejects_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.sqlite3"
    connection = _database(db_path)
    connection.close()

    readonly = open_knowledge_db_readonly(db_path)
    assert readonly.execute("SELECT COUNT(*) FROM knowledge_item").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        readonly.execute("DELETE FROM knowledge_item")
    readonly.close()


def test_mcp_lists_and_calls_exactly_two_readonly_tools() -> None:
    async def scenario() -> None:
        server = create_mcp_server(_service())
        async with Client(server, raise_exceptions=True) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            assert set(tools) == {"search_jira_knowledge", "get_jira_issue"}
            for tool in tools.values():
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.open_world_hint is False

            search = await client.call_tool(
                "search_jira_knowledge",
                {"query": "retry timeout", "top_k": 3},
            )
            assert search.is_error is False
            assert search.structured_content is not None
            assert search.structured_content["results"][0]["knowledge_item_id"] == "ki_1"

            issue = await client.call_tool("get_jira_issue", {"issue_key": "ABC-1"})
            assert issue.is_error is False
            assert issue.structured_content is not None
            assert issue.structured_content["issue"]["issue_key"] == "ABC-1"

    asyncio.run(scenario())


def test_real_run_payload_gate_accepts_safe_mcp_outputs() -> None:
    service = _service()
    search = service.search_jira_knowledge("retry timeout")
    issue = service.get_jira_issue("ABC-1")

    validation = validate_m10_payloads(search, issue)

    assert validation.passed
    assert validation.search_result_count == 1
    assert validation.evidence_count == 1
    assert validation.warning_count == 0
    assert validation.path_leak_count == 0
    assert validation.issue_lookup_ok


def test_real_run_payload_gate_rejects_warning_and_path_leak() -> None:
    service = _service()
    search = service.search_jira_knowledge("retry timeout")
    issue = service.get_jira_issue("ABC-1")
    search["warnings"] = [{"code": "TEST"}]
    issue["source_path"] = "/internal/path"

    validation = validate_m10_payloads(search, issue)

    assert not validation.passed
    assert validation.warning_count == 1
    assert validation.path_leak_count == 1
    assert len(validation.failures) == 2
