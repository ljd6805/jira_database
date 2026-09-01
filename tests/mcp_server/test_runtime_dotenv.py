from __future__ import annotations

from pathlib import Path

import jira_collector.mcp_server.runtime as runtime
from jira_collector.mcp_server.runtime import (
    _load_runtime_environment,
    _resolve_retrieval_dir,
)


def test_runtime_loads_service_settings_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    for name in (
        "JIRA_KNOWLEDGE_DB_PATH",
        "JIRA_RETRIEVAL_ARTIFACT_DIR",
        "JIRA_RETRIEVAL_ARTIFACT_ROOT",
        "BGE_M3_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "JIRA_KNOWLEDGE_DB_PATH=C:/service/knowledge.sqlite3\n"
        "JIRA_RETRIEVAL_ARTIFACT_DIR=C:/service/retrieval\n"
        "JIRA_RETRIEVAL_ARTIFACT_ROOT=C:/service/retrieval-operational\n"
        "BGE_M3_ENDPOINT=https://embedding.example.com/v1/embeddings\n",
        encoding="utf-8",
    )

    environment = _load_runtime_environment(env=None, dotenv_path=dotenv_path)

    assert environment["JIRA_KNOWLEDGE_DB_PATH"] == "C:/service/knowledge.sqlite3"
    assert environment["JIRA_RETRIEVAL_ARTIFACT_DIR"] == "C:/service/retrieval"
    assert environment["JIRA_RETRIEVAL_ARTIFACT_ROOT"] == "C:/service/retrieval-operational"
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


def test_g4_retrieval_root_resolves_active_bundle_at_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    knowledge_db = tmp_path / "knowledge.sqlite3"
    knowledge_db.touch()
    retrieval_root = tmp_path / "retrieval" / "operational"
    retrieval_root.mkdir(parents=True)
    expected = retrieval_root / "runs" / "pr_active"
    expected.mkdir(parents=True)
    calls: list[tuple[Path, Path]] = []

    def fake_resolver(db_path, root_path):
        calls.append((Path(db_path), Path(root_path)))
        return expected

    monkeypatch.setattr(runtime, "active_retrieval_artifact_dir", fake_resolver)
    resolved = _resolve_retrieval_dir(
        {"JIRA_RETRIEVAL_ARTIFACT_ROOT": str(retrieval_root)},
        knowledge_db,
    )

    assert resolved == expected
    assert calls == [(knowledge_db, retrieval_root.resolve())]


def test_legacy_retrieval_artifact_dir_remains_supported(tmp_path: Path) -> None:
    knowledge_db = tmp_path / "knowledge.sqlite3"
    knowledge_db.touch()
    retrieval_dir = tmp_path / "retrieval" / "legacy"
    retrieval_dir.mkdir(parents=True)

    resolved = _resolve_retrieval_dir(
        {"JIRA_RETRIEVAL_ARTIFACT_DIR": str(retrieval_dir)},
        knowledge_db,
    )

    assert resolved == retrieval_dir.resolve()
