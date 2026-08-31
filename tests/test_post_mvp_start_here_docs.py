from __future__ import annotations

from pathlib import Path


START_HERE = Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html")


def test_post_mvp_start_here_exists_and_is_html() -> None:
    assert START_HERE.is_file()
    text = START_HERE.read_text(encoding="utf-8")
    assert "<!doctype html>" in text.lower()
    assert "M0~M11" in text
    assert "Functional MVP" in text
    assert "Latest-Only" in text
    assert "개정 3" in text


def test_next_session_starts_after_knowledge_db_and_embedding_implementation() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "State Migration / StateStore foundation",
        "semantic_v2 source hash",
        "Loop A Delta Source Sync",
        "Loop B Knowledge Automation",
        "per-Work Knowledge DB materialization",
        "Incremental BGE-M3 staging",
        "IMPLEMENTED",
        "실제 local collector.db Migration",
        "실제 사내 Jira Loop A Run",
        "실제 사내 OpenCode Knowledge Run",
        "실제 jira-knowledge-extraction Skill load",
        "Atomic Publish",
    ):
        assert token in text


def test_handoff_preserves_full_operational_service_scope() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    upper = text.upper()
    assert "LOOP A" in upper
    assert "LOOP B" in upper
    assert "OPENCODE" in upper
    for token in (
        "per-Work Knowledge DB materialization",
        "BGE-M3",
        "FAISS",
        "Atomic Publish",
        "Structured Logging",
        "Remote MCP Operations / Team Pilot",
    ):
        assert token in text


def test_handoff_preserves_source_history_latest_only_policy() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "latest Work",
        "Source-ready",
        "latestness",
        "superseded",
    ):
        assert token in text


def test_handoff_records_opencode_automation_real_run_and_scheduler_separately() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "Loop B Knowledge Automation",
        "Real Internal OpenCode Run",
        "Continuous",
        "NOT IMPLEMENTED",
        "jira-knowledge-extraction",
        "Skill",
    ):
        assert token in text


def test_handoff_links_current_implementation_and_easy_guide() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html" in text
    assert "OPERATIONAL_INCREMENTAL_EMBEDDING_IMPLEMENTATION.html" in text
    assert "jira_loop_b_opencode_automation_easy_guide.html" in text


def test_handoff_does_not_prematurely_freeze_next_milestone_number() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "M12 CURRENT" not in text
    assert "M13 CURRENT" not in text
    assert "M12 DONE" not in text
    assert "M13 DONE" not in text
