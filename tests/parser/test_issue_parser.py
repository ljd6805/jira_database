from __future__ import annotations

import json
from pathlib import Path

from jira_collector.parser import IssueParser, IssueSource
from jira_collector.parser.value_helpers import html_to_text


def _source(tmp_path: Path, *, issue_key: str = "ABC-1") -> IssueSource:
    issue_dir = tmp_path / "projects" / "ABC" / "issues" / issue_key
    issue_dir.mkdir(parents=True)
    return IssueSource(
        run_id="run1",
        project_key="ABC",
        issue_key=issue_key,
        issue_path=issue_dir / "issue.json",
        comments_dir=issue_dir / "comments",
    )


def test_html_to_text_removes_style_and_keeps_blocks() -> None:
    value = (
        '<p dir="auto">First <span style="color:red">warning</span></p>'
        "<ul><li>One</li><li>Two</li></ul>"
        "<style>.secret { display:none; }</style>"
    )

    assert html_to_text(value) == "First warning\n- One\n- Two"


def test_parses_core_issue_fields_and_html_description(tmp_path: Path) -> None:
    source = _source(tmp_path)
    payload = {
        "id": "10001",
        "key": "ABC-1",
        "fields": {
            "project": {"key": "ABC", "name": "Alpha"},
            "summary": "Example issue",
            "description": (
                '<p dir="auto">Boot <span style="color:red">failed</span>.</p>'
            ),
            "issuetype": {"name": "Bug"},
            "status": {"name": "Open"},
            "priority": {"name": "Major"},
            "created": "2026-08-01T09:00:00.000+0900",
            "updated": "2026-08-04T18:00:00.000+0900",
        },
        "renderedFields": {
            "description": '<p dir="auto">Boot <strong>failed</strong>.</p>'
        },
    }
    source.issue_path.write_text(json.dumps(payload), encoding="utf-8")

    result = IssueParser().parse_file(source)

    assert result.warnings == ()
    assert result.record.issue_key == "ABC-1"
    assert result.record.project_key == "ABC"
    assert result.record.jira_id == "10001"
    assert result.record.summary == "Example issue"
    assert result.record.description_format == "html"
    assert result.record.description_text == "Boot failed."
    assert result.record.description_raw == payload["fields"]["description"]
    assert result.record.description_rendered == payload["renderedFields"]["description"]
    assert result.record.issue_type == "Bug"
    assert result.record.status == "Open"
    assert result.record.priority == "Major"


def test_uses_rendered_description_when_raw_is_object(tmp_path: Path) -> None:
    source = _source(tmp_path)
    payload = {
        "key": "ABC-1",
        "fields": {
            "project": {"key": "ABC"},
            "description": {"type": "doc", "content": []},
        },
        "renderedFields": {"description": "<p>Rendered body</p>"},
    }
    source.issue_path.write_text(json.dumps(payload), encoding="utf-8")

    result = IssueParser().parse_file(source)

    assert result.record.description_text == "Rendered body"
    assert result.record.description_format == "object_with_rendered_html"
    assert [warning.code for warning in result.warnings] == [
        "unsupported_description_type"
    ]


def test_reports_path_and_payload_key_mismatch(tmp_path: Path) -> None:
    source = _source(tmp_path, issue_key="ABC-1")
    payload = {
        "key": "ABC-2",
        "fields": {"project": {"key": "XYZ"}, "summary": "Mismatch"},
    }
    source.issue_path.write_text(json.dumps(payload), encoding="utf-8")

    result = IssueParser().parse_file(source)

    assert result.record.issue_key == "ABC-2"
    assert result.record.project_key == "XYZ"
    assert [warning.code for warning in result.warnings] == [
        "issue_key_mismatch",
        "project_key_mismatch",
    ]
