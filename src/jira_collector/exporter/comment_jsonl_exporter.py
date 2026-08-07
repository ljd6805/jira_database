from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jira_collector.parser import CommentParser, RunReader
from jira_collector.parser.models import CommentRecord, IssueSource, ParseWarning

from .atomic_writer import AtomicTextWriter
from .models import CommentExportResult
from .run_summary_store import RunSummaryStore
from .run_warning_store import RunWarningStore


class CommentJsonlExporter:
    """댓글 전용 API 원본을 파싱해 comments.jsonl과 공통 실행 요약으로 내보냅니다."""

    PARSER_VERSION = "0.1"

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
    ) -> None:
        """분석 저장 루트와 공통 요약·경고 저장소를 초기화합니다."""

        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        self.writer = AtomicTextWriter(self.analysis_root)
        self.summary_store = RunSummaryStore(
            self.data_root,
            analysis_directory,
        )
        self.warning_store = RunWarningStore(
            self.data_root,
            analysis_directory,
        )

    def export_run(
        self,
        run_id: str,
        reader: RunReader,
        parser: CommentParser,
    ) -> CommentExportResult:
        """run_id의 모든 댓글 페이지를 병합·중복 제거해 JSONL과 통계로 저장합니다."""

        sources = reader.list_issue_sources(run_id)
        comments_relative = Path(run_id) / "comments.jsonl"
        comments_path = (self.analysis_root / comments_relative).resolve()
        warning_documents: list[dict[str, Any]] = []
        page_count = 0
        discovered_count = 0
        exported_count = 0
        duplicate_count = 0
        failed_page_count = 0
        failed_comment_count = 0
        missing_source_count = 0
        body_formats: Counter[str] = Counter()

        # 댓글은 이슈 단위로 파싱하되 출력은 한 줄씩 기록해 전체 본문을 메모리에 쌓지 않습니다.
        with self.writer.open_text(comments_relative) as handle:
            for source in sources:
                result = parser.parse_issue(source)
                page_count += result.page_count
                discovered_count += result.discovered_comment_count
                duplicate_count += result.duplicate_comment_count
                failed_page_count += result.failed_page_count
                failed_comment_count += result.failed_comment_count
                missing_source_count += result.missing_comment_source_count

                for record in result.records:
                    handle.write(
                        json.dumps(
                            self._comment_document(record),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    handle.write("\n")
                    exported_count += 1
                    body_formats[record.body_format] += 1

                for warning in result.warnings:
                    warning_documents.append(
                        self._warning_document(source, warning)
                    )

        warnings_path = self.warning_store.replace_component(
            run_id,
            "comments",
            warning_documents,
        )
        comment_status = (
            "partial"
            if failed_page_count
            or failed_comment_count
            or missing_source_count
            else "completed"
        )
        summary_path = self.summary_store.update_section(
            run_id,
            "comments",
            {
                "status": comment_status,
                "parser_version": self.PARSER_VERSION,
                "issue_count": len(sources),
                "page_count": page_count,
                "discovered_count": discovered_count,
                "exported_count": exported_count,
                "duplicate_count": duplicate_count,
                "failed_page_count": failed_page_count,
                "failed_comment_count": failed_comment_count,
                "missing_comment_source_count": missing_source_count,
                "warning_count": len(warning_documents),
                "body_formats": dict(sorted(body_formats.items())),
            },
            {
                "comments": self._relative_to_data_root(comments_path),
                "warnings": self._relative_to_data_root(warnings_path),
                "summary": self._relative_to_data_root(
                    self.analysis_root / run_id / "summary.json"
                ),
            },
        )
        return CommentExportResult(
            run_id=run_id,
            issue_count=len(sources),
            page_count=page_count,
            discovered_comment_count=discovered_count,
            exported_comment_count=exported_count,
            duplicate_comment_count=duplicate_count,
            failed_page_count=failed_page_count,
            failed_comment_count=failed_comment_count,
            missing_comment_source_count=missing_source_count,
            warning_count=len(warning_documents),
            comments_path=comments_path,
            warnings_path=warnings_path,
            summary_path=summary_path,
        )

    @staticmethod
    def _comment_document(record: CommentRecord) -> dict[str, Any]:
        """CommentRecord에서 분석 저장 계약에 포함되는 필드만 선택합니다."""

        return {
            "run_id": record.run_id,
            "project_key": record.project_key,
            "issue_key": record.issue_key,
            "comment_id": record.comment_id,
            "sequence": record.sequence,
            "author_name": record.author_name,
            "author_key": record.author_key,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "body_text": record.body_text,
            "body_format": record.body_format,
            "source_path": record.source_path,
            "source_page": record.source_page,
        }

    @staticmethod
    def _warning_document(
        source: IssueSource,
        warning: ParseWarning,
    ) -> dict[str, Any]:
        """댓글 ParseWarning을 원본 추적 가능한 공통 경고 문서로 변환합니다."""

        return {
            "severity": warning.severity,
            "run_id": source.run_id,
            "project_key": source.project_key,
            "issue_key": source.issue_key,
            "code": warning.code,
            "message": warning.message,
            "json_path": warning.json_path,
            "source_path": str(source.comments_dir),
        }

    def _relative_to_data_root(self, path: Path) -> str:
        """절대 경로를 data_root 기준의 POSIX 상대 경로로 변환합니다."""

        return path.resolve().relative_to(self.data_root).as_posix()
