from __future__ import annotations

from pathlib import Path


START_HERE = Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html")


def test_post_mvp_start_here_exists_and_is_html() -> None:
    assert START_HERE.is_file()
    text = START_HERE.read_text(encoding="utf-8")
    assert "<!doctype html>" in text.lower()
    assert "M0~M11" in text
    assert "Functional MVP" in text
    assert "Continuous Jira Knowledge Service" in text


def test_next_session_starts_from_sync_contract_not_implementation() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "첫 작업 = Sync Contract 설계",
        "코드부터 만들지 않습니다",
        "Project Discovery",
        "Delta Issue Sync",
        "checkpoint",
        "resume",
        "source_hash",
    ):
        assert token in text


def test_handoff_preserves_full_operational_service_scope() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    for token in (
        "지속적인 Jira 업데이트",
        "Project 추가",
        "Embedding",
        "FAISS",
        "중앙 MCP 서비스",
        "운영 자동화",
        "팀원별 Jira 권한",
    ):
        assert token in text


def test_handoff_does_not_freeze_next_milestone_number() -> None:
    text = START_HERE.read_text(encoding="utf-8")
    assert "M12, M13 같은 번호를 아직 확정하지 않았습니다" in text
    assert "첫 운영 Milestone 번호" in text
