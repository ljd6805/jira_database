from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    AttachmentRecord,
    CustomFieldDefinitionRecord,
    CustomFieldValueRecord,
    IssueRelationshipRecord,
    IssueSource,
    IssueStructureParseResult,
    ParseWarning,
)
from .value_helpers import author_key_value, named_value, optional_string, value_type_name


class IssueStructureParseError(ValueError):
    """issue.json 자체를 읽을 수 없어 구조 데이터 파싱을 시작할 수 없을 때 발생합니다."""


class IssueStructureParser:
    """하나의 issue.json을 한 번 읽어 Attachment·관계·Custom Field를 함께 파싱합니다."""

    def parse_file(self, source: IssueSource) -> IssueStructureParseResult:
        """RAW issue.json을 읽고 4단계 구조 데이터 레코드 묶음으로 변환합니다."""

        payload = self._load_payload(source.issue_path)
        return self.parse_payload(payload, source)

    def parse_payload(
        self,
        payload: dict[str, Any],
        source: IssueSource,
    ) -> IssueStructureParseResult:
        """이미 읽은 Jira 이슈 객체에서 구조 데이터를 결정적으로 추출합니다."""

        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise IssueStructureParseError(
                f"이슈 fields가 객체 형식이 아닙니다: {source.issue_path}"
            )

        attachments, attachment_warnings, discovered_attachments, failed_attachments = (
            self._parse_attachments(fields, source)
        )
        relationships, relationship_warnings, relationship_stats = (
            self._parse_relationships(payload, fields, source)
        )
        definitions, values, custom_warnings, failed_custom_values = (
            self._parse_custom_fields(payload, fields, source)
        )

        return IssueStructureParseResult(
            attachments=tuple(attachments),
            relationships=tuple(relationships),
            custom_field_definitions=tuple(definitions),
            custom_field_values=tuple(values),
            attachment_warnings=tuple(attachment_warnings),
            relationship_warnings=tuple(relationship_warnings),
            custom_field_warnings=tuple(custom_warnings),
            discovered_attachment_count=discovered_attachments,
            failed_attachment_count=failed_attachments,
            discovered_relationship_count=relationship_stats["discovered"],
            issue_link_count=relationship_stats["issue_links"],
            hierarchy_count=relationship_stats["hierarchy"],
            failed_relationship_count=relationship_stats["failed"],
            discovered_custom_field_value_count=len(values) + failed_custom_values,
            failed_custom_field_value_count=failed_custom_values,
        )

    @staticmethod
    def _load_payload(path: Path) -> dict[str, Any]:
        """UTF-8 issue.json을 읽고 최상위 객체 형식을 검증합니다."""

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IssueStructureParseError(
                f"이슈 JSON을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise IssueStructureParseError(
                f"이슈 JSON 최상위 값은 객체여야 합니다: {path}"
            )
        return payload

    def _parse_attachments(
        self,
        fields: dict[str, Any],
        source: IssueSource,
    ) -> tuple[list[AttachmentRecord], list[ParseWarning], int, int]:
        """fields.attachment 배열에서 파일 본문을 제외한 메타데이터만 추출합니다."""

        raw_attachments = fields.get("attachment")
        if raw_attachments is None:
            return [], [], 0, 0
        if not isinstance(raw_attachments, list):
            return (
                [],
                [
                    ParseWarning(
                        code="invalid_attachment_array",
                        message="fields.attachment 값이 배열이 아닙니다.",
                        json_path="/fields/attachment",
                        severity="error",
                    )
                ],
                0,
                1,
            )

        records: list[AttachmentRecord] = []
        warnings: list[ParseWarning] = []
        failed_count = 0
        for index, item in enumerate(raw_attachments):
            json_path = f"/fields/attachment/{index}"
            if not isinstance(item, dict):
                failed_count += 1
                warnings.append(
                    ParseWarning(
                        code="invalid_attachment_object",
                        message="첨부파일 항목이 객체가 아닙니다.",
                        json_path=json_path,
                        severity="error",
                    )
                )
                continue

            attachment_id = optional_string(item.get("id"))
            if attachment_id is None:
                failed_count += 1
                warnings.append(
                    ParseWarning(
                        code="missing_attachment_id",
                        message="첨부파일 id가 없어 레코드를 만들 수 없습니다.",
                        json_path=f"{json_path}/id",
                        severity="error",
                    )
                )
                continue

            size_value = item.get("size")
            size_bytes: int | None = None
            if isinstance(size_value, bool):
                warnings.append(
                    ParseWarning(
                        code="invalid_attachment_size",
                        message="첨부파일 size에 boolean 값이 들어 있습니다.",
                        json_path=f"{json_path}/size",
                    )
                )
            elif isinstance(size_value, int):
                size_bytes = size_value
            elif size_value is not None:
                try:
                    size_bytes = int(size_value)
                except (TypeError, ValueError):
                    warnings.append(
                        ParseWarning(
                            code="invalid_attachment_size",
                            message=(
                                "첨부파일 size를 정수로 변환할 수 없습니다: "
                                f"{value_type_name(size_value)}"
                            ),
                            json_path=f"{json_path}/size",
                        )
                    )

            author = item.get("author")
            records.append(
                AttachmentRecord(
                    run_id=source.run_id,
                    project_key=source.project_key,
                    issue_key=source.issue_key,
                    attachment_id=attachment_id,
                    filename=optional_string(item.get("filename")),
                    author_name=named_value(author),
                    author_key=author_key_value(author),
                    created_at=optional_string(item.get("created")),
                    size_bytes=size_bytes,
                    mime_type=optional_string(item.get("mimeType")),
                    content_url=optional_string(item.get("content")),
                    thumbnail_url=optional_string(item.get("thumbnail")),
                    source_path=str(source.issue_path),
                )
            )

        return records, warnings, len(raw_attachments), failed_count

    def _parse_relationships(
        self,
        payload: dict[str, Any],
        fields: dict[str, Any],
        source: IssueSource,
    ) -> tuple[list[IssueRelationshipRecord], list[ParseWarning], dict[str, int]]:
        """명시적 Issue Link와 parent/subtask 계층을 canonical parent/outward 방향으로 변환합니다."""

        records: list[IssueRelationshipRecord] = []
        warnings: list[ParseWarning] = []
        stats = {"discovered": 0, "issue_links": 0, "hierarchy": 0, "failed": 0}

        current_summary = optional_string(fields.get("summary"))
        current_status = named_value(fields.get("status"))
        raw_links = fields.get("issuelinks")
        if raw_links is None:
            raw_links = []
        if not isinstance(raw_links, list):
            stats["failed"] += 1
            warnings.append(
                ParseWarning(
                    code="invalid_issue_links_array",
                    message="fields.issuelinks 값이 배열이 아닙니다.",
                    json_path="/fields/issuelinks",
                    severity="error",
                )
            )
            raw_links = []

        for index, link in enumerate(raw_links):
            json_path = f"/fields/issuelinks/{index}"
            if not isinstance(link, dict):
                stats["failed"] += 1
                warnings.append(
                    ParseWarning(
                        code="invalid_issue_link_object",
                        message="Issue Link 항목이 객체가 아닙니다.",
                        json_path=json_path,
                        severity="error",
                    )
                )
                continue

            link_type = link.get("type")
            if not isinstance(link_type, dict):
                link_type = {}
                warnings.append(
                    ParseWarning(
                        code="invalid_issue_link_type",
                        message="Issue Link type이 객체가 아닙니다.",
                        json_path=f"{json_path}/type",
                    )
                )

            outward = link.get("outwardIssue")
            inward = link.get("inwardIssue")
            candidates: list[tuple[str, dict[str, Any]]] = []
            if isinstance(outward, dict):
                candidates.append(("outward", outward))
            if isinstance(inward, dict):
                candidates.append(("inward", inward))
            if not candidates:
                stats["failed"] += 1
                warnings.append(
                    ParseWarning(
                        code="missing_issue_link_target",
                        message="Issue Link에 inwardIssue 또는 outwardIssue가 없습니다.",
                        json_path=json_path,
                        severity="error",
                    )
                )
                continue

            for observed_direction, linked_issue in candidates:
                stats["discovered"] += 1
                stats["issue_links"] += 1
                linked_key = optional_string(linked_issue.get("key"))
                if linked_key is None:
                    stats["failed"] += 1
                    warnings.append(
                        ParseWarning(
                            code="missing_linked_issue_key",
                            message="연결 이슈 key가 없어 관계를 만들 수 없습니다.",
                            json_path=f"{json_path}/{observed_direction}Issue/key",
                            severity="error",
                        )
                    )
                    continue

                linked_fields = linked_issue.get("fields")
                linked_fields = linked_fields if isinstance(linked_fields, dict) else {}
                linked_summary = optional_string(linked_fields.get("summary"))
                linked_status = named_value(linked_fields.get("status"))

                # Jira link의 outward 문구를 canonical edge의 의미로 사용합니다.
                # inwardIssue로 관찰한 경우 실제 edge 방향은 linked issue -> current issue입니다.
                if observed_direction == "outward":
                    source_key = source.issue_key
                    target_key = linked_key
                    source_summary = current_summary
                    source_status = current_status
                    target_summary = linked_summary
                    target_status = linked_status
                else:
                    source_key = linked_key
                    target_key = source.issue_key
                    source_summary = linked_summary
                    source_status = linked_status
                    target_summary = current_summary
                    target_status = current_status

                records.append(
                    IssueRelationshipRecord(
                        run_id=source.run_id,
                        observed_project_key=source.project_key,
                        relationship_id=optional_string(link.get("id")),
                        relationship_category="issue_link",
                        relationship_type=optional_string(link_type.get("name")) or "unknown",
                        relationship_text=(
                            optional_string(link_type.get("outward"))
                            or optional_string(link_type.get("name"))
                            or "related to"
                        ),
                        source_issue_key=source_key,
                        target_issue_key=target_key,
                        source_summary=source_summary,
                        source_status=source_status,
                        target_summary=target_summary,
                        target_status=target_status,
                        observed_from_issue_key=source.issue_key,
                        observed_direction=observed_direction,
                        derived=False,
                        source_path=str(source.issue_path),
                    )
                )

        # parent 필드가 향후 나타나더라도 parent -> child 방향으로 canonicalize합니다.
        parent = fields.get("parent")
        if isinstance(parent, dict):
            stats["discovered"] += 1
            stats["hierarchy"] += 1
            parent_key = optional_string(parent.get("key"))
            if parent_key is None:
                stats["failed"] += 1
                warnings.append(
                    ParseWarning(
                        code="missing_parent_issue_key",
                        message="parent 객체에 key가 없어 계층 관계를 만들 수 없습니다.",
                        json_path="/fields/parent/key",
                        severity="error",
                    )
                )
            else:
                parent_fields = parent.get("fields")
                parent_fields = parent_fields if isinstance(parent_fields, dict) else {}
                records.append(
                    self._hierarchy_record(
                        source=source,
                        parent_key=parent_key,
                        child_key=source.issue_key,
                        parent_summary=optional_string(parent_fields.get("summary")),
                        parent_status=named_value(parent_fields.get("status")),
                        child_summary=current_summary,
                        child_status=current_status,
                        observed_direction="parent",
                    )
                )

        raw_subtasks = fields.get("subtasks")
        if raw_subtasks is None:
            raw_subtasks = []
        if not isinstance(raw_subtasks, list):
            stats["failed"] += 1
            warnings.append(
                ParseWarning(
                    code="invalid_subtasks_array",
                    message="fields.subtasks 값이 배열이 아닙니다.",
                    json_path="/fields/subtasks",
                    severity="error",
                )
            )
            raw_subtasks = []

        for index, subtask in enumerate(raw_subtasks):
            stats["discovered"] += 1
            stats["hierarchy"] += 1
            json_path = f"/fields/subtasks/{index}"
            if not isinstance(subtask, dict):
                stats["failed"] += 1
                warnings.append(
                    ParseWarning(
                        code="invalid_subtask_object",
                        message="subtask 항목이 객체가 아닙니다.",
                        json_path=json_path,
                        severity="error",
                    )
                )
                continue
            child_key = optional_string(subtask.get("key"))
            if child_key is None:
                stats["failed"] += 1
                warnings.append(
                    ParseWarning(
                        code="missing_subtask_issue_key",
                        message="subtask 객체에 key가 없어 계층 관계를 만들 수 없습니다.",
                        json_path=f"{json_path}/key",
                        severity="error",
                    )
                )
                continue
            subtask_fields = subtask.get("fields")
            subtask_fields = subtask_fields if isinstance(subtask_fields, dict) else {}
            records.append(
                self._hierarchy_record(
                    source=source,
                    parent_key=source.issue_key,
                    child_key=child_key,
                    parent_summary=current_summary,
                    parent_status=current_status,
                    child_summary=optional_string(subtask_fields.get("summary")),
                    child_status=named_value(subtask_fields.get("status")),
                    observed_direction="subtask",
                )
            )

        return records, warnings, stats

    @staticmethod
    def _hierarchy_record(
        *,
        source: IssueSource,
        parent_key: str,
        child_key: str,
        parent_summary: str | None,
        parent_status: str | None,
        child_summary: str | None,
        child_status: str | None,
        observed_direction: str,
    ) -> IssueRelationshipRecord:
        """부모-자식 관계를 parent -> child 방향의 공통 레코드로 만듭니다."""

        return IssueRelationshipRecord(
            run_id=source.run_id,
            observed_project_key=source.project_key,
            relationship_id=f"hierarchy:{parent_key}:{child_key}",
            relationship_category="hierarchy",
            relationship_type="parent_of",
            relationship_text="parent of",
            source_issue_key=parent_key,
            target_issue_key=child_key,
            source_summary=parent_summary,
            source_status=parent_status,
            target_summary=child_summary,
            target_status=child_status,
            observed_from_issue_key=source.issue_key,
            observed_direction=observed_direction,
            derived=False,
            source_path=str(source.issue_path),
        )

    def _parse_custom_fields(
        self,
        payload: dict[str, Any],
        fields: dict[str, Any],
        source: IssueSource,
    ) -> tuple[
        list[CustomFieldDefinitionRecord],
        list[CustomFieldValueRecord],
        list[ParseWarning],
        int,
    ]:
        """names/schema 정의와 non-null customfield_* 값을 개인정보 최소화 규칙으로 정규화합니다."""

        warnings: list[ParseWarning] = []
        definitions: list[CustomFieldDefinitionRecord] = []
        values: list[CustomFieldValueRecord] = []
        failed_value_count = 0

        names = payload.get("names")
        schema = payload.get("schema")
        if not isinstance(names, dict):
            warnings.append(
                ParseWarning(
                    code="missing_custom_field_names",
                    message="issue.json의 names 객체를 찾을 수 없습니다.",
                    json_path="/names",
                )
            )
            names = {}
        if not isinstance(schema, dict):
            warnings.append(
                ParseWarning(
                    code="missing_custom_field_schema",
                    message="issue.json의 schema 객체를 찾을 수 없습니다.",
                    json_path="/schema",
                )
            )
            schema = {}

        field_ids = sorted(
            name for name in fields.keys() if name.startswith("customfield_")
        )
        for field_id in field_ids:
            raw_schema = schema.get(field_id)
            schema_object = raw_schema if isinstance(raw_schema, dict) else {}
            field_name = optional_string(names.get(field_id)) or field_id
            definition = CustomFieldDefinitionRecord(
                run_id=source.run_id,
                field_id=field_id,
                field_name=field_name,
                schema_type=optional_string(schema_object.get("type")),
                schema_items=optional_string(schema_object.get("items")),
                schema_custom=optional_string(schema_object.get("custom")),
                schema_custom_id=optional_string(schema_object.get("customId")),
                source_path=str(source.issue_path),
            )
            definitions.append(definition)

            raw_value = fields.get(field_id)
            if raw_value is None:
                continue
            try:
                values.append(
                    self._custom_field_value(
                        source=source,
                        definition=definition,
                        raw_value=raw_value,
                    )
                )
            except (TypeError, ValueError) as exc:
                failed_value_count += 1
                warnings.append(
                    ParseWarning(
                        code="custom_field_value_parse_error",
                        message=f"Custom Field 값을 정규화할 수 없습니다: {field_id}: {exc}",
                        json_path=f"/fields/{field_id}",
                        severity="error",
                    )
                )

        return definitions, values, warnings, failed_value_count

    def _custom_field_value(
        self,
        *,
        source: IssueSource,
        definition: CustomFieldDefinitionRecord,
        raw_value: Any,
    ) -> CustomFieldValueRecord:
        """실제 값 타입과 Jira schema를 함께 보고 안전한 표시값과 식별자만 추출합니다."""

        actual_type = value_type_name(raw_value)
        value_kind = actual_type
        display_value: str | None = None
        display_values: tuple[str, ...] = ()
        value_id: str | None = None
        value_ids: tuple[str, ...] = ()
        user_keys: tuple[str, ...] = ()
        value_shape: tuple[str, ...] = ()

        if isinstance(raw_value, str):
            value_kind = "string"
            display_value = raw_value.strip() or None
        elif isinstance(raw_value, (int, float, bool)):
            value_kind = "scalar"
            display_value = str(raw_value)
        elif isinstance(raw_value, dict):
            value_shape = tuple(sorted(str(key) for key in raw_value.keys()))
            if definition.schema_type == "option" or "value" in raw_value:
                value_kind = "option"
                display_value = named_value(raw_value)
                value_id = optional_string(raw_value.get("id"))
            else:
                value_kind = "generic_object"
                display_value = named_value(raw_value)
                value_id = optional_string(raw_value.get("id"))
        elif isinstance(raw_value, list):
            if definition.schema_type == "array" and definition.schema_items == "user":
                value_kind = "user_array"
                names: list[str] = []
                keys: list[str] = []
                for item in raw_value:
                    if not isinstance(item, dict):
                        continue
                    name = named_value(item)
                    key = author_key_value(item)
                    if name:
                        names.append(name)
                    if key:
                        keys.append(key)
                display_values = tuple(names)
                user_keys = tuple(keys)
                value_shape = self._array_shape(raw_value)
            else:
                value_kind = "generic_array"
                display_items: list[str] = []
                ids: list[str] = []
                for item in raw_value:
                    candidate = named_value(item) if isinstance(item, dict) else optional_string(item)
                    if candidate:
                        display_items.append(candidate)
                    if isinstance(item, dict):
                        item_id = optional_string(item.get("id"))
                        if item_id:
                            ids.append(item_id)
                display_values = tuple(display_items)
                value_ids = tuple(ids)
                value_shape = self._array_shape(raw_value)
        else:
            raise TypeError(f"지원하지 않는 값 타입입니다: {actual_type}")

        return CustomFieldValueRecord(
            run_id=source.run_id,
            project_key=source.project_key,
            issue_key=source.issue_key,
            field_id=definition.field_id,
            field_name=definition.field_name,
            schema_type=definition.schema_type,
            schema_items=definition.schema_items,
            schema_custom=definition.schema_custom,
            actual_type=actual_type,
            value_kind=value_kind,
            display_value=display_value,
            display_values=display_values,
            value_id=value_id,
            value_ids=value_ids,
            user_keys=user_keys,
            value_shape=value_shape,
            source_path=str(source.issue_path),
        )

    @staticmethod
    def _array_shape(value: list[Any]) -> tuple[str, ...]:
        """배열 원소의 실제 값을 복제하지 않고 타입·객체 key 구조만 기록합니다."""

        signatures: set[str] = set()
        for item in value:
            if isinstance(item, dict):
                keys = ",".join(sorted(str(key) for key in item.keys()))
                signatures.add(f"object[{keys}]")
            else:
                signatures.add(value_type_name(item))
        return tuple(sorted(signatures))
