from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jira_collector.knowledge_db import KnowledgeDbError, connect_database
from jira_collector.retrieval import (
    load_retrieval_mapping,
    load_retrieval_searcher,
    validate_retrieval_artifact,
)


_BUNDLE_METADATA_FILENAME = "publish.bundle.json"
_BUNDLE_METADATA_FIELDS = {
    "processing_run_id",
    "work_item_id",
    "target_knowledge_generation_id",
    "knowledge_generation_ids",
    "source_work_by_generation",
    "faiss_index_id",
    "vector_count",
    "dimension",
    "staged_at",
}


@dataclass(frozen=True)
class RetrievalBundleHead:
    artifact_dir: Path
    processing_run_id: str
    staged_at: str
    generation_ids: frozenset[str]


def active_generation_ids_from_connection(connection) -> frozenset[str]:
    """현재 SQLite read snapshot이 보는 active accepted Generation 집합을 반환합니다."""

    rows = connection.execute(
        """
        SELECT knowledge_generation_id
        FROM knowledge_generation
        WHERE state='active' AND accepted_attempt_id IS NOT NULL
        ORDER BY knowledge_generation_id
        """
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def active_generation_ids(database_path: str | Path) -> frozenset[str]:
    connection = connect_database(database_path)
    try:
        return active_generation_ids_from_connection(connection)
    finally:
        connection.close()


def retrieval_artifact_dir_for_generation_set(
    retrieval_artifact_root: str | Path,
    generation_ids: Iterable[str],
) -> Path:
    """주어진 Generation 집합과 정확히 일치하는 최신 검증 bundle을 선택합니다."""

    expected = frozenset(str(value) for value in generation_ids if str(value))
    if not expected:
        raise KnowledgeDbError("active Knowledge Generation이 아직 없습니다.")

    runs_root = Path(retrieval_artifact_root).expanduser().resolve() / "runs"
    candidates: list[RetrievalBundleHead] = []
    if runs_root.is_dir():
        for artifact_dir in runs_root.iterdir():
            head = _validated_matching_head(artifact_dir, expected)
            if head is not None:
                candidates.append(head)
    if not candidates:
        raise KnowledgeDbError(
            "active Knowledge Generation 집합과 일치하는 Published Retrieval bundle이 없습니다."
        )
    return max(
        candidates,
        key=lambda head: (head.staged_at, head.processing_run_id),
    ).artifact_dir


def active_retrieval_artifact_dir(
    knowledge_database_path: str | Path,
    retrieval_artifact_root: str | Path,
) -> Path:
    """Knowledge DB의 현재 active set과 정확히 맞는 Retrieval bundle을 반환합니다."""

    return retrieval_artifact_dir_for_generation_set(
        retrieval_artifact_root,
        active_generation_ids(knowledge_database_path),
    )


def load_active_retrieval_searcher(
    knowledge_database_path: str | Path,
    retrieval_artifact_root: str | Path,
):
    return load_retrieval_searcher(
        active_retrieval_artifact_dir(
            knowledge_database_path,
            retrieval_artifact_root,
        )
    )


def _validated_matching_head(
    artifact_dir: Path,
    expected: frozenset[str],
) -> RetrievalBundleHead | None:
    if not artifact_dir.is_dir():
        return None
    metadata = _load_metadata(artifact_dir)
    if metadata is None or metadata.generation_ids != expected:
        return None
    try:
        validation = validate_retrieval_artifact(artifact_dir)
        if not validation.passed:
            return None
        mappings = load_retrieval_mapping(artifact_dir)
    except (KnowledgeDbError, OSError):
        return None
    mapped = frozenset(row.knowledge_generation_id for row in mappings)
    return metadata if mapped == expected else None


def _load_metadata(artifact_dir: Path) -> RetrievalBundleHead | None:
    path = artifact_dir / _BUNDLE_METADATA_FILENAME
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or set(document) != _BUNDLE_METADATA_FIELDS:
        return None
    generations = document.get("knowledge_generation_ids")
    if not isinstance(generations, list) or not generations:
        return None
    generation_ids = frozenset(
        value for value in generations if isinstance(value, str) and value
    )
    if len(generation_ids) != len(generations):
        return None
    processing_run_id = document.get("processing_run_id")
    staged_at = document.get("staged_at")
    if not isinstance(processing_run_id, str) or not processing_run_id:
        return None
    if not isinstance(staged_at, str) or not staged_at:
        return None
    return RetrievalBundleHead(
        artifact_dir=artifact_dir,
        processing_run_id=processing_run_id,
        staged_at=staged_at,
        generation_ids=generation_ids,
    )


__all__ = [
    "RetrievalBundleHead",
    "active_generation_ids",
    "active_generation_ids_from_connection",
    "active_retrieval_artifact_dir",
    "load_active_retrieval_searcher",
    "retrieval_artifact_dir_for_generation_set",
]
