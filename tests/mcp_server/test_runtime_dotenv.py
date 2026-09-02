from __future__ import annotations

import sqlite3
from pathlib import Path

import jira_collector.mcp_server.runtime as runtime
from jira_collector.mcp_server.runtime import (
    _build_operational_search_head_provider,
    _load_runtime_environment,
    _optional_path,
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


def test_g4_provider_resolves_bundle_for_current_read_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    retrieval_root = tmp_path / "retrieval" / "operational"
    retrieval_root.mkdir(parents=True)
    expected = retrieval_root / "runs" / "pr_active"
    expected.mkdir(parents=True)
    calls: list[tuple[Path, frozenset[str]]] = []

    class FakeSearcher:
        manifest = object()

    fake_searcher = FakeSearcher()
    monkeypatch.setattr(
        runtime,
        "active_generation_ids_from_connection",
        lambda connection: frozenset({"kg_active"}),
    )

    def fake_resolver(root_path, generations):
        calls.append((Path(root_path), frozenset(generations)))
        return expected

    monkeypatch.setattr(runtime, "retrieval_artifact_dir_for_generation_set", fake_resolver)
    monkeypatch.setattr(runtime, "load_retrieval_searcher", lambda path: fake_searcher)
    provider = _build_operational_search_head_provider(retrieval_root, object())

    connection = sqlite3.connect(":memory:")
    try:
        head = provider(connection)
        cached = provider(connection)
    finally:
        connection.close()

    assert head.searcher is fake_searcher
    assert cached.searcher is fake_searcher
    assert calls == [(retrieval_root, frozenset({"kg_active"}))]


def test_legacy_retrieval_artifact_dir_path_remains_supported(tmp_path: Path) -> None:
    retrieval_dir = tmp_path / "retrieval" / "legacy"
    retrieval_dir.mkdir(parents=True)

    resolved = _optional_path(
        {"JIRA_RETRIEVAL_ARTIFACT_DIR": str(retrieval_dir)},
        "JIRA_RETRIEVAL_ARTIFACT_DIR",
    )

    assert resolved == retrieval_dir.resolve()
