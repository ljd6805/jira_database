from __future__ import annotations

import json
from pathlib import Path

from jira_collector.exporter import CommentJsonlExporter, IssueJsonlExporter
from jira_collector.parser import CommentParser, IssueParser, RunReader


def _issue_dir(
    data_root: Path,
    *,
    run_id: str = "run1",
    project_key: str = "ABC",
    issue_key: str = "ABC-1",
) -> Path:
    """실제 수집 저장 계약과 같은 테스트 이슈 디렉터리를 만듭니다."""

    issue_dir = (
        data_root
        / "raw"
        / "runs"
        / run_id
        / "projects"
        / project_key
        / "issues"
        / issue_key
    )
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "issue.json").write_text(
        json.dumps(
            {
                "id": "10001",
                "key": issue_key,
                "fields": {
                    "project": {"key": project_key},
                    "summary": "Example issue",
                    "description": "<p>설명</p>",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (issue_dir / "comments").mkdir()
    return issue_dir


def _write_comment_page(
    issue_dir: Path,
    page_number: int,
    payload: object,
) -> None:
    """가짜 댓글 페이지를 comments/page_*.json 경로에 저장합니다."""

    path = issue_dir / "comments" / f"page_{page_number:04d}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_exports_comments_without_private_author_fields(tmp_path: Path) -> None:
    """댓글 텍스트와 필요한 작성자 값만 저장하고 이메일·아바타를 제외하는지 확인합니다."""

    data_root = tmp_path / "data"
    issue_dir = _issue_dir(data_root)
    _write_comment_page(
        issue_dir,
        1,
        {
            "startAt": 0,
            "maxResults": 100,
            "total": 1,
            "comments": [
                {
                    "id": "1",
                    "body": '<p dir="auto">댓글 <span style="color:red">본문</span></p>',
                    "author": {
                        "displayName": "Example User",
                        "name": "example.user",
                        "emailAddress": "not-exported@example.com",
                        "avatarUrls": {"48x48": "https://example.invalid/a"},
                    },
                    "created": "2026-08-01T10:00:00.000+0900",
                    "updated": "2026-08-01T11:00:00.000+0900",
                }
            ],
        },
    )

    result = CommentJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        CommentParser(),
    )

    lines = result.comments_path.read_text(encoding="utf-8").splitlines()
    assert result.issue_count == 1
    assert result.page_count == 1
    assert result.exported_comment_count == 1
    assert len(lines) == 1

    comment = json.loads(lines[0])
    assert comment["comment_id"] == "1"
    assert comment["sequence"] == 1
    assert comment["body_text"] == "댓글 본문"
    assert comment["body_format"] == "html"
    assert comment["author_name"] == "Example User"
    assert comment["author_key"] == "example.user"
    assert "body_raw" not in comment
    assert "emailAddress" not in comment
    assert "avatarUrls" not in comment


def test_migrates_v1_summary_and_preserves_issue_statistics(
    tmp_path: Path,
) -> None:
    """기존 Issue Exporter 1.0 요약을 2.0으로 변환하고 댓글 통계를 추가하는지 확인합니다."""

    data_root = tmp_path / "data"
    issue_dir = _issue_dir(data_root)
    _write_comment_page(
        issue_dir,
        1,
        {"comments": [{"id": "1", "body": "<p>댓글</p>"}]},
    )
    analysis_dir = data_root / "analysis" / "run1"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "parser_version": "0.1",
                "run_id": "run1",
                "generated_at": "2026-08-04T00:00:00Z",
                "status": "completed",
                "discovered_issue_count": 1,
                "exported_issue_count": 1,
                "failed_issue_count": 0,
                "warning_count": 0,
                "parse_error_count": 0,
                "description_formats": {"html": 1},
                "output_files": {
                    "issues": "analysis/run1/issues.jsonl",
                    "warnings": "analysis/run1/parse_warnings.jsonl",
                    "summary": "analysis/run1/summary.json",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CommentJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        CommentParser(),
    )
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))

    assert summary["schema_version"] == "2.0"
    assert summary["status"] == "completed"
    assert summary["issues"]["exported_count"] == 1
    assert summary["issues"]["description_formats"] == {"html": 1}
    assert summary["comments"]["exported_count"] == 1
    assert summary["output_files"]["issues"] == "analysis/run1/issues.jsonl"
    assert summary["output_files"]["comments"] == "analysis/run1/comments.jsonl"


def test_issue_and_comment_export_order_does_not_remove_other_results(
    tmp_path: Path,
) -> None:
    """두 Exporter를 어떤 순서로 재실행해도 다른 영역의 요약과 경고를 보존하는지 확인합니다."""

    data_root = tmp_path / "data"
    issue_dir = _issue_dir(data_root)
    _write_comment_page(
        issue_dir,
        1,
        {"comments": [{"id": "1", "body": "<p>댓글</p>"}]},
    )
    reader = RunReader(data_root)

    CommentJsonlExporter(data_root).export_run(
        "run1",
        reader,
        CommentParser(),
    )
    IssueJsonlExporter(data_root).export_run(
        "run1",
        reader,
        IssueParser(),
    )
    summary = json.loads(
        (data_root / "analysis" / "run1" / "summary.json").read_text(
            encoding="utf-8"
        )
    )

    assert summary["status"] == "completed"
    assert summary["issues"]["exported_count"] == 1
    assert summary["comments"]["exported_count"] == 1


def test_broken_comment_page_creates_partial_summary(tmp_path: Path) -> None:
    """댓글 페이지 오류가 다른 이슈 처리를 막지 않고 partial 상태로 기록되는지 확인합니다."""

    data_root = tmp_path / "data"
    issue_dir = _issue_dir(data_root)
    broken_path = issue_dir / "comments" / "page_0001.json"
    broken_path.write_text("{not-json", encoding="utf-8")

    result = CommentJsonlExporter(data_root).export_run(
        "run1",
        RunReader(data_root),
        CommentParser(),
    )
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    warning = json.loads(
        result.warnings_path.read_text(encoding="utf-8").splitlines()[0]
    )

    assert result.failed_page_count == 1
    assert summary["comments"]["status"] == "partial"
    assert summary["status"] == "partial"
    assert warning["component"] == "comments"
    assert warning["severity"] == "error"
    assert warning["code"] == "comment_page_parse_error"
