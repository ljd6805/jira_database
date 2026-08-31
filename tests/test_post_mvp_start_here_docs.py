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


def test_next_session_starts_from_v3_implementation_gate() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "Sync Contract v3",
        "State Schema v3",
        "D10 Latest-Only",
        "Documentation Shell / Registry / pytest Gate PASS",
        "State Schema v3 explicit Migration",
        "Source Ready",
        "superseded",
        "stale guard",
    ):
        assert token in text


def test_handoff_preserves_full_operational_service_scope() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    upper = text.upper()
    assert "SOURCE SYNC" in upper
    for token in (
        "OpenCode",
        "Embedding",
        "FAISS",
        "Atomic Publish",
        "Structured Logging",
        "Remote MCP Operations / Team Pilot",
    ):
        assert token in text


def test_handoff_preserves_source_history_latest_only_policy() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "Source History",
        "모두 보존",
        "latest + source-ready Work",
        "superseded",
        "Jira 원문은 로그에 기록하지 않습니다",
    ):
        assert token in text


def test_handoff_does_not_prematurely_freeze_next_milestone_number() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "M12 CURRENT" not in text
    assert "M13 CURRENT" not in text
    assert "M12 DONE" not in text
    assert "M13 DONE" not in text
