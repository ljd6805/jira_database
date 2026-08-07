from __future__ import annotations

import json
from pathlib import Path

from jira_collector.exporter import IssueStructureJsonlExporter
from jira_collector.parser import IssueStructureParser, RunReader


def _write_issue(data_root: Path, payload: dict[str, object]) -> None:
    """실제 RAW 저장 계약과 같은 위치에 구조 데이터 fixture를 기록합니다."""

    path = (
        data_root
        / "raw"
        / "runs"
        / "run1"
        / "projects"
        / "ABC"
        / "issues"
        / "ABC-1"
        / "issue.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _payload() -> dict[str, object]:
    """한 이슈에서 네 구조 출력 파일을 모두 만들 수 있는 최소 Jira 응답을 생성합니다."""

    return {
        "id": "10001",
        "key": "ABC-1",
        "names": {
            "customfield_16603": "Select Field",
            "customfield_10015": "Multi User",
        },
        "schema": {
            "customfield_16603": {
                "type": "option",
                "custom": "com.atlassian.jira.plugin.system.customfieldtypes:select",
            },
            "customfield_10015": {
                "type": "array",
                "items": "user",
                "custom": "com.atlassian.jira.plugin.system.customfieldtypes:multiuserpicker",
            },
        },
        "fields": {
            "summary": "Parent",
            "status": {"name": "Open"},
            "attachment": [
                {
                    "id": "A1",
                    "filename": "example.log",
                    "author": {
                        "displayName": "Example User",
                        "name": "example",
                    },
                    "created": "2026-08-01T10:00:00.000+0900",
                    "size": 42,
                    "mimeType": "text/plain",
                    "content": "https://jira.example/A1",
                }
            ],
            "issuelinks": [
                {
                    "id": "L1",
                    "type": {
                        "name": "Blocks",
                        "inward": "is blocked by",
                        "outward": "blocks",
                    },
                    "outwardIssue": {
                        "key": "ABC-2",
                        "fields": {
                            "summary": "Target",
                            "status": {"name": "Open"},
                        },
                    },
                }
            ],
            "subtasks": [
                {
                    "key": "ABC-3",
                    "fields": {
                        "summary": "Child",
                        "status": {"name": "To Do"},
                    },
                }
            ],
            "customfield_16603": {
                "value": "EVT",
                "id": "1",
                "disabled": False,
            },
            "customfield_10015": [
                {
                    "name": "example",
                    "key": "example",
                    "displayName": "Example User",
                    "emailAddress": "private@example.com",
                }
            ],
        },
    }


def test_export_structure_writes_four_jsonl_files_and_summary(tmp_path: Path) -> None:
    """한 번의 RAW 순회로 Attachment·관계·Catalog·Value JSONL과 공통 요약을 생성합니다."""

    data_root = tmp_path / "data"
    _write_issue(data_root, _payload())

    result = IssueStructureJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        IssueStructureParser(),
    )

    assert result.issue_count == 1
    assert result.exported_attachment_count == 1
    assert result.exported_relationship_count == 2
    assert result.custom_field_catalog_count == 2
    assert result.used_custom_field_count == 2
    assert result.exported_custom_field_value_count == 2
    assert result.warning_count == 0

    attachments = result.attachments_path.read_text(encoding="utf-8").splitlines()
    relationships = result.relationships_path.read_text(encoding="utf-8").splitlines()
    catalog = result.custom_field_catalog_path.read_text(encoding="utf-8").splitlines()
    values = result.custom_field_values_path.read_text(encoding="utf-8").splitlines()

    assert len(attachments) == 1
    assert len(relationships) == 2
    assert len(catalog) == 2
    assert len(values) == 2
    assert "private@example.com" not in result.custom_field_values_path.read_text(
        encoding="utf-8"
    )

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["attachments"]["status"] == "completed"
    assert summary["relationships"]["issue_link_count"] == 1
    assert summary["relationships"]["hierarchy_count"] == 1
    assert summary["custom_fields"]["catalog_count"] == 2
    assert summary["custom_fields"]["exported_value_count"] == 2
