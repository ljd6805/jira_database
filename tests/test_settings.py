from __future__ import annotations

from pathlib import Path

import pytest

from jira_collector.settings import SettingsError, load_settings


def test_loads_separate_url_username_and_password(settings_file: Path) -> None:
    settings = load_settings(
        settings_file,
        local_config_path=None,
        dotenv_path=None,
        env={
            "JIRA_BASE_URL": "https://jira.internal",
            "JIRA_USERNAME": "alice",
            "JIRA_PASSWORD": "secret",
        },
    )

    assert settings.jira.base_url == "https://jira.internal"
    assert settings.jira.username == "alice"
    assert settings.jira.password == "secret"
    assert settings.jira.verify_ssl is False
    assert settings.jira.rate_limit.requests_per_minute == 20
    assert settings.jira.rate_limit.min_request_interval_seconds == 3.0


def test_rejects_non_boolean_verify_ssl(settings_file: Path) -> None:
    content = settings_file.read_text(encoding="utf-8").replace(
        "verify_ssl: false", 'verify_ssl: "false"'
    )
    settings_file.write_text(content, encoding="utf-8")

    with pytest.raises(SettingsError, match="true 또는 false"):
        load_settings(
            settings_file,
            local_config_path=None,
            dotenv_path=None,
            env={
                "JIRA_BASE_URL": "https://jira.internal",
                "JIRA_USERNAME": "alice",
                "JIRA_PASSWORD": "secret",
            },
        )


def test_rejects_rate_limit_above_twenty(settings_file: Path) -> None:
    content = settings_file.read_text(encoding="utf-8").replace(
        "requests_per_minute: 20", "requests_per_minute: 21"
    )
    settings_file.write_text(content, encoding="utf-8")

    with pytest.raises(SettingsError, match="1~20"):
        load_settings(
            settings_file,
            local_config_path=None,
            dotenv_path=None,
            env={
                "JIRA_BASE_URL": "https://jira.internal",
                "JIRA_USERNAME": "alice",
                "JIRA_PASSWORD": "secret",
            },
        )


def test_requires_credentials(settings_file: Path) -> None:
    with pytest.raises(SettingsError, match="JIRA_PASSWORD"):
        load_settings(
            settings_file,
            local_config_path=None,
            dotenv_path=None,
            env={
                "JIRA_BASE_URL": "https://jira.internal",
                "JIRA_USERNAME": "alice",
                "JIRA_PASSWORD": "",
            },
        )
