from __future__ import annotations

from collections.abc import Sequence

from jira_collector.retrieval import RetrievalCandidate

from .models import (
    EvidenceBuildResult,
    EvidencePackageWarning,
    EvidenceResolutionError,
    NoUsableEvidenceError,
)
from .resolver import EvidenceResolver


class CandidateEvidenceBuilder:
    """M9 후보들을 Evidence Package로 만들고 깨진 후보를 격리합니다."""

    def __init__(self, resolver: EvidenceResolver) -> None:
        self._resolver = resolver

    def build(self, candidates: Sequence[RetrievalCandidate]) -> EvidenceBuildResult:
        results = []
        warnings = []
        for candidate in candidates:
            try:
                results.append(self._resolver.resolve_candidate(candidate))
            except EvidenceResolutionError as exc:
                warnings.append(
                    EvidencePackageWarning(
                        code=exc.code,
                        knowledge_item_id=exc.knowledge_item_id,
                        message=str(exc),
                    )
                )

        if candidates and not results:
            codes = ", ".join(warning.code for warning in warnings)
            raise NoUsableEvidenceError(
                f"검색 후보는 있었지만 사용 가능한 Evidence Package가 없습니다: {codes}"
            )
        return EvidenceBuildResult(results=tuple(results), warnings=tuple(warnings))
