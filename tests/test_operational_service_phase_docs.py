from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_operational_service_phase_is_documented_and_linked() -> None:
    path = "docs/architecture/jira_knowledge_operational_service_phase.html"
    text = _read(path)
    assert "<!doctype html>" in text.lower()
    for token in (
        "Functional MVP",
        "Project Discovery",
        "Delta Issue Sync",
        "Knowledge / Evidence",
        "Embedding / FAISS",
        "Central Remote MCP",
        "delta-first",
    ):
        assert token in text

    for source in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
    ):
        body = _read(source)
        assert "jira_knowledge_operational_service_phase.html" in body
        assert "M0~M11" in body
        assert "MVP" in body


def test_remote_mcp_is_only_one_operational_service_component() -> None:
    text = _read("docs/architecture/jira_knowledge_mcp_service_target.html")
    assert "운영 서비스" in text
    assert "구성요소" in text
    assert "Remote MCP만으로 서비스가 완성되는 것은 아니" in text
    assert "jira_knowledge_operational_service_phase.html" in text


def test_operational_service_scope_keeps_project_and_delta_updates() -> None:
    text = _read("docs/architecture/jira_knowledge_operational_service_phase.html")
    for token in (
        "새 프로젝트",
        "자동 발견",
        "source_hash 동일",
        "source_hash 변경",
        "unchanged",
        "changed",
        "full rebuild",
        "checkpoint",
    ):
        assert token in text


def test_operational_service_flags_access_control_as_unresolved() -> None:
    text = _read("docs/architecture/jira_knowledge_operational_service_phase.html")
    for token in (
        "프로젝트 권한 상실",
        "팀원별 Jira 권한",
        "MVP",
        "정책",
    ):
        assert token in text
