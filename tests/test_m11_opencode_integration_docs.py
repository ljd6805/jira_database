from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_m11_opencode_integration_is_current_and_linked() -> None:
    m11_path = Path("docs/status/M11_OPENCODE_MCP_INTEGRATION.html")
    assert m11_path.is_file()
    m11 = m11_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in m11.lower()
    assert "OpenCode" in m11
    assert "M11" in m11 and "CURRENT" in m11
    assert "프로젝트 내부에 Agent를 구현" in m11

    for path in (
        "README.md",
        "docs/index.html",
        "docs/status/jira_knowledge_db_current_status.html",
    ):
        text = _read(path)
        assert "M11" in text and "CURRENT" in text
        assert "M11_OPENCODE_MCP_INTEGRATION.html" in text


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


def test_m11_opencode_real_run_has_discovery_and_explicit_call_pass() -> None:
    required = (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/M11_OPENCODE_MCP_INTEGRATION.html",
    )
    for path in required:
        text = _read(path)
        assert "M11-03" in text and "PASS" in text
        assert "M11-04" in text and "PASS" in text
        assert "M11-05" in text and "NEXT" in text

    m11 = _read("docs/status/M11_OPENCODE_MCP_INTEGRATION.html")
    for token in (
        "get_jira_issue",
        "search_jira_knowledge",
        "Tool discovery PASS",
        "Explicit Tool call PASS",
        "실제 OpenCode",
    ):
        assert token in m11
