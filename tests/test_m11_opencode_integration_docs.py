from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_m11_opencode_integration_is_done_and_linked() -> None:
    m11_path = Path("docs/status/M11_OPENCODE_MCP_INTEGRATION.html")
    completion_path = Path("docs/status/M11_COMPLETION.html")
    assert m11_path.is_file()
    assert completion_path.is_file()

    for path in (m11_path, completion_path):
        text = path.read_text(encoding="utf-8")
        assert "<!doctype html>" in text.lower()
        assert "OpenCode" in text
        assert "M11" in text and "DONE" in text and "PASS" in text

    m11 = m11_path.read_text(encoding="utf-8")
    assert "프로젝트 안에 Agent를 새로 구현" in m11

    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
    ):
        text = _read(path)
        assert "M11" in text and "DONE" in text and "PASS" in text
        assert "M11_COMPLETION.html" in text


def test_m11_service_configuration_uses_dotenv_policy() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/M11_OPENCODE_MCP_INTEGRATION.html",
    ):
        text = _read(path)
        for token in (
            ".env",
            "JIRA_KNOWLEDGE_DB_PATH",
            "JIRA_RETRIEVAL_ARTIFACT_DIR",
            "BGE_M3_ENDPOINT",
        ):
            assert token in text

    env_example = _read(".env.example")
    assert "JIRA_KNOWLEDGE_DB_PATH=" in env_example
    assert "JIRA_RETRIEVAL_ARTIFACT_DIR=" in env_example
    assert "BGE_M3_ENDPOINT=" in env_example
    assert "M10_REAL_RUN_QUERY는 서비스 설정이 아니라" in env_example

    gitignore = _read(".gitignore").splitlines()
    assert ".env" in gitignore


def test_mcp_runtime_loads_dotenv_without_overriding_os_environment() -> None:
    runtime = _read("src/jira_collector/mcp_server/runtime.py")
    assert "load_dotenv" in runtime
    assert 'dotenv_path: str | Path | None = ".env"' in runtime
    assert "override=False" in runtime
    assert "load_embedding_settings(dotenv_path=None, env=environment)" in runtime


def test_m11_all_opencode_real_run_gates_are_pass() -> None:
    required = (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/M11_OPENCODE_MCP_INTEGRATION.html",
        "docs/status/M11_COMPLETION.html",
    )
    for path in required:
        text = _read(path)
        for gate in ("M11-03", "M11-04", "M11-05", "M11-06"):
            assert gate in text and "PASS" in text
        assert "M11" in text and "DONE" in text

    m11 = _read("docs/status/M11_COMPLETION.html")
    for token in (
        "get_jira_issue",
        "search_jira_knowledge",
        "자동 Tool 선택",
        "description",
        "comment",
        "Evidence",
        "M11 DONE / PASS",
    ):
        assert token in m11


def test_m11_completion_preserves_privacy_and_remote_service_target() -> None:
    completion = _read("docs/status/M11_COMPLETION.html")
    assert "실제 업무 질문, Issue key, Jira 원문" in completion
    assert "Remote MCP" in completion
    assert "Streamable HTTP" in completion
    assert "다음 Milestone 번호는 아직 고정하지 않습니다" in completion
