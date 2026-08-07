from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from jira_collector.parser import IssueStructureParseError, IssueStructureParser, RunReader
from jira_collector.parser.models import (
    AttachmentRecord,
    CustomFieldDefinitionRecord,
    CustomFieldValueRecord,
    IssueRelationshipRecord,
    IssueSource,
    ParseWarning,
)

from .atomic_writer import AtomicTextWriter
from .models import StructureExportResult
from .run_summary_store import RunSummaryStore
from .run_warning_store import RunWarningStore


class IssueStructureJsonlExporter:
    """issue.json의 Attachment·관계·Custom Field를 한 번의 순회로 ANALYSIS JSONL에 저장합니다."""

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
        self.summary_store = RunSummaryStore(self.data_root, analysis_directory)
        self.warning_store = RunWarningStore(self.data_root, analysis_directory)

    def export_run(
        self,
        run_id: str,
        reader: RunReader,
        parser: IssueStructureParser,
    ) -> StructureExportResult:
        """run_id의 issue.json을 한 번씩 읽어 4개의 구조 데이터 JSONL과 공통 통계를 생성합니다."""

        sources = reader.list_issue_sources(run_id)
        attachments_relative = Path(run_id) / "attachments.jsonl"
        relationships_relative = Path(run_id) / "issue_relationships.jsonl"
        catalog_relative = Path(run_id) / "custom_field_catalog.jsonl"
        values_relative = Path(run_id) / "custom_field_values.jsonl"

        attachments_path = (self.analysis_root / attachments_relative).resolve()
        relationships_path = (self.analysis_root / relationships_relative).resolve()
        catalog_path = (self.analysis_root / catalog_relative).resolve()
        values_path = (self.analysis_root / values_relative).resolve()

        warnings_by_component: dict[str, list[dict[str, Any]]] = {
            "attachments": [],
            "relationships": [],
            "custom_fields": [],
            "structure": [],
        }

        discovered_attachment_count = 0
        exported_attachment_count = 0
        failed_attachment_count = 0
        discovered_relationship_count = 0
        exported_relationship_count = 0
        duplicate_relationship_count = 0
        issue_link_count = 0
        hierarchy_count = 0
        failed_relationship_count = 0
        discovered_custom_field_value_count = 0
        exported_custom_field_value_count = 0
        failed_custom_field_value_count = 0
        failed_issue_count = 0
        definition_mismatch_count = 0
        used_field_ids: set[str] = set()
        value_kinds: Counter[str] = Counter()
        catalog: dict[str, CustomFieldDefinitionRecord] = {}
        relationship_keys: set[str] = set()

        # 세 대용량 출력은 스트리밍으로 기록하고, Catalog 정의 220여 건만 메모리에 유지합니다.
        with (
            self.writer.open_text(attachments_relative) as attachments_handle,
            self.writer.open_text(relationships_relative) as relationships_handle,
            self.writer.open_text(values_relative) as values_handle,
        ):
            for source in sources:
                try:
                    result = parser.parse_file(source)
                except IssueStructureParseError as exc:
                    failed_issue_count += 1
                    warnings_by_component["structure"].append(
                        self._fatal_issue_warning(source, exc)
                    )
                    continue

                discovered_attachment_count += result.discovered_attachment_count
                failed_attachment_count += result.failed_attachment_count
                discovered_relationship_count += result.discovered_relationship_count
                issue_link_count += result.issue_link_count
                hierarchy_count += result.hierarchy_count
                failed_relationship_count += result.failed_relationship_count
                discovered_custom_field_value_count += result.discovered_custom_field_value_count
                failed_custom_field_value_count += result.failed_custom_field_value_count

                for record in result.attachments:
                    attachments_handle.write(self._json_line(self._attachment_document(record)))
                    exported_attachment_count += 1

                for record in result.relationships:
                    relationship_key = self._relationship_key(record)
                    if relationship_key in relationship_keys:
                        duplicate_relationship_count += 1
                        continue
                    relationship_keys.add(relationship_key)
                    relationships_handle.write(self._json_line(self._relationship_document(record)))
                    exported_relationship_count += 1

                for definition in result.custom_field_definitions:
                    existing = catalog.get(definition.field_id)
                    if existing is None:
                        catalog[definition.field_id] = definition
                    elif self._definition_signature(existing) != self._definition_signature(definition):
                        definition_mismatch_count += 1
                        warnings_by_component["custom_fields"].append(
                            self._definition_mismatch_warning(source, existing, definition)
                        )

                for record in result.custom_field_values:
                    values_handle.write(self._json_line(self._custom_field_value_document(record)))
                    exported_custom_field_value_count += 1
                    used_field_ids.add(record.field_id)
                    value_kinds[record.value_kind] += 1

                self._append_parser_warnings(
                    warnings_by_component["attachments"], source, result.attachment_warnings
                )
                self._append_parser_warnings(
                    warnings_by_component["relationships"], source, result.relationship_warnings
                )
                self._append_parser_warnings(
                    warnings_by_component["custom_fields"], source, result.custom_field_warnings
                )

        # Catalog는 field_id 순서로 고정해 실행마다 동일한 파일 순서를 보장합니다.
        with self.writer.open_text(catalog_relative) as catalog_handle:
            for field_id in sorted(catalog):
                catalog_handle.write(
                    self._json_line(self._custom_field_definition_document(catalog[field_id]))
                )

        warnings_path = self.warning_store.replace_components(
            run_id,
            warnings_by_component,
        )

        attachment_warning_count = len(warnings_by_component["attachments"])
        relationship_warning_count = len(warnings_by_component["relationships"])
        custom_warning_count = len(warnings_by_component["custom_fields"])
        structure_warning_count = len(warnings_by_component["structure"])

        summary_path = self.summary_store.update_sections(
            run_id,
            {
                "attachments": {
                    "status": "partial"
                    if failed_issue_count or failed_attachment_count
                    else "completed",
                    "parser_version": self.PARSER_VERSION,
                    "issue_count": len(sources),
                    "discovered_count": discovered_attachment_count,
                    "exported_count": exported_attachment_count,
                    "failed_count": failed_attachment_count,
                    "failed_issue_count": failed_issue_count,
                    "warning_count": attachment_warning_count + structure_warning_count,
                },
                "relationships": {
                    "status": "partial"
                    if failed_issue_count or failed_relationship_count
                    else "completed",
                    "parser_version": self.PARSER_VERSION,
                    "issue_count": len(sources),
                    "discovered_count": discovered_relationship_count,
                    "exported_count": exported_relationship_count,
                    "duplicate_count": duplicate_relationship_count,
                    "issue_link_count": issue_link_count,
                    "hierarchy_count": hierarchy_count,
                    "failed_count": failed_relationship_count,
                    "failed_issue_count": failed_issue_count,
                    "warning_count": relationship_warning_count + structure_warning_count,
                },
                "custom_fields": {
                    "status": "partial"
                    if failed_issue_count
                    or failed_custom_field_value_count
                    or definition_mismatch_count
                    else "completed",
                    "parser_version": self.PARSER_VERSION,
                    "issue_count": len(sources),
                    "catalog_count": len(catalog),
                    "used_field_count": len(used_field_ids),
                    "discovered_value_count": discovered_custom_field_value_count,
                    "exported_value_count": exported_custom_field_value_count,
                    "failed_value_count": failed_custom_field_value_count,
                    "definition_mismatch_count": definition_mismatch_count,
                    "failed_issue_count": failed_issue_count,
                    "warning_count": custom_warning_count + structure_warning_count,
                    "value_kinds": dict(sorted(value_kinds.items())),
                },
            },
            {
                "attachments": self._relative_to_data_root(attachments_path),
                "relationships": self._relative_to_data_root(relationships_path),
                "custom_field_catalog": self._relative_to_data_root(catalog_path),
                "custom_field_values": self._relative_to_data_root(values_path),
                "warnings": self._relative_to_data_root(warnings_path),
                "summary": self._relative_to_data_root(
                    self.analysis_root / run_id / "summary.json"
                ),
            },
        )

        return StructureExportResult(
            run_id=run_id,
            issue_count=len(sources),
            discovered_attachment_count=discovered_attachment_count,
            exported_attachment_count=exported_attachment_count,
            failed_attachment_count=failed_attachment_count,
            discovered_relationship_count=discovered_relationship_count,
            exported_relationship_count=exported_relationship_count,
            duplicate_relationship_count=duplicate_relationship_count,
            issue_link_count=issue_link_count,
            hierarchy_count=hierarchy_count,
            failed_relationship_count=failed_relationship_count,
            custom_field_catalog_count=len(catalog),
            used_custom_field_count=len(used_field_ids),
            discovered_custom_field_value_count=discovered_custom_field_value_count,
            exported_custom_field_value_count=exported_custom_field_value_count,
            failed_custom_field_value_count=failed_custom_field_value_count,
            definition_mismatch_count=definition_mismatch_count,
            failed_issue_count=failed_issue_count,
            warning_count=sum(len(items) for items in warnings_by_component.values()),
            attachments_path=attachments_path,
            relationships_path=relationships_path,
            custom_field_catalog_path=catalog_path,
            custom_field_values_path=values_path,
            warnings_path=warnings_path,
            summary_path=summary_path,
        )

    @staticmethod
    def _json_line(document: dict[str, Any]) -> str:
        """JSON 객체를 UTF-8 JSONL 한 줄 문자열로 직렬화합니다."""

        return json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"

    @staticmethod
    def _attachment_document(record: AttachmentRecord) -> dict[str, Any]:
        """AttachmentRecord를 ANALYSIS 저장 계약의 JSON 객체로 변환합니다."""

        return {
            "run_id": record.run_id,
            "project_key": record.project_key,
            "issue_key": record.issue_key,
            "attachment_id": record.attachment_id,
            "filename": record.filename,
            "author_name": record.author_name,
            "author_key": record.author_key,
            "created_at": record.created_at,
            "size_bytes": record.size_bytes,
            "mime_type": record.mime_type,
            "content_url": record.content_url,
            "thumbnail_url": record.thumbnail_url,
            "source_path": record.source_path,
        }

    @staticmethod
    def _relationship_document(record: IssueRelationshipRecord) -> dict[str, Any]:
        """관계 레코드를 그래프에서 바로 사용할 수 있는 canonical edge JSON으로 변환합니다."""

        return {
            "run_id": record.run_id,
            "observed_project_key": record.observed_project_key,
            "relationship_id": record.relationship_id,
            "relationship_category": record.relationship_category,
            "relationship_type": record.relationship_type,
            "relationship_text": record.relationship_text,
            "source_issue_key": record.source_issue_key,
            "target_issue_key": record.target_issue_key,
            "source_summary": record.source_summary,
            "source_status": record.source_status,
            "target_summary": record.target_summary,
            "target_status": record.target_status,
            "observed_from_issue_key": record.observed_from_issue_key,
            "observed_direction": record.observed_direction,
            "derived": record.derived,
            "source_path": record.source_path,
        }

    @staticmethod
    def _custom_field_definition_document(
        record: CustomFieldDefinitionRecord,
    ) -> dict[str, Any]:
        """Custom Field 정의를 업무 값이 없는 Catalog JSON으로 변환합니다."""

        return {
            "run_id": record.run_id,
            "field_id": record.field_id,
            "field_name": record.field_name,
            "schema_type": record.schema_type,
            "schema_items": record.schema_items,
            "schema_custom": record.schema_custom,
            "schema_custom_id": record.schema_custom_id,
            "source_path": record.source_path,
        }

    @staticmethod
    def _custom_field_value_document(record: CustomFieldValueRecord) -> dict[str, Any]:
        """Custom Field 값을 원본 객체 전체 복제 없이 검색 가능한 안전한 JSON으로 변환합니다."""

        return {
            "run_id": record.run_id,
            "project_key": record.project_key,
            "issue_key": record.issue_key,
            "field_id": record.field_id,
            "field_name": record.field_name,
            "schema_type": record.schema_type,
            "schema_items": record.schema_items,
            "schema_custom": record.schema_custom,
            "actual_type": record.actual_type,
            "value_kind": record.value_kind,
            "display_value": record.display_value,
            "display_values": list(record.display_values),
            "value_id": record.value_id,
            "value_ids": list(record.value_ids),
            "user_keys": list(record.user_keys),
            "value_shape": list(record.value_shape),
            "source_path": record.source_path,
        }

    @staticmethod
    def _relationship_key(record: IssueRelationshipRecord) -> str:
        """양쪽 issue.json에 같은 Jira Link가 나타나도 한 edge만 남도록 중복 키를 만듭니다."""

        if record.relationship_category == "issue_link" and record.relationship_id:
            return f"issue_link:{record.relationship_id}"
        return (
            f"{record.relationship_category}:{record.relationship_type}:"
            f"{record.source_issue_key}:{record.target_issue_key}"
        )

    @staticmethod
    def _definition_signature(record: CustomFieldDefinitionRecord) -> tuple[Any, ...]:
        """서로 다른 issue.json의 동일 field_id 정의가 같은지 비교할 서명을 만듭니다."""

        return (
            record.field_name,
            record.schema_type,
            record.schema_items,
            record.schema_custom,
            record.schema_custom_id,
        )

    @classmethod
    def _definition_mismatch_warning(
        cls,
        source: IssueSource,
        existing: CustomFieldDefinitionRecord,
        current: CustomFieldDefinitionRecord,
    ) -> dict[str, Any]:
        """동일 field_id의 names/schema가 이슈별로 다를 때 검토용 경고를 만듭니다."""

        return {
            "severity": "warning",
            "run_id": source.run_id,
            "project_key": source.project_key,
            "issue_key": source.issue_key,
            "code": "custom_field_definition_mismatch",
            "message": (
                f"동일 Custom Field 정의가 이슈별로 다릅니다: {current.field_id}; "
                f"first={cls._definition_signature(existing)!r}, "
                f"current={cls._definition_signature(current)!r}"
            ),
            "json_path": f"/schema/{current.field_id}",
            "source_path": str(source.issue_path),
        }

    @staticmethod
    def _fatal_issue_warning(
        source: IssueSource,
        error: IssueStructureParseError,
    ) -> dict[str, Any]:
        """한 issue.json 전체를 읽지 못한 오류를 다음 이슈 처리와 분리해 기록합니다."""

        return {
            "severity": "error",
            "run_id": source.run_id,
            "project_key": source.project_key,
            "issue_key": source.issue_key,
            "code": "issue_structure_parse_error",
            "message": str(error),
            "json_path": None,
            "source_path": str(source.issue_path),
        }

    @classmethod
    def _append_parser_warnings(
        cls,
        target: list[dict[str, Any]],
        source: IssueSource,
        warnings: tuple[ParseWarning, ...],
    ) -> None:
        """Parser 경고를 공통 parse_warnings.jsonl 형식으로 변환해 누적합니다."""

        for warning in warnings:
            target.append(
                {
                    "severity": warning.severity,
                    "run_id": source.run_id,
                    "project_key": source.project_key,
                    "issue_key": source.issue_key,
                    "code": warning.code,
                    "message": warning.message,
                    "json_path": warning.json_path,
                    "source_path": str(source.issue_path),
                }
            )

    def _relative_to_data_root(self, path: Path) -> str:
        """절대 경로를 data_root 기준의 POSIX 상대 경로로 변환합니다."""

        return path.resolve().relative_to(self.data_root).as_posix()
