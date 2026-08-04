from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from .rate_limiter import IntervalRateLimiter
from .settings import JiraSettings

LOGGER = logging.getLogger(__name__)


class JiraClientError(RuntimeError):
    """Base class for Jira client failures."""


class JiraAuthenticationError(JiraClientError):
    """Raised for HTTP 401."""


class JiraPermissionError(JiraClientError):
    """Raised for HTTP 403."""


class JiraNotFoundError(JiraClientError):
    """Raised for HTTP 404."""


class JiraResponseError(JiraClientError):
    """Raised for unexpected HTTP or JSON responses."""


@dataclass(frozen=True)
class ApiResult:
    payload: Any
    status_code: int
    url: str
    headers: Mapping[str, str]


class JiraClient:
    def __init__(
        self,
        settings: JiraSettings,
        *,
        session: requests.Session | None = None,
        limiter: IntervalRateLimiter | None = None,
        sleeper=time.sleep,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.auth = (settings.username, settings.password)
        self.session.verify = settings.verify_ssl
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "jira-raw-data-collector/0.1.0",
            }
        )
        if not settings.verify_ssl:
            urllib3.disable_warnings(InsecureRequestWarning)
            LOGGER.warning(
                "Jira HTTPS 인증서 검증이 비활성화되어 있습니다. "
                "신뢰할 수 있는 사내 Jira에서만 사용하십시오."
            )
        self.limiter = limiter or IntervalRateLimiter(
            settings.rate_limit.requests_per_minute,
            sleeper=sleeper,
        )
        self._sleeper = sleeper

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "JiraClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> ApiResult:
        url = self.settings.api_url(path)
        last_error: Exception | None = None

        for attempt in range(1, self.settings.retry.max_attempts + 1):
            self.limiter.wait()
            try:
                response = self.session.get(
                    url,
                    params=dict(params or {}),
                    timeout=(
                        self.settings.timeout.connect_seconds,
                        self.settings.timeout.read_seconds,
                    ),
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.settings.retry.max_attempts:
                    break
                delay = self._backoff(attempt)
                LOGGER.warning(
                    "Jira 연결 오류. %s초 후 재시도합니다. attempt=%s/%s",
                    delay,
                    attempt,
                    self.settings.retry.max_attempts,
                )
                self._sleeper(delay)
                continue

            if response.status_code == 401:
                raise JiraAuthenticationError("Jira 인증에 실패했습니다. 사용자명과 비밀번호를 확인하십시오.")
            if response.status_code == 403:
                raise JiraPermissionError(f"Jira 접근 권한이 없습니다: {response.url}")
            if response.status_code == 404:
                raise JiraNotFoundError(f"Jira 리소스를 찾을 수 없습니다: {response.url}")

            if response.status_code == 429:
                if attempt >= self.settings.retry.max_attempts:
                    raise JiraResponseError("Jira API 요청 제한(429)이 반복되어 수집을 중단했습니다.")
                retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
                delay = max(self.limiter.interval_seconds, retry_after)
                LOGGER.warning("Jira API 429 응답. %s초 후 재시도합니다.", delay)
                self._sleeper(delay)
                continue

            if 500 <= response.status_code < 600:
                if attempt >= self.settings.retry.max_attempts:
                    raise JiraResponseError(
                        f"Jira 서버 오류가 반복되었습니다: HTTP {response.status_code}"
                    )
                delay = self._backoff(attempt)
                LOGGER.warning(
                    "Jira 서버 오류 HTTP %s. %s초 후 재시도합니다.",
                    response.status_code,
                    delay,
                )
                self._sleeper(delay)
                continue

            if not 200 <= response.status_code < 300:
                raise JiraResponseError(
                    f"예상하지 못한 Jira 응답입니다: HTTP {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise JiraResponseError(
                    f"Jira 응답이 JSON이 아닙니다: HTTP {response.status_code}"
                ) from exc

            return ApiResult(
                payload=payload,
                status_code=response.status_code,
                url=response.url,
                headers=dict(response.headers),
            )

        raise JiraClientError(f"Jira 요청에 실패했습니다: {url}: {last_error}") from last_error

    def check_connection(self) -> ApiResult:
        return self.get_json(self.settings.myself_path)

    def _backoff(self, attempt: int) -> float:
        raw = self.settings.retry.backoff_initial_seconds * (2 ** (attempt - 1))
        return min(raw, self.settings.retry.backoff_max_seconds)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            return max(0.0, float(value))
        except ValueError:
            return 0.0
