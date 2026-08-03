from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv


class SettingsError(ValueError):
    """Raised when required configuration is missing or invalid."""


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SettingsError(f"필수 환경 변수 {name}가 비어 있습니다.")
    return value


@dataclass(frozen=True)
class PaginationSettings:
    project_page_size: int
    search_page_size: int
    comment_page_size: int


@dataclass(frozen=True)
class CollectionSettings:
    project_scope: str
    issues_per_project: int
    issue_order: str
    collect_comments: bool
    download_attachments: bool


@dataclass(frozen=True)
class RateLimitSettings:
    requests_per_minute: int
    max_concurrency: int

    @property
    def min_request_interval_seconds(self) -> float:
        return 60.0 / self.requests_per_minute


@dataclass(frozen=True)
class TimeoutSettings:
    connect_seconds: float
    read_seconds: float


@dataclass(frozen=True)
class RetrySettings:
    max_attempts: int
    backoff_initial_seconds: float
    backoff_max_seconds: float


@dataclass(frozen=True)
class JiraSettings:
    base_url: str
    username: str
    password: str
    api_base_path: str
    myself_path: str
    project_list_path: str
    issue_search_path: str
    issue_path: str
    comment_path: str
    pagination: PaginationSettings
    collection: CollectionSettings
    rate_limit: RateLimitSettings
    timeout: TimeoutSettings
    retry: RetrySettings

    def api_url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{self.api_base_path.strip('/')}/{path.lstrip('/')}"


@dataclass(frozen=True)
class StorageSettings:
    data_root: Path
    raw_directory: str
    state_directory: str
    report_directory: str

    @property
    def raw_root(self) -> Path:
        return self.data_root / self.raw_directory

    @property
    def state_root(self) -> Path:
        return self.data_root / self.state_directory

    @property
    def report_root(self) -> Path:
        return self.data_root / self.report_directory


@dataclass(frozen=True)
class LoggingSettings:
    level: str
    log_response_body: bool


@dataclass(frozen=True)
class AppSettings:
    jira: JiraSettings
    storage: StorageSettings
    logging: LoggingSettings


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SettingsError(f"설정 파일을 찾을 수 없습니다: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SettingsError(f"YAML 설정 파일을 읽을 수 없습니다: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SettingsError(f"설정 파일 최상위 값은 객체여야 합니다: {path}")
    return loaded


def load_settings(
    config_path: str | Path = "config/settings.yaml",
    *,
    local_config_path: str | Path | None = "config/settings.local.yaml",
    dotenv_path: str | Path | None = ".env",
    env: Mapping[str, str] | None = None,
) -> AppSettings:
    config_file = Path(config_path)

    if dotenv_path is not None:
        load_dotenv(Path(dotenv_path), override=False)

    environment: Mapping[str, str] = os.environ if env is None else env
    raw = _load_yaml(config_file)

    if local_config_path is not None:
        local_file = Path(local_config_path)
        if local_file.exists():
            raw = _deep_merge(raw, _load_yaml(local_file))

    jira_raw = raw.get("jira", {})
    storage_raw = raw.get("storage", {})
    logging_raw = raw.get("logging", {})

    base_url = _required_env(environment, "JIRA_BASE_URL").rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SettingsError("JIRA_BASE_URL은 http:// 또는 https:// 형식의 URL이어야 합니다.")

    username = _required_env(environment, "JIRA_USERNAME")
    password = _required_env(environment, "JIRA_PASSWORD")

    pagination_raw = jira_raw.get("pagination", {})
    collection_raw = jira_raw.get("collection", {})
    rate_raw = jira_raw.get("rate_limit", {})
    timeout_raw = jira_raw.get("timeout", {})
    retry_raw = jira_raw.get("retry", {})

    requests_per_minute = int(rate_raw.get("requests_per_minute", 20))
    if not 1 <= requests_per_minute <= 20:
        raise SettingsError("jira.rate_limit.requests_per_minute는 1~20 사이여야 합니다.")

    max_concurrency = int(rate_raw.get("max_concurrency", 1))
    if max_concurrency != 1:
        raise SettingsError("파일럿에서는 jira.rate_limit.max_concurrency를 1로 설정해야 합니다.")

    issues_per_project = int(collection_raw.get("issues_per_project", 30))
    if issues_per_project <= 0:
        raise SettingsError("jira.collection.issues_per_project는 1 이상이어야 합니다.")

    data_root = Path(storage_raw.get("data_root", "./data")).expanduser()

    jira = JiraSettings(
        base_url=base_url,
        username=username,
        password=password,
        api_base_path=str(jira_raw.get("api_base_path", "/rest/api/2")),
        myself_path=str(jira_raw.get("myself_path", "/myself")),
        project_list_path=str(jira_raw.get("project_list_path", "/project")),
        issue_search_path=str(jira_raw.get("issue_search_path", "/search")),
        issue_path=str(jira_raw.get("issue_path", "/issue/{issue_key}")),
        comment_path=str(jira_raw.get("comment_path", "/issue/{issue_key}/comment")),
        pagination=PaginationSettings(
            project_page_size=int(pagination_raw.get("project_page_size", 50)),
            search_page_size=int(pagination_raw.get("search_page_size", 30)),
            comment_page_size=int(pagination_raw.get("comment_page_size", 100)),
        ),
        collection=CollectionSettings(
            project_scope=str(collection_raw.get("project_scope", "all_accessible")),
            issues_per_project=issues_per_project,
            issue_order=str(collection_raw.get("issue_order", "updated_desc")),
            collect_comments=bool(collection_raw.get("collect_comments", True)),
            download_attachments=bool(collection_raw.get("download_attachments", False)),
        ),
        rate_limit=RateLimitSettings(
            requests_per_minute=requests_per_minute,
            max_concurrency=max_concurrency,
        ),
        timeout=TimeoutSettings(
            connect_seconds=float(timeout_raw.get("connect_seconds", 10)),
            read_seconds=float(timeout_raw.get("read_seconds", 60)),
        ),
        retry=RetrySettings(
            max_attempts=int(retry_raw.get("max_attempts", 3)),
            backoff_initial_seconds=float(retry_raw.get("backoff_initial_seconds", 3)),
            backoff_max_seconds=float(retry_raw.get("backoff_max_seconds", 60)),
        ),
    )

    if jira.pagination.project_page_size <= 0:
        raise SettingsError("project_page_size는 1 이상이어야 합니다.")
    if jira.pagination.search_page_size <= 0:
        raise SettingsError("search_page_size는 1 이상이어야 합니다.")
    if jira.pagination.comment_page_size <= 0:
        raise SettingsError("comment_page_size는 1 이상이어야 합니다.")
    if jira.retry.max_attempts <= 0:
        raise SettingsError("max_attempts는 1 이상이어야 합니다.")

    storage = StorageSettings(
        data_root=data_root,
        raw_directory=str(storage_raw.get("raw_directory", "raw")),
        state_directory=str(storage_raw.get("state_directory", "state")),
        report_directory=str(storage_raw.get("report_directory", "reports")),
    )

    logging_settings = LoggingSettings(
        level=str(logging_raw.get("level", "INFO")).upper(),
        log_response_body=bool(logging_raw.get("log_response_body", False)),
    )

    return AppSettings(jira=jira, storage=storage, logging=logging_settings)
