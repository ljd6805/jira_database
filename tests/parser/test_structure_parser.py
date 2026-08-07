from __future__ import annotations

from pathlib import Path

from jira_collector.parser import IssueSource, IssueStructureParser


def _source(tmp_path: Path) -> IssueSource:
    """실제 RAW 저장 계약과 같은 경로 정보를 가진 테스트 source를 생성합니다."""

    issue_path = tmp_path / "issue.json"
    return IssueSource(
        run_id="run1",
        project_key="ABC",
        issue_key="ABC-1",
        issue_path=issue_path,
        comments_dir=tmp_path / "comments",
    )


def _payload() -> dict[str, object]:
    """실환경에서 확인한 Attachment·Link·Subtask·Custom Field 형태를 최소 fixture로 만듭니다."""

    return {
        "id": "10001",
        "key": "ABC-1",
        "names": {
            "customfield_16603": "Select Field",
            "customfield_10015": "Multi User",
            "customfield_16608": "Scripted Field",
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
            "customfield_16608": {
                "type": "string",
                "custom": "com.onresolve.jira.groovy.groovyrunner:scripted-field",
            },
        },
        "fields": {
            "summary": "Parent issue",
            "status": {"name": "Open"},
            "attachment": [
                {
                    "id": "A1",
                    "filename": "example.log",
                    "author": {
                        "displayName": "Example User",
                        "name": "example",
                        "emailAddress": "private@example.com",
                    },
                    "created": "2026-08-01T10:00:00.000+0900",
                    "size": 1234,
                    "mimeType": "text/plain",
                    "content": "https://jira.example/attachment/A1",
                    "thumbnail": None,
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
                },
                {
                    "id": "L2",
                    "type": {
                        "name": "Blocks",
                        "inward": "is blocked by",
                        "outward": "blocks",
                    },
                    "inwardIssue": {
                        "key": "XYZ-3",
                        "fields": {
                            "summary": "Source",
                            "status": {"name": "Done"},
                        },
                    },
                },
            ],
            "subtasks": [
                {
                    "key": "ABC-4",
                    "fields": {
                        "summary": "Child",
                        "status": {"name": "To Do"},
                    },
                }
            ],
            "customfield_16603": {
                "self": "https://jira.example/option/1",
                "value": "EVT",
                "id": "1",
                "disabled": False,
            },
            "customfield_10015": [
                {
                    "self": "https://jira.example/user/1",
                    "name": "example",
                    "key": "example",
                    "emailAddress": "private@example.com",
                    "avatarUrls": {},
                    "displayName": "Example User",
                    "active": True,
                    "timeZone": "Asia/Seoul",
                }
            ],
            "customfield_16608": "script result",
        },
    }


def test_structure_parser_normalizes_verified_shapes(tmp_path: Path) -> None:
    """실환경에서 확인된 구조를 Attachment·canonical 관계·Custom Field 레코드로 변환합니다."""

    result = IssueStructureParser().parse_payload(_payload(), _source(tmp_path))

    assert len(result.attachments) == 1
    assert result.attachments[0].attachment_id == "A1"
    assert result.attachments[0].author_name == "Example User"

    links = {item.relationship_id: item for item in result.relationships}
    assert links["L1"].source_issue_key == "ABC-1"
    assert links["L1"].target_issue_key == "ABC-2"
    assert links["L2"].source_issue_key == "XYZ-3"
    assert links["L2"].target_issue_key == "ABC-1"
    assert links["hierarchy:ABC-1:ABC-4"].relationship_type == "parent_of"

    values = {item.field_id: item for item in result.custom_field_values}
    assert values["customfield_16603"].value_kind == "option"
    assert values["customfield_16603"].display_value == "EVT"
    assert values["customfield_10015"].value_kind == "user_array"
    assert values["customfield_10015"].display_values == ("Example User",)
    assert values["customfield_10015"].user_keys == ("example",)
    assert "private@example.com" not in repr(values["customfield_10015"])
