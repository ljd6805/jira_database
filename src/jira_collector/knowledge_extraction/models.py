from __future__ import annotations

from dataclasses import dataclass


class KnowledgeExtractionValidationError(ValueError):
    """Knowledge Input 또는 Agent 출력 파일 자체를 안전하게 읽을 수 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class KnowledgeValidationMessage:
    """Validator가 발견한 오류 또는 경고 한 건을 구조적으로 표현합니다."""

    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class KnowledgeExtractionValidationResult:
    """Agent Knowledge 출력의 구조·evidence 검증 결과를 보관합니다."""

    valid: bool
    errors: tuple[KnowledgeValidationMessage, ...] = ()
    warnings: tuple[KnowledgeValidationMessage, ...] = ()

    @property
    def error_count(self) -> int:
        """검증 오류 개수를 반환합니다."""

        return len(self.errors)

    @property
    def warning_count(self) -> int:
        """검증 경고 개수를 반환합니다."""

        return len(self.warnings)
