from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


ID_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class KnowledgeContract:
    """Knowledge Generation identity에 포함되는 최소 extraction contract입니다."""

    knowledge_schema_version: str
    skill_version: str
    runtime_version: str
    model_profile: str

    def logical_hash(self) -> str:
        """동일 contract가 항상 같은 logical hash를 만들도록 canonicalize합니다."""

        return _logical_id(
            "kc_",
            "knowledge_contract",
            {
                "knowledge_schema_version": self.knowledge_schema_version,
                "skill_version": self.skill_version,
                "runtime_version": self.runtime_version,
                "model_profile": self.model_profile,
            },
        )


def canonical_json(value: Any) -> str:
    """M6에서 고정한 canonical JSON 문자열을 만듭니다."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(value: Any) -> str:
    """Artifact 내용 비교에 사용하는 SHA-256 hash를 반환합니다."""

    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def issue_version_id(jira_id: str, source_hash: str) -> str:
    """Jira identity와 semantic source hash에서 immutable Version ID를 만듭니다."""

    return _logical_id(
        "iv_",
        "issue_version",
        {"jira_id": jira_id, "source_hash": source_hash},
    )


def knowledge_generation_id(version_id: str, contract_hash: str) -> str:
    """Issue Version + Knowledge Contract의 retry lineage ID를 만듭니다."""

    return _logical_id(
        "kg_",
        "knowledge_generation",
        {
            "issue_version_id": version_id,
            "knowledge_contract_hash": contract_hash,
        },
    )


def knowledge_attempt_id(generation_id: str, attempt_no: int) -> str:
    """Generation 내부의 immutable retry Attempt ID를 만듭니다."""

    if attempt_no < 1:
        raise ValueError("attempt_no는 1 이상이어야 합니다.")
    return _logical_id(
        "ka_",
        "knowledge_attempt",
        {"knowledge_generation_id": generation_id, "attempt_no": attempt_no},
    )


def knowledge_item_id(attempt_id: str, category: str, ordinal: int) -> str:
    """Attempt 내부 category 위치를 Knowledge Item identity로 사용합니다."""

    if ordinal < 0:
        raise ValueError("ordinal은 0 이상이어야 합니다.")
    return _logical_id(
        "ki_",
        "knowledge_item",
        {
            "knowledge_attempt_id": attempt_id,
            "category": category,
            "ordinal": ordinal,
        },
    )


def knowledge_evidence_id(
    item_id: str,
    ordinal: int,
    evidence_ref: str,
) -> str:
    """Knowledge Item 안에서 Evidence의 exact reference와 순서를 식별합니다."""

    if ordinal < 0:
        raise ValueError("ordinal은 0 이상이어야 합니다.")
    return _logical_id(
        "ke_",
        "knowledge_evidence",
        {
            "knowledge_item_id": item_id,
            "ordinal": ordinal,
            "evidence_ref": evidence_ref,
        },
    )


def _logical_id(prefix: str, kind: str, material: Mapping[str, Any]) -> str:
    """Entity kind와 version을 포함한 full SHA-256 logical ID를 생성합니다."""

    value = {
        "id_schema_version": ID_SCHEMA_VERSION,
        "kind": kind,
        **material,
    }
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return prefix + digest
