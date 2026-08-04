from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jira_collector.parser import IssueParseError, IssueParser, RunReader
from jira_collector.parser.models import IssueRecord, IssueSource, ParseWarning

from .atomic_writer import AtomicTextWriter
from .models import IssueExportResult


class IssueJsonlExporter:
    """수집된 Jira 이슈를 파싱해 분석용 JSONL 파일 묶음으로 내보냅니다."""

    SCHEMA_VERSION = "1.0"
    PARSER_VERSION = "0.1"

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
    ) -> None:
        """데이터 루트 아래의 분석 출력 디렉터리를 초기화합니다."""

        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        if (
            self.analysis_root != self.data_root
            and self.data_root not in self.analysis_root.parents
        ):
            raise ValueError(
                f"analysis 디렉터리는 data_root 아래에 있어야 합니다: {self.analysis_root}"
            )
        self.writer = AtomicTextWriter(self.analysis_root)

    def export_run(
        self,
        run_id: str,
        reader: RunReader,
        parser: IssueParser,
    ) -> IssueExportResult:
        """run_id의 모든 이슈를 파싱하고 JSONL·경고·요약 파일을 생성합니다."""

        sources = reader.list_issue_sources(run_id)
        run_relative = Path(run_id)
        issues_relative = run_relative / "issues.jsonl"
        warnings_relative = run_relative / "parse_warnings.jsonl"
        summary_relative = run_relative / "summary.json"

        exported_issue_count = 0
        failed_issue_count = 0
        parse_error_count = 0
        warning_documents: list[dict[str, Any]] = []
        description_formats: Counter[str] = Counter()

        # 이슈 데이터는 한 줄씩 기록해 전체 본문을 메모리에 쌓지 않습니다.
        with self.writer.open_text(issues_relative) as issues_handle:
            for source in sources:
                try:
                    result = parser.parse_file(source)
                except IssueParseError as exc:
                    failed_issue_count += 1
                    parse_error_count += 1
                    warning_documents.append(
                        self._parse_error_document(source, exc)
                    )
                    continue

                issues_handle.write(
                    json.dumps(
                        self._issue_document(result.record),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                issues_handle.write("\n")
                exported_issue_count += 1
                description_formats[result.record.description_format] += 1

                for warning in result.warnings:
                    warning_documents.append(
                        self._warning_document(source, warning)
                    )

        # 경고가 없더라도 0바이트 파일을 생성해 경고 검사가 완료됐음을 명시합니다.
        with self.writer.open_text(warnings_relative) as warnings_handle:
            for document in warning_documents:
                warnings_handle.write(
                    json.dumps(
                        document,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                warnings_handle.write("\n")

        issues_path = (self.analysis_root / issues_relative).resolve()
        warnings_path = (self.analysis_root / warnings_relative).resolve()
        summary_path = (self.analysis_root / summary_relative).resolve()
        summary_document = {
            "schema_version": self.SCHEMA_VERSION,
            "parser_version": self.PARSER_VERSION,
            "run_id": run_id,
            "generated_at": self._utc_now_text(),
            "status": "completed" if failed_issue_count == 0 else "partial",
            "discovered_issue_count": len(sources),
            "exported_issue_count": exported_issue_count,
            "failed_issue_count": failed_issue_count,
            "warning_count": len(warning_documents),
            "parse_error_count": parse_error_count,
            "description_formats": dict(sorted(description_formats.items())),
            "output_files": {
                "issues": self._relative_to_data_root(issues_path),
                "warnings": self._relative_to_data_root(warnings_path),
                "summary": self._relative_to_data_root(summary_path),
            },
        }

        # summary.json을 마지막에 기록해 세 파일 묶음의 완료 표시로 사용합니다.
        self.writer.write_text(
            summary_relative,
            json.dumps(summary_document, ensure_ascii=False, indent=2) + "\n",
        )

        return IssueExportResult(
            run_id=run_id,
            discovered_issue_count=len(sources),
            exported_issue_count=exported_issue_count,
            failed_issue_count=failed_issue_count,
            warning_count=len(warning_documents),
            parse_error_count=parse_error_count,
            issues_path=issues_path,
            warnings_path=warnings_path,
            summary_path=summary_path,
        )

    @staticmethod
    def _issue_document(record: IssueRecord) -> dict[str, Any]:
        """IssueRecord에서 분석 저장 계약에 포함되는 필드만 선택합니다."""

        return {
            "run_id": record.run_id,
            "project_key": record.project_key,
            "issue_key": record.issue_key,
            "jira_id": record.jira_id,
            "summary": record.summary,
            "description_text": record.description_text,
            "description_format": record.description_format,
            "issue_type": record.issue_type,
            "status": record.status,
            "priority": record.priority,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "source_path": record.source_path,
        }

    @staticmethod
    def _warning_document(
        source: IssueSource,
        warning: ParseWarning,
    ) -> dict[str, Any]:
        """비치명적 ParseWarning을 원본 추적 가능한 JSON 객체로 변환합니다."""

        return {
            "severity": "warning",
            "run_id": source.run_id,
            "project_key": source.project_key,
            "issue_key": source.issue_key,
            "code": warning.code,
            "message": warning.message,
            "json_path": warning.json_path,
            "source_path": str(source.issue_path),
        }

    @staticmethod
    def _parse_error_document(
        source: IssueSource,
        error: IssueParseError,
    ) -> dict[str, Any]:
        """파싱 실패를 다음 이슈 처리를 막지 않는 오류 문서로 변환합니다."""

        return {
            "severity": "error",
            "run_id": source.run_id,
            "project_key": source.project_key,
            "issue_key": source.issue_key,
            "code": "issue_parse_error",
            "message": str(error),
            "json_path": None,
            "source_path": str(source.issue_path),
        }

    def _relative_to_data_root(self, path: Path) -> str:
        """출력 파일 경로를 data_root 기준의 이식 가능한 POSIX 경로로 바꿉니다."""

        return path.relative_to(self.data_root).as_posix()

    @staticmethod
    def _utc_now_text() -> str:
        """요약 파일에 기록할 현재 UTC 시각을 ISO 8601 형식으로 반환합니다."""

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
