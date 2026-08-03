from __future__ import annotations

from pathlib import Path

import pytest

from jira_collector.settings import load_settings


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(
        """
jira:
  api_base_path: /rest/api/2
  myself_path: /myself
  project_list_path: /project
  issue_search_path: /search
  issue_path: /issue/{issue_key}
  comment_path: /issue/{issue_key}/comment
  pagination:
    project_page_size: 2
    search_page_size: 2
    comment_page_size: 2
  collection:
    project_scope: all_accessible
    issues_per_project: 30
    issue_order: updated_desc
    collect_comments: true
    download_attachments: false
  rate_limit:
    requests_per_minute: 20
    max_concurrency: 1
  timeout:
    connect_seconds: 1
    read_seconds: 2
  retry:
    max_attempts: 3
    backoff_initial_seconds: 1
    backoff_max_seconds: 4
storage:
  data_root: DATA_ROOT_PLACEHOLDER
  raw_directory: raw
  state_directory: state
  report_directory: reports
logging:
  level: INFO
  log_response_body: false
""".replace("DATA_ROOT_PLACEHOLDER", str(tmp_path / "data")),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def app_settings(settings_file: Path):
    return load_settings(
        settings_file,
        local_config_path=None,
        dotenv_path=None,
        env={
            "JIRA_BASE_URL": "https://jira.example.com",
            "JIRA_USERNAME": "user",
            "JIRA_PASSWORD": "password",
        },
    )
