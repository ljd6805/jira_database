from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueSource:
    """수집된 Jira 이슈 한 건과 연결된 파일 시스템 위치를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    issue_path: Path
    comments_dir: Path


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """파싱은 계속할 수 있지만 나중에 검토해야 하는 관찰 결과를 나타냅니다."""

    code: str
    message: str
    json_path: str | None = None
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """Jira 이슈 한 건의 1차 표준화 결과를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    jira_id: str | None
    summary: str | None
    description_raw: Any
    description_rendered: str | None
    description_text: str | None
    description_format: str
    issue_type: str | None
    status: str | None
    priority: str | None
    created_at: str | None
    updated_at: str | None
    source_path: str


@dataclass(frozen=True, slots=True)
class IssueParseResult:
    """이슈 파싱 결과와 비치명적 경고를 함께 보관합니다."""

    record: IssueRecord
    warnings: tuple[ParseWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class CommentRecord:
    """Jira 댓글 한 건의 1차 표준화 결과를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    comment_id: str
    sequence: int
    author_name: str | None
    author_key: str | None
    created_at: str | None
    updated_at: str | None
    body_raw: Any
    body_text: str | None
    body_format: str
    source_path: str
    source_page: str


@dataclass(frozen=True, slots=True)
class CommentParseResult:
    """한 이슈의 댓글 페이지 전체를 파싱한 결과와 집계값을 보관합니다."""

    records: tuple[CommentRecord, ...]
    warnings: tuple[ParseWarning, ...] = ()
    page_count: int = 0
    discovered_comment_count: int = 0
    duplicate_comment_count: int = 0
    failed_page_count: int = 0
    failed_comment_count: int = 0
    missing_comment_source_count: int = 0


@dataclass(frozen=True, slots=True)
class AttachmentRecord:
    """Jira 이슈에 연결된 첨부파일의 메타데이터만 보관합니다."""

    run_id: str
    project_key: str
    issue_key: str
    attachment_id: str
    filename: str | None
    author_name: str | None
    author_key: str | None
    created_at: str | None
    size_bytes: int | None
    mime_type: str | None
    content_url: str | None
    thumbnail_url: str | None
    source_path: str


@dataclass(frozen=True, slots=True)
class IssueRelationshipRecord:
    """Issue Link와 계층 관계를 canonical source -> target edge로 표현합니다."""

    run_id: str
    observed_project_key: str
    relationship_id: str | None
    relationship_category: str
    relationship_type: str
    relationship_text: str
    source_issue_key: str
    target_issue_key: str
    source_summary: str | None
    source_status: str | None
    target_summary: str | None
    target_status: str | None
    observed_from_issue_key: str
    observed_direction: str
    derived: bool
    source_path: str


@dataclass(frozen=True, slots=True)
class CustomFieldDefinitionRecord:
    """Jira names/schema에서 얻은 Custom Field 정의 한 건을 나타냅니다."""

    run_id: str
    field_id: str
    field_name: str
    schema_type: str | None
    schema_items: str | None
    schema_custom: str | None
    schema_custom_id: str | None
    source_path: str


@dataclass(frozen=True, slots=True)
class CustomFieldValueRecord:
    """Custom Field 실제 값을 개인정보 최소화 규칙으로 정규화한 레코드입니다."""

    run_id: str
    project_key: str
    issue_key: str
    field_id: str
    field_name: str
    schema_type: str | None
    schema_items: str | None
    schema_custom: str | None
    actual_type: str
    value_kind: str
    display_value: str | None
    display_values: tuple[str, ...]
    value_id: str | None
    value_ids: tuple[str, ...]
    user_keys: tuple[str, ...]
    value_shape: tuple[str, ...]
    source_path: str


@dataclass(frozen=True, slots=True)
class IssueStructureParseResult:
    """한 issue.json에서 추출한 4단계 구조 데이터와 영역별 경고·집계를 보관합니다."""

    attachments: tuple[AttachmentRecord, ...]
    relationships: tuple[IssueRelationshipRecord, ...]
    custom_field_definitions: tuple[CustomFieldDefinitionRecord, ...]
    custom_field_values: tuple[CustomFieldValueRecord, ...]
    attachment_warnings: tuple[ParseWarning, ...] = ()
    relationship_warnings: tuple[ParseWarning, ...] = ()
    custom_field_warnings: tuple[ParseWarning, ...] = ()
    discovered_attachment_count: int = 0
    failed_attachment_count: int = 0
    discovered_relationship_count: int = 0
    issue_link_count: int = 0
    hierarchy_count: int = 0
    failed_relationship_count: int = 0
    discovered_custom_field_value_count: int = 0
    failed_custom_field_value_count: int = 0
