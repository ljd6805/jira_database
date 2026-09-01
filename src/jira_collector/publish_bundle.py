from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jira_collector.embedding.validation import validate_embedding_artifact
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval import (
    build_retrieval_artifacts,
    load_retrieval_mapping,
    validate_retrieval_artifact,
)
from jira_collector.state_store import utc_now_iso


_BUNDLE_METADATA_FILENAME = "publish.bundle.json"
_SOURCE_CORPUS_FILENAME = "source.corpus.jsonl"
_SOURCE_EMBEDDING_FILENAME = "source.embeddings.jsonl"


@dataclass(frozen=True)
class RetrievalBundleMetadata:
    processing_run_id: str
    work_item_id: str
    target_knowledge_generation_id: str
    knowledge_generation_ids: tuple[str, ...]
    source_work_by_generation: dict[str, str]
    faiss_index_id: str
    vector_count: int
    dimension: int
    staged_at: str


def stage_retrieval_bundle(
    *,
    artifact_dir: Path,
    embedding_artifact_root: Path,
    work_item_id: str,
    processing_run_id: str,
    target_generation_id: str,
    sources: dict[str, str],
    expected_generations: frozenset[str],
    default_top_k: int,
):
    """모든 active 대상 Generation의 Embedding으로 검증된 immutable bundle을 만듭니다."""

    artifact_dir.mkdir(parents=True, exist_ok=False)
    corpus_path, embedding_path, count, dimension = _merge_embedding_sources(
        artifact_dir,
        embedding_artifact_root,
        sources,
    )
    build_result = build_retrieval_artifacts(
        corpus_path,
        embedding_path,
        artifact_dir,
        expected_count=count,
        expected_dimension=dimension,
        default_top_k=default_top_k,
    )
    validation = validate_retrieval_artifact(
        artifact_dir,
        embedding_path=embedding_path,
        expected_count=count,
        expected_dimension=dimension,
    )
    if not validation.passed:
        raise KnowledgeDbError("G4 Retrieval staging artifact 검증에 실패했습니다.")
    staged = frozenset(
        row.knowledge_generation_id for row in load_retrieval_mapping(artifact_dir)
    )
    if staged != expected_generations:
        raise KnowledgeDbError(
            "G4 Retrieval bundle Generation 집합이 expected active set과 다릅니다."
        )
    _write_bundle_metadata(
        artifact_dir,
        RetrievalBundleMetadata(
            processing_run_id=processing_run_id,
            work_item_id=work_item_id,
            target_knowledge_generation_id=target_generation_id,
            knowledge_generation_ids=tuple(sorted(expected_generations)),
            source_work_by_generation=dict(sorted(sources.items())),
            faiss_index_id=build_result.faiss_index_id,
            vector_count=build_result.vector_count,
            dimension=build_result.dimension,
            staged_at=utc_now_iso(),
        ),
    )
    return build_result


def _merge_embedding_sources(
    artifact_dir: Path,
    embedding_artifact_root: Path,
    sources: dict[str, str],
) -> tuple[Path, Path, int, int]:
    corpus_by_item: dict[str, dict[str, object]] = {}
    embedding_by_item: dict[str, dict[str, object]] = {}
    for generation_id, work_item_id in sorted(sources.items()):
        work_root = embedding_artifact_root / "work" / work_item_id
        corpus_path = work_root / "corpus.jsonl"
        embedding_path = work_root / "embeddings.jsonl"
        validation = validate_embedding_artifact(corpus_path, embedding_path)
        if not validation.passed:
            raise KnowledgeDbError(
                f"Publish source embedding integrity 실패: {work_item_id}"
            )
        _merge_generation_rows(
            generation_id,
            _read_jsonl(corpus_path),
            _read_jsonl(embedding_path),
            corpus_by_item,
            embedding_by_item,
        )

    if not embedding_by_item:
        raise KnowledgeDbError("Publish할 embedding row가 없습니다.")
    dimensions = {int(row["embedding_dimension"]) for row in embedding_by_item.values()}
    if len(dimensions) != 1:
        raise KnowledgeDbError(
            f"Publish snapshot에 embedding dimension이 섞여 있습니다: {sorted(dimensions)}"
        )
    corpus_path = artifact_dir / _SOURCE_CORPUS_FILENAME
    embedding_path = artifact_dir / _SOURCE_EMBEDDING_FILENAME
    _write_jsonl(corpus_path, corpus_by_item.values(), "knowledge_item_id")
    _write_jsonl(embedding_path, embedding_by_item.values(), "knowledge_item_id")
    return corpus_path, embedding_path, len(embedding_by_item), dimensions.pop()


def _merge_generation_rows(
    generation_id: str,
    corpus_rows: list[dict[str, object]],
    embedding_rows: list[dict[str, object]],
    corpus_by_item: dict[str, dict[str, object]],
    embedding_by_item: dict[str, dict[str, object]],
) -> None:
    corpus_items = {str(row.get("knowledge_item_id") or "") for row in corpus_rows}
    embedding_items = {str(row.get("knowledge_item_id") or "") for row in embedding_rows}
    if corpus_items != embedding_items:
        raise KnowledgeDbError(f"Embedding source item set 불일치: {generation_id}")
    for row in corpus_rows:
        _merge_row(generation_id, row, corpus_by_item, "Corpus")
    for row in embedding_rows:
        _merge_row(generation_id, row, embedding_by_item, "Embedding")


def _merge_row(
    generation_id: str,
    row: dict[str, object],
    target: dict[str, dict[str, object]],
    label: str,
) -> None:
    if row.get("knowledge_generation_id") != generation_id:
        raise KnowledgeDbError(f"{label} Generation identity 불일치: {generation_id}")
    item_id = str(row["knowledge_item_id"])
    if item_id in target:
        raise KnowledgeDbError(f"중복 {label} Knowledge Item입니다: {item_id}")
    target[item_id] = row


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise KnowledgeDbError(f"필수 JSONL artifact가 없습니다: {path}")
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise KnowledgeDbError(f"JSONL 파싱 실패: {path}:{line_no}") from exc
        if not isinstance(value, dict):
            raise KnowledgeDbError(f"JSONL row가 객체가 아닙니다: {path}:{line_no}")
        rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]], sort_key: str) -> None:
    ordered = sorted(rows, key=lambda row: str(row[sort_key]))
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in ordered
        ),
        encoding="utf-8",
    )


def _write_bundle_metadata(
    artifact_dir: Path,
    metadata: RetrievalBundleMetadata,
) -> None:
    document = {
        "processing_run_id": metadata.processing_run_id,
        "work_item_id": metadata.work_item_id,
        "target_knowledge_generation_id": metadata.target_knowledge_generation_id,
        "knowledge_generation_ids": list(metadata.knowledge_generation_ids),
        "source_work_by_generation": metadata.source_work_by_generation,
        "faiss_index_id": metadata.faiss_index_id,
        "vector_count": metadata.vector_count,
        "dimension": metadata.dimension,
        "staged_at": metadata.staged_at,
    }
    (artifact_dir / _BUNDLE_METADATA_FILENAME).write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = ["RetrievalBundleMetadata", "stage_retrieval_bundle"]
