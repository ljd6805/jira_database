from __future__ import annotations

from pathlib import Path

import yaml


POLICY = Path("docs/architecture/jira_operational_fresh_bootstrap_smoke_policy.html")
SMOKE_CONFIG = Path("config/settings.smoke.yaml")


def test_smoke_config_uses_isolated_data_root() -> None:
    assert SMOKE_CONFIG.is_file()
    loaded = yaml.safe_load(SMOKE_CONFIG.read_text(encoding="utf-8"))
    assert loaded["storage"]["data_root"] == "./data_smoke"
    assert "data_smoke/" in Path(".gitignore").read_text(encoding="utf-8")


def test_fresh_bootstrap_policy_is_documented_and_current() -> None:
    assert POLICY.is_file()
    text = POLICY.read_text(encoding="utf-8")
    for token in (
        "Fresh Bootstrap",
        "data_smoke",
        "정식 Real Test",
        "Full Initial Ingest",
        "Migration",
        "compatibility",
        "--max-issues-per-project 1",
    ):
        assert token in text


def test_current_entry_docs_link_fresh_bootstrap_policy() -> None:
    for path in (
        Path("docs/index.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
        Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html"),
    ):
        text = path.read_text(encoding="utf-8")
        assert "jira_operational_fresh_bootstrap_smoke_policy.html" in text
        assert "Fresh Bootstrap" in text
