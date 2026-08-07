from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    KnowledgeExtractionValidationError,
    KnowledgeExtractionValidationResult,
    KnowledgeValidationMessage,
)


_KNOWLEDGE_SCHEMA_VERSION = "1.0"
_PROMPT_VERSION = "knowledge-extraction-v1"

_STATEMENT_CATEGORIES = (
    "problem_or_goal",
    "context",
    "observations",
    "hypotheses",
    "confirmed_causes",
    "actions_taken",
    "plans",
    "decisions",
    "results",
    "conclusions",
    "open_questions",
    "blockers",
)

_REQUIRED_TOP_LEVEL_KEYS = {
    "knowledge_schema_version",
    "run_id",
    "project_key",
    "issue_key",
    "source_hash",
    "prompt_version",
    "extractor_model",
    "extracted_at",
    "issue_summary",
    *_STATEMENT_CATEGORIES,
}

_ALLOWED_STATES = {
    "stated",
    "proposed",
    "active",
    "observed",
    "confirmed",
    "rejected",
    "attempted",
    "completed",
    "failed",
    "cancelled",
    "superseded",
    "unresolved",
    "unknown",
}

_ALLOWED_EVIDENCE_TYPES = {
    "issue_description",
    "comment",
    "attachment_metadata",
    "relationship",
    "custom_field",
}

# 원인·조치·결정·결과·결론처럼 의미 해석이 큰 항목은
# Attachment filename이나 Relationship metadata만으로 확정하지 못하게 텍스트 근거를 요구합니다.
_TEXT_EVIDENCE_REQUIRED = {
    "hypotheses",
    "confirmed_causes",
    "actions_taken",
    "plans",
    "decisions",
    "results",
    "conclusions",
    "open_questions",
    "blockers",
}


class KnowledgeExtractionValidator:
    """OpenCode Agent 출력이 Knowledge Input과 구조적으로 일치하는지 결정적으로 검증합니다."""

    def validate_files(
        self,
        package_path: str | Path,
        extraction_path: str | Path,
    ) -> KnowledgeExtractionValidationResult:
        """Knowledge Input package와 Agent 출력 JSON 파일을 읽어 검증합니다."""

        package = self._load_json_object(Path(package_path), "Knowledge Input")
        extraction = self._load_json_object(Path(extraction_path), "Knowledge")
        return self.validate(package, extraction)

    def validate(
        self,
        package: dict[str, Any],
        extraction: dict[str, Any],
    ) -> KnowledgeExtractionValidationResult:
        """이미 읽은 두 JSON 객체의 metadata, schema, evidence 연결을 검증합니다."""

        errors: list[KnowledgeValidationMessage] = []
        warnings: list[KnowledgeValidationMessage] = []

        # 먼저 top-level 계약을 확인해 이후 세부 검증에서 예상하지 못한 key를 조용히 무시하지 않게 합니다.
        self._validate_top_level(extraction, errors)

        # Agent가 입력 package의 식별자나 source_hash를 임의로 바꾸면 다른 snapshot의 Knowledge로 오인할 수 있습니다.
        self._validate_identity(package, extraction, errors)

        # 실행 추적에 필요한 Prompt/Model/시각 metadata를 검증합니다.
        self._validate_metadata(extraction, errors)

        # 실제 package에 존재하는 evidence 식별자 집합을 만들고 모든 statement 참조를 교차 검증합니다.
        evidence_index = self._evidence_index(package)

        summary = extraction.get("issue_summary")
        if summary is not None:
            self._validate_statement(
                summary,
                "issue_summary",
                evidence_index,
                errors,
                warnings,
                require_state=False,
            )

        for category in _STATEMENT_CATEGORIES:
            value = extraction.get(category)
            if not isinstance(value, list):
                errors.append(
                    self._message(
                        "error",
                        "invalid_category_type",
                        f"/{category}",
                        f"{category} 값은 배열이어야 합니다.",
                    )
                )
                continue

            for index, statement in enumerate(value):
                self._validate_statement(
                    statement,
                    f"{category}/{index}",
                    evidence_index,
                    errors,
                    warnings,
                    require_state=True,
                    category=category,
                )

        return KnowledgeExtractionValidationResult(
            valid=not errors,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _validate_top_level(
        self,
        extraction: dict[str, Any],
        errors: list[KnowledgeValidationMessage],
    ) -> None:
        """필수 top-level key와 스키마 밖 추가 key를 검증합니다."""

        keys = set(extraction)
        missing = sorted(_REQUIRED_TOP_LEVEL_KEYS - keys)
        extra = sorted(keys - _REQUIRED_TOP_LEVEL_KEYS)

        for key in missing:
            errors.append(
                self._message(
                    "error",
                    "missing_top_level_key",
                    "/",
                    f"필수 top-level key가 없습니다: {key}",
                )
            )

        for key in extra:
            errors.append(
                self._message(
                    "error",
                    "unexpected_top_level_key",
                    f"/{key}",
                    f"스키마에 정의되지 않은 top-level key입니다: {key}",
                )
            )

        if extraction.get("knowledge_schema_version") != _KNOWLEDGE_SCHEMA_VERSION:
            errors.append(
                self._message(
                    "error",
                    "knowledge_schema_version_mismatch",
                    "/knowledge_schema_version",
                    f"knowledge_schema_version은 {_KNOWLEDGE_SCHEMA_VERSION!r}이어야 합니다.",
                )
            )

        if extraction.get("prompt_version") != _PROMPT_VERSION:
            errors.append(
                self._message(
                    "error",
                    "prompt_version_mismatch",
                    "/prompt_version",
                    f"prompt_version은 {_PROMPT_VERSION!r}이어야 합니다.",
                )
            )

    def _validate_identity(
        self,
        package: dict[str, Any],
        extraction: dict[str, Any],
        errors: list[KnowledgeValidationMessage],
    ) -> None:
        """Knowledge가 실제 입력 package와 동일한 Issue snapshot을 가리키는지 확인합니다."""

        for key in ("run_id", "project_key", "issue_key", "source_hash"):
            if extraction.get(key) != package.get(key):
                errors.append(
                    self._message(
                        "error",
                        "input_identity_mismatch",
                        f"/{key}",
                        f"Agent 출력 {key}가 Knowledge Input 값과 다릅니다.",
                    )
                )

    def _validate_metadata(
        self,
        extraction: dict[str, Any],
        errors: list[KnowledgeValidationMessage],
    ) -> None:
        """모델 식별자와 추출 시각 형식을 검증합니다."""

        model = extraction.get("extractor_model")
        if not isinstance(model, str) or not model.strip():
            errors.append(
                self._message(
                    "error",
                    "missing_extractor_model",
                    "/extractor_model",
                    "extractor_model은 비어 있지 않은 문자열이어야 합니다.",
                )
            )

        extracted_at = extraction.get("extracted_at")
        if not isinstance(extracted_at, str) or not extracted_at.strip():
            errors.append(
                self._message(
                    "error",
                    "missing_extracted_at",
                    "/extracted_at",
                    "extracted_at은 ISO 8601 문자열이어야 합니다.",
                )
            )
            return

        try:
            datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(
                self._message(
                    "error",
                    "invalid_extracted_at",
                    "/extracted_at",
                    "extracted_at을 ISO 8601 시각으로 해석할 수 없습니다.",
                )
            )

    def _validate_statement(
        self,
        statement: Any,
        path: str,
        evidence_index: dict[str, set[str]],
        errors: list[KnowledgeValidationMessage],
        warnings: list[KnowledgeValidationMessage],
        *,
        require_state: bool,
        category: str | None = None,
    ) -> None:
        """Knowledge statement 한 건의 text/state/evidence_refs를 검증합니다."""

        json_path = "/" + path.strip("/")
        if not isinstance(statement, dict):
            errors.append(
                self._message(
                    "error",
                    "invalid_statement_type",
                    json_path,
                    "Knowledge statement는 JSON 객체여야 합니다.",
                )
            )
            return

        allowed_keys = {"text", "evidence_refs"}
        if require_state:
            allowed_keys.add("state")

        extra_keys = sorted(set(statement) - allowed_keys)
        for key in extra_keys:
            errors.append(
                self._message(
                    "error",
                    "unexpected_statement_key",
                    f"{json_path}/{key}",
                    f"statement 스키마에 없는 key입니다: {key}",
                )
            )

        text = statement.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(
                self._message(
                    "error",
                    "empty_statement_text",
                    f"{json_path}/text",
                    "statement text는 비어 있지 않은 문자열이어야 합니다.",
                )
            )

        if require_state:
            state = statement.get("state")
            if state not in _ALLOWED_STATES:
                errors.append(
                    self._message(
                        "error",
                        "invalid_statement_state",
                        f"{json_path}/state",
                        f"허용되지 않은 state입니다: {state!r}",
                    )
                )
            elif category == "confirmed_causes" and state != "confirmed":
                warnings.append(
                    self._message(
                        "warning",
                        "confirmed_cause_state_suspicious",
                        f"{json_path}/state",
                        "confirmed_causes 항목은 일반적으로 state=confirmed여야 합니다.",
                    )
                )
            elif category == "observations" and state not in {
                "observed",
                "confirmed",
                "stated",
            }:
                warnings.append(
                    self._message(
                        "warning",
                        "observation_state_suspicious",
                        f"{json_path}/state",
                        "observations 항목의 state가 관찰 사실 의미와 어울리는지 검토하십시오.",
                    )
                )

        evidence_refs = statement.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(
                self._message(
                    "error",
                    "missing_evidence_refs",
                    f"{json_path}/evidence_refs",
                    "모든 Knowledge statement에는 최소 1개의 evidence가 필요합니다.",
                )
            )
            return

        evidence_types: set[str] = set()
        for index, reference in enumerate(evidence_refs):
            ref_type = self._validate_evidence_ref(
                reference,
                f"{json_path}/evidence_refs/{index}",
                evidence_index,
                errors,
            )
            if ref_type:
                evidence_types.add(ref_type)

        # 원인·결정·결론 같은 고해석 항목은 filename/관계 metadata만으로 확정하지 못하게 합니다.
        if category in _TEXT_EVIDENCE_REQUIRED and evidence_types:
            if not evidence_types.intersection({"issue_description", "comment"}):
                errors.append(
                    self._message(
                        "error",
                        "text_evidence_required",
                        f"{json_path}/evidence_refs",
                        f"{category} 항목에는 issue_description 또는 comment 근거가 최소 1개 필요합니다.",
                    )
                )

    def _validate_evidence_ref(
        self,
        reference: Any,
        path: str,
        evidence_index: dict[str, set[str]],
        errors: list[KnowledgeValidationMessage],
    ) -> str | None:
        """Evidence reference의 타입과 ID가 실제 Knowledge Input에 존재하는지 확인합니다."""

        if not isinstance(reference, dict):
            errors.append(
                self._message(
                    "error",
                    "invalid_evidence_ref_type",
                    path,
                    "evidence reference는 JSON 객체여야 합니다.",
                )
            )
            return None

        if set(reference) != {"source_type", "source_id"}:
            errors.append(
                self._message(
                    "error",
                    "invalid_evidence_ref_shape",
                    path,
                    "evidence reference는 source_type과 source_id만 가져야 합니다.",
                )
            )

        source_type = reference.get("source_type")
        source_id = reference.get("source_id")

        if source_type not in _ALLOWED_EVIDENCE_TYPES:
            errors.append(
                self._message(
                    "error",
                    "invalid_evidence_source_type",
                    f"{path}/source_type",
                    f"지원하지 않는 evidence source_type입니다: {source_type!r}",
                )
            )
            return None

        if not isinstance(source_id, str) or not source_id.strip():
            errors.append(
                self._message(
                    "error",
                    "invalid_evidence_source_id",
                    f"{path}/source_id",
                    "evidence source_id는 비어 있지 않은 문자열이어야 합니다.",
                )
            )
            return str(source_type)

        if source_id not in evidence_index.get(str(source_type), set()):
            errors.append(
                self._message(
                    "error",
                    "evidence_not_found",
                    path,
                    f"Knowledge Input에서 evidence를 찾을 수 없습니다: {source_type}:{source_id}",
                )
            )

        return str(source_type)

    @staticmethod
    def _evidence_index(package: dict[str, Any]) -> dict[str, set[str]]:
        """Knowledge Input 내부 객체에서 evidence로 참조 가능한 안정 식별자 집합을 만듭니다."""

        issue_key = package.get("issue_key")
        issue = package.get("issue") if isinstance(package.get("issue"), dict) else {}

        index: dict[str, set[str]] = {
            "issue_description": set(),
            "comment": set(),
            "attachment_metadata": set(),
            "relationship": set(),
            "custom_field": set(),
        }

        # Description이 실제로 존재할 때만 issue_description evidence를 허용합니다.
        if isinstance(issue_key, str) and isinstance(issue.get("description"), str):
            if issue["description"].strip():
                index["issue_description"].add(issue_key)

        for item in package.get("comments", []):
            if isinstance(item, dict):
                value = item.get("comment_id")
                if isinstance(value, str) and value.strip():
                    index["comment"].add(value)

        for item in package.get("attachments", []):
            if isinstance(item, dict):
                value = item.get("attachment_id")
                if isinstance(value, str) and value.strip():
                    index["attachment_metadata"].add(value)

        for item in package.get("relationships", []):
            if isinstance(item, dict):
                # v1은 안정적인 Jira relationship_id가 있는 관계만 직접 evidence로 사용합니다.
                value = item.get("relationship_id")
                if isinstance(value, str) and value.strip():
                    index["relationship"].add(value)

        for item in package.get("custom_fields", []):
            if isinstance(item, dict):
                value = item.get("field_id")
                if isinstance(value, str) and value.strip():
                    index["custom_field"].add(value)

        return index

    @staticmethod
    def _load_json_object(path: Path, label: str) -> dict[str, Any]:
        """UTF-8 JSON 파일을 읽고 최상위 객체 형식을 검증합니다."""

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise KnowledgeExtractionValidationError(
                f"{label} JSON을 읽을 수 없습니다: {path}: {exc}"
            ) from exc

        if not isinstance(value, dict):
            raise KnowledgeExtractionValidationError(
                f"{label} JSON 최상위 값은 객체여야 합니다: {path}"
            )
        return value

    @staticmethod
    def _message(
        severity: str,
        code: str,
        path: str,
        message: str,
    ) -> KnowledgeValidationMessage:
        """검증 결과 메시지를 한 형식으로 생성합니다."""

        return KnowledgeValidationMessage(
            severity=severity,
            code=code,
            path=path,
            message=message,
        )
