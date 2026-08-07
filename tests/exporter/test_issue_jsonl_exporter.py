from __future__ import annotations

import json
from pathlib import Path

from jira_collector.exporter import IssueJsonlExporter
from jira_collector.parser import IssueParser, RunReader


def _write_issue(
    data_root: Path,
    *,
    run_id: str,
    project_key: str,
    issue_key: str,
    payload: object,
) -> Path:
    """테스트용 Jira 이슈 원본 파일을 실제 저장 계약과 같은 경로에 만듭니다."""

    issue_path = (
        data_root
        / "raw"
        / "runs"
        / run_id
        / "projects"
        / project_key
        / "issues"
        / issue_key
        / "issue.json"
    )
    issue_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        issue_path.write_text(payload, encoding="utf-8")
    else:
        issue_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return issue_path


def _valid_payload(issue_key: str) -> dict[str, object]:
    """민감정보가 없는 가짜 Jira 이슈 응답을 생성합니다."""

    return {
        "id": "10001",
        "key": issue_key,
        "fields": {
            "project": {"key": "ABC"},
            "summary": "Example summary",
            "description": (
                '<p dir="auto">첫 문단 <span style="color:red">강조</span></p>'
                "<ul><li>항목 하나</li></ul>"
            ),
            "issuetype": {"name": "Bug"},
            "status": {"name": "Open"},
            "priority": {"name": "Major"},
            "created": "2026-08-01T10:00:00.000+0900",
            "updated": "2026-08-02T11:00:00.000+0900",
        },
        "renderedFields": {
            "description": '<p dir="auto">렌더링 본문</p>',
        },
    }


def test_export_run_writes_jsonl_warnings_and_summary(tmp_path: Path) -> None:
    """정상 이슈와 파싱 실패 이슈를 분리해 공통 출력 계약으로 저장하는지 확인합니다."""

    data_root = tmp_path / "data"
    _write_issue(
        data_root,
        run_id="run1",
        project_key="ABC",
        issue_key="ABC-1",
        payload=_valid_payload("ABC-1"),
    )
    _write_issue(
        data_root,
        run_id="run1",
        project_key="ABC",
        issue_key="ABC-2",
        payload="{not-json",
    )

    result = IssueJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        IssueParser(),
    )

    issue_lines = result.issues_path.read_text(encoding="utf-8").splitlines()
    warning_lines = result.warnings_path.read_text(encoding="utf-8").splitlines()
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))

    assert result.discovered_issue_count == 2
    assert result.exported_issue_count == 1
    assert result.failed_issue_count == 1
    assert result.parse_error_count == 1
    assert len(issue_lines) == 1
    assert len(warning_lines) == 1

    issue = json.loads(issue_lines[0])
    assert issue["issue_key"] == "ABC-1"
    assert issue["description_format"] == "html"
    assert issue["description_text"] == "첫 문단 강조\n- 항목 하나"
    assert "description_raw" not in issue
    assert "description_rendered" not in issue

    warning = json.loads(warning_lines[0])
    assert warning["component"] == "issues"
    assert warning["severity"] == "error"
    assert warning["code"] == "issue_parse_error"
    assert warning["issue_key"] == "ABC-2"

    assert summary["schema_version"] == "2.0"
    assert summary["status"] == "partial"
    assert summary["issues"]["status"] == "partial"
    assert summary["issues"]["discovered_count"] == 2
    assert summary["issues"]["exported_count"] == 1
    assert summary["issues"]["failed_count"] == 1
    assert summary["issues"]["description_formats"] == {"html": 1}
    assert summary["comments"]["status"] == "not_run"
    assert summary["output_files"]["issues"] == "analysis/run1/issues.jsonl"


def test_export_run_creates_empty_warning_file_when_no_warnings(
    tmp_path: Path,
) -> None:
    """경고가 없을 때도 빈 parse_warnings.jsonl을 생성하는지 확인합니다."""

    data_root = tmp_path / "data"
    _write_issue(
        data_root,
        run_id="run1",
        project_key="ABC",
        issue_key="ABC-1",
        payload=_valid_payload("ABC-1"),
    )

    result = IssueJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        IssueParser(),
    )

    assert result.exported_issue_count == 1
    assert result.failed_issue_count == 0
    assert result.warning_count == 0
    assert result.warnings_path.read_text(encoding="utf-8") == ""

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "incomplete"
    assert summary["issues"]["status"] == "completed"
    assert summary["issues"]["warning_count"] == 0
    assert summary["issues"]["parse_error_count"] == 0
    assert summary["comments"]["status"] == "not_run"
