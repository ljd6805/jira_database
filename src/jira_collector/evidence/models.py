from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class EvidenceResolutionError(RuntimeError):
    """M10 candidate/Evidence resolve 계약 위반을 나타냅니다."""

    def __init__(self, code: str, knowledge_item_id: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.knowledge_item_id = knowledge_item_id


class StaleKnowledgeError(EvidenceResolutionError):
    """M9 candidate가 더 이상 active accepted Knowledge가 아닐 때 사용합니다."""


class NoUsableEvidenceError(RuntimeError):
    """검색 후보는 있었지만 정상 Evidence Package가 하나도 없을 때 사용합니다."""


@dataclass(frozen=True)
class IssueContext:
    issue_key: str
    status: str | None
    issue_type: str | None


@dataclass(frozen=True)
class ResolvedEvidence:
    knowledge_evidence_id: str
    ordinal: int
    evidence_ref: str
    evidence_type: str
    source_issue_key: str
    source_entity_key: str | None
    text: str | None
    text_format: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class EvidencePackage:
    rank: int
    score: float
    faiss_position: int
    embedding_id: str
    knowledge_item_id: str
    category: str
    statement: str
    issue: IssueContext
    evidence: tuple[ResolvedEvidence, ...]


@dataclass(frozen=True)
class EvidencePackageWarning:
    code: str
    knowledge_item_id: str
    message: str


@dataclass(frozen=True)
class EvidenceBuildResult:
    results: tuple[EvidencePackage, ...]
    warnings: tuple[EvidencePackageWarning, ...]
