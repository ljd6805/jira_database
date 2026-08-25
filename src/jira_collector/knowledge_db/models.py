from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class KnowledgeDbError(RuntimeError):
    """Knowledge DB materialization 계약 위반을 나타냅니다."""


@dataclass(frozen=True)
class MaterializationResult:
    """한 Run을 SQLite로 materialize한 결과 요약입니다."""

    run_id: str
    database_path: Path
    issue_count: int
    generation_count: int
    attempt_count: int
    knowledge_item_count: int
    evidence_count: int
    review_count: int
