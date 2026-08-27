from __future__ import annotations

from pathlib import Path

from jira_collector.mcp_server.runtime import _load_runtime_environment


def test_runtime_loads_service_settings_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    for name in (
        "JIRA_KNOWLEDGE_DB_PATH",
        "JIRA_RETRIEVAL_ARTIFACT_DIR",
        "BGE_M3_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "JIRA_KNOWLEDGE_DB_PATH=C:/service/knowledge.sqlite3\n"
        "JIRA_RETRIEVAL_ARTIFACT_DIR=C:/service/retrieval\n"
        "BGE_M3_ENDPOINT=https://embedding.example.com/v1/embeddings\n",
        encoding="utf-8",
    )

    environment = _load_runtime_environment(env=None, dotenv_path=dotenv_path)

    assert environment["JIRA_KNOWLEDGE_DB_PATH"] == "C:/service/knowledge.sqlite3"
    assert environment["JIRA_RETRIEVAL_ARTIFACT_DIR"] == "C:/service/retrieval"
    assert environment["BGE_M3_ENDPOINT"] == "https://embedding.example.com/v1/embeddings"


def test_runtime_os_environment_overrides_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JIRA_KNOWLEDGE_DB_PATH", "C:/override/knowledge.sqlite3")
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "JIRA_KNOWLEDGE_DB_PATH=C:/dotenv/knowledge.sqlite3\n",
        encoding="utf-8",
    )

    environment = _load_runtime_environment(env=None, dotenv_path=dotenv_path)

    assert environment["JIRA_KNOWLEDGE_DB_PATH"] == "C:/override/knowledge.sqlite3"


def test_explicit_env_mapping_does_not_read_dotenv(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("JIRA_KNOWLEDGE_DB_PATH=from-dotenv\n", encoding="utf-8")
    explicit = {"JIRA_KNOWLEDGE_DB_PATH": "from-test"}

    environment = _load_runtime_environment(env=explicit, dotenv_path=dotenv_path)

    assert environment is explicit
    assert environment["JIRA_KNOWLEDGE_DB_PATH"] == "from-test"
