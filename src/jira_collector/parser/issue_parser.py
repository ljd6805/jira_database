from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import IssueParseResult, IssueRecord, IssueSource, ParseWarning
from .value_helpers import (
    html_to_text,
    looks_like_html,
    named_value,
    optional_string,
    value_type_name,
)


class IssueParseError(ValueError):
    """이슈 원본에서 의미 있는 레코드를 만들 수 없을 때 발생합니다."""


class IssueParser:
    """원본 추적 정보를 유지하면서 Jira 이슈 핵심 필드를 파싱합니다."""

    def parse_file(self, source: IssueSource) -> IssueParseResult:
        """issue.json 파일을 읽고 1차 정규화 결과를 반환합니다."""

        payload = self._load_payload(source.issue_path)
        return self.parse_payload(payload, source)

    def parse_payload(
        self,
        payload: dict[str, Any],
        source: IssueSource,
    ) -> IssueParseResult:
        """이미 읽은 Jira 이슈 객체를 표준 IssueRecord로 변환합니다."""

        warnings: list[ParseWarning] = []
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise IssueParseError(
                f"이슈 fields가 객체 형식이 아닙니다: {source.issue_path}"
            )

        # 경로의 이슈 키와 JSON 내부 키를 비교하되, 불일치는 경고로만 남깁니다.
        payload_issue_key = optional_string(payload.get("key"))
        issue_key = payload_issue_key or source.issue_key
        if payload_issue_key and payload_issue_key != source.issue_key:
            warnings.append(
                ParseWarning(
                    code="issue_key_mismatch",
                    message=(
                        f"경로 이슈 키 {source.issue_key!r}와 "
                        f"JSON 이슈 키 {payload_issue_key!r}가 다릅니다."
                    ),
                    json_path="/key",
                )
            )

        payload_project_key = self._project_key(fields.get("project"))
        project_key = payload_project_key or source.project_key
        if payload_project_key and payload_project_key != source.project_key:
            warnings.append(
                ParseWarning(
                    code="project_key_mismatch",
                    message=(
                        f"경로 프로젝트 키 {source.project_key!r}와 "
                        f"JSON 프로젝트 키 {payload_project_key!r}가 다릅니다."
                    ),
                    json_path="/fields/project/key",
                )
            )

        summary = self._expected_string(
            fields.get("summary"), "/fields/summary", warnings
        )
        created_at = self._expected_string(
            fields.get("created"), "/fields/created", warnings
        )
        updated_at = self._expected_string(
            fields.get("updated"), "/fields/updated", warnings
        )

        # Raw description과 rendered description을 각각 보존하고 검색용 텍스트를 만듭니다.
        description_raw = fields.get("description")
        rendered_fields = payload.get("renderedFields")
        rendered_description_value = (
            rendered_fields.get("description")
            if isinstance(rendered_fields, dict)
            else None
        )
        description_rendered = self._expected_string(
            rendered_description_value,
            "/renderedFields/description",
            warnings,
            warn_on_none=False,
        )
        description_text, description_format = self._normalize_description(
            description_raw,
            description_rendered,
            warnings,
        )

        record = IssueRecord(
            run_id=source.run_id,
            project_key=project_key,
            issue_key=issue_key,
            jira_id=optional_string(payload.get("id")),
            summary=summary,
            description_raw=description_raw,
            description_rendered=description_rendered,
            description_text=description_text,
            description_format=description_format,
            issue_type=named_value(fields.get("issuetype")),
            status=named_value(fields.get("status")),
            priority=named_value(fields.get("priority")),
            created_at=created_at,
            updated_at=updated_at,
            source_path=str(source.issue_path),
        )
        return IssueParseResult(record=record, warnings=tuple(warnings))

    @staticmethod
    def _load_payload(path: Path) -> dict[str, Any]:
        """UTF-8 issue.json을 읽고 최상위 객체 형식을 검증합니다."""

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IssueParseError(
                f"이슈 JSON을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise IssueParseError(f"이슈 JSON 최상위 값은 객체여야 합니다: {path}")
        return payload

    @staticmethod
    def _project_key(value: Any) -> str | None:
        """Jira project 객체에서 프로젝트 키를 안전하게 추출합니다."""

        if not isinstance(value, dict):
            return None
        return optional_string(value.get("key"))

    @staticmethod
    def _expected_string(
        value: Any,
        json_path: str,
        warnings: list[ParseWarning],
        *,
        warn_on_none: bool = False,
    ) -> str | None:
        """문자열 필드를 검증하고 예상과 다른 타입은 경고로 기록합니다."""

        if value is None:
            if warn_on_none:
                warnings.append(
                    ParseWarning(
                        code="missing_value",
                        message=f"값이 없습니다: {json_path}",
                        json_path=json_path,
                    )
                )
            return None
        if isinstance(value, str):
            return value.strip() or None
        warnings.append(
            ParseWarning(
                code="unexpected_type",
                message=(
                    f"문자열이 필요한 위치 {json_path}에서 "
                    f"{value_type_name(value)} 타입을 발견했습니다."
                ),
                json_path=json_path,
            )
        )
        return None

    @staticmethod
    def _normalize_description(
        raw_value: Any,
        rendered_value: str | None,
        warnings: list[ParseWarning],
    ) -> tuple[str | None, str]:
        """description 원본 형식을 판별하고 분석용 텍스트를 생성합니다."""

        if isinstance(raw_value, str):
            if looks_like_html(raw_value):
                return html_to_text(raw_value), "html"
            normalized = raw_value.strip()
            return normalized or None, "plain_text"

        if raw_value is None:
            if rendered_value and looks_like_html(rendered_value):
                return html_to_text(rendered_value), "rendered_html"
            return rendered_value, "null"

        raw_type = value_type_name(raw_value)
        warnings.append(
            ParseWarning(
                code="unsupported_description_type",
                message=f"지원하지 않는 description 타입입니다: {raw_type}",
                json_path="/fields/description",
            )
        )
        if rendered_value:
            if looks_like_html(rendered_value):
                return html_to_text(rendered_value), f"{raw_type}_with_rendered_html"
            return rendered_value.strip() or None, f"{raw_type}_with_rendered_text"
        return None, raw_type
