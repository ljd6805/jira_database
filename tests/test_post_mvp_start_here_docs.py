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


def test_next_session_starts_after_loop_b_knowledge_implementation() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "State Migration / StateStore foundation",
        "semantic_v2 source hash",
        "Loop A Delta Source Sync",
        "Loop B Latest-Only Knowledge Worker",
        "IMPLEMENTED",
        "실제 local collector.db Migration",
        "실제 사내 Jira Loop A Run",
        "실제 사내 OpenCode Knowledge Run",
        "Operational Data Plane Integration",
    ):
        assert token in text


def test_handoff_preserves_full_operational_service_scope() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    upper = text.upper()
    assert "LOOP A" in upper
    assert "LOOP B" in upper
    assert "OPENCODE" in upper
    for token in (
        "Knowledge DB incremental materialization",
        "BGE-M3",
        "FAISS staging",
        "Atomic Publish",
        "Remote MCP Operations / Team Pilot",
    ):
        assert token in text


def test_handoff_preserves_source_history_latest_only_policy() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "Source History",
        "모두 보존",
        "Source-ready",
        "superseded",
        "latestness",
    ):
        assert token in text


def test_handoff_links_current_implementation_reports() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html" in text
    assert "LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html" in text
    assert "OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html" in text


def test_handoff_does_not_prematurely_freeze_next_milestone_number() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "M12 CURRENT" not in text
    assert "M13 CURRENT" not in text
    assert "M12 DONE" not in text
    assert "M13 DONE" not in text
