from __future__ import annotations

from pathlib import Path


START_HERE = Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html")


def test_post_mvp_start_here_exists_and_is_html() -> None:
    assert START_HERE.is_file()
    text = START_HERE.read_text(encoding="utf-8")
    assert "<!doctype html>" in text.lower()
    assert "M0~M11" in text
    assert "Functional MVP" in text
    assert "TWO-LOOP" in text.upper() or "2-LOOP" in text.upper()
    assert "Latest-Only" in text


def test_next_session_starts_after_state_and_loop_a_implementation() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "현재 운영 Sync 규칙 · 개정 3",
        "현재 Operational State 설계 · 개정 3",
        "State Migration / StateStore foundation",
        "semantic_v2 source hash",
        "Loop A Delta Source Sync",
        "IMPLEMENTED",
        "실제 local collector.db Migration",
        "실제 사내 Jira Loop A Run",
        "Loop B Latest-Only Single Worker",
        "Source Ready",
        "superseded",
        "stale guard",
    ):
        assert token in text


def test_handoff_preserves_full_operational_service_scope() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    upper = text.upper()
    assert "SOURCE SYNC" in upper
    assert "OPENCODE" in upper
    for token in (
        "Knowledge / Review / Evidence",
        "BGE-M3 / FAISS staging / Atomic Publish",
        "Structured Logging / Lag / Backlog Monitoring",
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
    ):
        assert token in text

    implementation = Path(
        "docs/status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html"
    ).read_text(encoding="utf-8")
    assert "Jira 본문/댓글" in implementation
    assert "기록하지 않고" in implementation


def test_handoff_links_loop_a_implementation_report() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html" in text


def test_handoff_does_not_prematurely_freeze_next_milestone_number() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "M12 CURRENT" not in text
    assert "M13 CURRENT" not in text
    assert "M12 DONE" not in text
    assert "M13 DONE" not in text
