from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CommentParseResult, CommentRecord, IssueSource, ParseWarning
from .value_helpers import (
    author_key_value,
    html_to_text,
    looks_like_html,
    named_value,
    optional_string,
    value_type_name,
)


class CommentParser:
    """댓글 전용 API로 저장된 page_*.json을 읽어 표준 댓글 레코드로 변환합니다."""

    def parse_issue(self, source: IssueSource) -> CommentParseResult:
        """한 이슈의 댓글 페이지를 순서대로 읽고 중복 제거와 텍스트 정규화를 수행합니다."""

        warnings: list[ParseWarning] = []
        records: list[CommentRecord] = []
        seen_comment_ids: set[str] = set()
        discovered_comment_count = 0
        duplicate_comment_count = 0
        failed_page_count = 0
        failed_comment_count = 0

        page_paths = self._page_paths(source.comments_dir)
        if not page_paths:
            warnings.append(
                ParseWarning(
                    code="comment_pages_missing",
                    message=f"댓글 페이지 파일을 찾을 수 없습니다: {source.comments_dir}",
                )
            )
            return CommentParseResult(
                records=(),
                warnings=tuple(warnings),
                missing_comment_source_count=1,
            )

        for page_path in page_paths:
            try:
                payload = self._load_page(page_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                failed_page_count += 1
                warnings.append(
                    ParseWarning(
                        code="comment_page_parse_error",
                        message=f"댓글 페이지를 읽을 수 없습니다: {page_path}: {exc}",
                        severity="error",
                    )
                )
                continue

            comments = payload.get("comments")
            if not isinstance(comments, list):
                failed_page_count += 1
                warnings.append(
                    ParseWarning(
                        code="invalid_comments_array",
                        message=f"comments 값이 배열이 아닙니다: {page_path}",
                        json_path="/comments",
                        severity="error",
                    )
                )
                continue

            for index, comment in enumerate(comments):
                discovered_comment_count += 1
                if not isinstance(comment, dict):
                    failed_comment_count += 1
                    warnings.append(
                        ParseWarning(
                            code="invalid_comment_object",
                            message=f"댓글 항목이 객체가 아닙니다: {page_path} index={index}",
                            json_path=f"/comments/{index}",
                            severity="error",
                        )
                    )
                    continue

                comment_id = optional_string(comment.get("id"))
                if comment_id is None:
                    failed_comment_count += 1
                    warnings.append(
                        ParseWarning(
                            code="missing_comment_id",
                            message=f"댓글 ID가 없어 저장하지 않습니다: {page_path} index={index}",
                            json_path=f"/comments/{index}/id",
                            severity="error",
                        )
                    )
                    continue

                if comment_id in seen_comment_ids:
                    duplicate_comment_count += 1
                    warnings.append(
                        ParseWarning(
                            code="duplicate_comment_id",
                            message=f"중복 댓글 ID를 건너뜁니다: {comment_id}",
                            json_path=f"/comments/{index}/id",
                        )
                    )
                    continue
                seen_comment_ids.add(comment_id)

                body_raw = comment.get("body")
                body_text, body_format, body_warning = self._normalize_body(
                    body_raw, page_path, index
                )
                if body_warning is not None:
                    warnings.append(body_warning)

                author = comment.get("author")
                records.append(
                    CommentRecord(
                        run_id=source.run_id,
                        project_key=source.project_key,
                        issue_key=source.issue_key,
                        comment_id=comment_id,
                        sequence=len(records) + 1,
                        author_name=named_value(author),
                        author_key=author_key_value(author),
                        created_at=optional_string(comment.get("created")),
                        updated_at=optional_string(comment.get("updated")),
                        body_raw=body_raw,
                        body_text=body_text,
                        body_format=body_format,
                        source_path=str(page_path),
                        source_page=page_path.name,
                    )
                )

        return CommentParseResult(
            records=tuple(records),
            warnings=tuple(warnings),
            page_count=len(page_paths),
            discovered_comment_count=discovered_comment_count,
            duplicate_comment_count=duplicate_comment_count,
            failed_page_count=failed_page_count,
            failed_comment_count=failed_comment_count,
        )

    @staticmethod
    def _page_paths(comments_dir: Path) -> list[Path]:
        """comments 디렉터리에서 page_*.json 파일을 안정적인 이름 순서로 반환합니다."""

        if not comments_dir.is_dir():
            return []
        return sorted(
            (path for path in comments_dir.glob("page_*.json") if path.is_file()),
            key=lambda path: path.name,
        )

    @staticmethod
    def _load_page(path: Path) -> dict[str, Any]:
        """댓글 페이지 JSON을 UTF-8로 읽고 최상위 객체 여부를 검증합니다."""

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("댓글 페이지 JSON 최상위 값은 객체여야 합니다.")
        return payload

    @staticmethod
    def _normalize_body(
        raw_value: Any,
        page_path: Path,
        index: int,
    ) -> tuple[str | None, str, ParseWarning | None]:
        """댓글 body를 HTML·일반 문자열·기타 타입으로 분류하고 검색용 텍스트를 생성합니다."""

        if isinstance(raw_value, str):
            if looks_like_html(raw_value):
                return html_to_text(raw_value), "html", None
            normalized = raw_value.strip()
            return normalized or None, "plain_text", None
        if raw_value is None:
            return None, "null", None

        raw_type = value_type_name(raw_value)
        return (
            None,
            raw_type,
            ParseWarning(
                code="unsupported_comment_body_type",
                message=(
                    f"지원하지 않는 댓글 body 타입입니다: {raw_type} "
                    f"file={page_path} index={index}"
                ),
                json_path=f"/comments/{index}/body",
            ),
        )
