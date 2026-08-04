from __future__ import annotations

import json
from pathlib import Path

from jira_collector.parser import CommentParser, IssueSource


def _source(tmp_path: Path, issue_key: str = "ABC-1") -> IssueSource:
    """테스트용 이슈와 댓글 디렉터리를 실제 저장 구조와 동일하게 만듭니다."""

    issue_dir = tmp_path / "projects" / "ABC" / "issues" / issue_key
    issue_dir.mkdir(parents=True)
    comments_dir = issue_dir / "comments"
    comments_dir.mkdir()
    return IssueSource(
        run_id="run1",
        project_key="ABC",
        issue_key=issue_key,
        issue_path=issue_dir / "issue.json",
        comments_dir=comments_dir,
    )


def _write_page(
    comments_dir: Path,
    page_number: int,
    payload: object,
) -> Path:
    """민감정보가 없는 가짜 댓글 페이지를 지정한 번호로 저장합니다."""

    path = comments_dir / f"page_{page_number:04d}.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return path


def test_parses_html_author_and_multiple_pages(tmp_path: Path) -> None:
    """HTML 댓글과 작성자 정보를 추출하고 페이지 순서대로 sequence를 부여하는지 확인합니다."""

    source = _source(tmp_path)
    _write_page(
        source.comments_dir,
        1,
        {
            "startAt": 0,
            "maxResults": 2,
            "total": 3,
            "comments": [
                {
                    "id": "1",
                    "body": '<p dir="auto">첫 댓글 <b>강조</b></p>',
                    "author": {
                        "displayName": "Example User",
                        "name": "example.user",
                        "emailAddress": "not-exported@example.com",
                        "avatarUrls": {"48x48": "https://example.invalid/a"},
                    },
                    "created": "2026-08-01T10:00:00.000+0900",
                    "updated": "2026-08-01T11:00:00.000+0900",
                },
                {
                    "id": "2",
                    "body": "일반 텍스트 댓글",
                    "author": {"name": "fallback.user"},
                },
            ],
        },
    )
    _write_page(
        source.comments_dir,
        2,
        {
            "startAt": 2,
            "maxResults": 2,
            "total": 3,
            "comments": [
                {
                    "id": "3",
                    "body": "<p>마지막 댓글</p>",
                    "author": {"displayName": "Other User", "key": "other"},
                }
            ],
        },
    )

    result = CommentParser().parse_issue(source)

    assert result.page_count == 2
    assert result.discovered_comment_count == 3
    assert result.duplicate_comment_count == 0
    assert [record.comment_id for record in result.records] == ["1", "2", "3"]
    assert [record.sequence for record in result.records] == [1, 2, 3]
    assert result.records[0].body_text == "첫 댓글 강조"
    assert result.records[0].body_format == "html"
    assert result.records[0].author_name == "Example User"
    assert result.records[0].author_key == "example.user"
    assert result.records[1].author_name == "fallback.user"
    assert result.warnings == ()


def test_deduplicates_comment_id_and_keeps_first_value(tmp_path: Path) -> None:
    """같은 comment.id가 여러 페이지에 있으면 첫 댓글만 남기고 경고하는지 확인합니다."""

    source = _source(tmp_path)
    _write_page(
        source.comments_dir,
        1,
        {"comments": [{"id": "1", "body": "first"}]},
    )
    _write_page(
        source.comments_dir,
        2,
        {"comments": [{"id": "1", "body": "duplicate"}]},
    )

    result = CommentParser().parse_issue(source)

    assert len(result.records) == 1
    assert result.records[0].body_text == "first"
    assert result.duplicate_comment_count == 1
    assert [warning.code for warning in result.warnings] == [
        "duplicate_comment_id"
    ]


def test_accepts_empty_comment_page(tmp_path: Path) -> None:
    """댓글이 0개인 빈 첫 페이지를 정상 수집 완료 결과로 처리하는지 확인합니다."""

    source = _source(tmp_path)
    _write_page(
        source.comments_dir,
        1,
        {
            "startAt": 0,
            "maxResults": 100,
            "total": 0,
            "comments": [],
        },
    )

    result = CommentParser().parse_issue(source)

    assert result.page_count == 1
    assert result.discovered_comment_count == 0
    assert result.records == ()
    assert result.warnings == ()


def test_isolates_broken_page_and_missing_comment_id(tmp_path: Path) -> None:
    """깨진 페이지와 ID 없는 댓글을 오류로 기록하고 다른 페이지 처리를 계속하는지 확인합니다."""

    source = _source(tmp_path)
    _write_page(source.comments_dir, 1, "{not-json")
    _write_page(
        source.comments_dir,
        2,
        {
            "comments": [
                {"body": "ID 없음"},
                {"id": "2", "body": "정상 댓글"},
            ]
        },
    )

    result = CommentParser().parse_issue(source)

    assert result.page_count == 2
    assert result.failed_page_count == 1
    assert result.failed_comment_count == 1
    assert [record.comment_id for record in result.records] == ["2"]
    assert [warning.code for warning in result.warnings] == [
        "comment_page_parse_error",
        "missing_comment_id",
    ]
    assert all(warning.severity == "error" for warning in result.warnings)


def test_reports_missing_comment_source(tmp_path: Path) -> None:
    """comments 디렉터리나 페이지가 없을 때 누락 상태를 명시하는지 확인합니다."""

    source = _source(tmp_path)
    source.comments_dir.rmdir()

    result = CommentParser().parse_issue(source)

    assert result.missing_comment_source_count == 1
    assert result.records == ()
    assert [warning.code for warning in result.warnings] == [
        "comment_pages_missing"
    ]
