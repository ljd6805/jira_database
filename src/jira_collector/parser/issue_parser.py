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
    """Raised when an issue artifact cannot produce a meaningful record."""


class IssueParser:
    """Parse first-stage issue fields while preserving source traceability."""

    def parse_file(self, source: IssueSource) -> IssueParseResult:
        payload = self._load_payload(source.issue_path)
        return self.parse_payload(payload, source)

    def parse_payload(
        self,
        payload: dict[str, Any],
        source: IssueSource,
    ) -> IssueParseResult:
        warnings: list[ParseWarning] = []
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise IssueParseError(
                f"issue fields must be an object: {source.issue_path}"
            )

        payload_issue_key = optional_string(payload.get("key"))
        issue_key = payload_issue_key or source.issue_key
        if payload_issue_key and payload_issue_key != source.issue_key:
            warnings.append(
                ParseWarning(
                    code="issue_key_mismatch",
                    message=(
                        f"path issue key {source.issue_key!r} differs from "
                        f"payload key {payload_issue_key!r}"
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
                        f"path project key {source.project_key!r} differs from "
                        f"payload project key {payload_project_key!r}"
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
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IssueParseError(f"cannot read issue JSON: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise IssueParseError(f"issue JSON root must be an object: {path}")
        return payload

    @staticmethod
    def _project_key(value: Any) -> str | None:
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
        if value is None:
            if warn_on_none:
                warnings.append(
                    ParseWarning(
                        code="missing_value",
                        message=f"missing value at {json_path}",
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
                    f"expected string at {json_path}, "
                    f"observed {value_type_name(value)}"
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
                message=f"description has unsupported type: {raw_type}",
                json_path="/fields/description",
            )
        )
        if rendered_value:
            if looks_like_html(rendered_value):
                return html_to_text(rendered_value), f"{raw_type}_with_rendered_html"
            return rendered_value.strip() or None, f"{raw_type}_with_rendered_text"
        return None, raw_type
