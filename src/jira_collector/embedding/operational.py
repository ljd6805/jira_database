from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jira_collector.knowledge_db import KnowledgeDbError, connect_database
from jira_collector.state_store import StateStore

from .artifact import export_embedding_artifact_atomic
from .client import OpenAICompatibleEmbeddingClient, partition_batches
from .config import EmbeddingRuntimeSettings
from .corpus import CORPUS_SCHEMA_VERSION, TEXT_PROFILE_STATEMENT_V1, EmbeddingCorpusRow
from .runner import embed_corpus_rows


class _RateLimiter(Protocol):
    def wait(self) -> None: ...


class StaleEmbeddingWorkError(KnowledgeDbError):
    """Embedding 처리 중 Work Item이 latest가 아니게 된 경우입니다."""


@dataclass(frozen=True)
class OperationalEmbeddingResult:
    work_item_id: str
    knowledge_generation_id: str
    corpus_rows: int
    embedding_rows: int
    batch_count: int
    embedding_dimension: int
    embedding_contract_hash: str
    corpus_path: Path
    embedding_path: Path


_CATEGORY_ORDER = (
    "issue_summary",
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
)

_GENERATION_CORPUS_SQL = """
SELECT
    ki.knowledge_item_id,
    ki.knowledge_attempt_id,
    ka.knowledge_generation_id,
    kg.issue_version_id,
    kg.jira_id,
    ki.category,
    ki.ordinal,
    ki.statement,
    kg.state AS generation_state
FROM knowledge_generation AS kg
JOIN knowledge_attempt AS ka
  ON ka.knowledge_attempt_id = kg.accepted_attempt_id
 AND ka.knowledge_generation_id = kg.knowledge_generation_id
JOIN knowledge_item AS ki
  ON ki.knowledge_attempt_id = ka.knowledge_attempt_id
WHERE kg.knowledge_generation_id = ?
  AND kg.accepted_attempt_id IS NOT NULL
  AND ka.content_available = 1
ORDER BY
    CASE ki.category
        WHEN 'issue_summary' THEN 0
        WHEN 'problem_or_goal' THEN 1
        WHEN 'key_findings' THEN 2
        WHEN 'actions_and_decisions' THEN 3
        WHEN 'outcomes' THEN 4
        WHEN 'open_items' THEN 5
        ELSE 99
    END,
    ki.ordinal,
    ki.knowledge_item_id
"""


def load_generation_embedding_corpus(
    database_path: str | Path,
    knowledge_generation_id: str,
    *,
    text_profile: str = TEXT_PROFILE_STATEMENT_V1,
) -> tuple[EmbeddingCorpusRow, ...]:
    """candidate/active Generation 하나의 accepted Knowledge Item만 읽습니다."""

    if text_profile != TEXT_PROFILE_STATEMENT_V1:
        raise ValueError(f"지원하지 않는 embedding text profile입니다: {text_profile}")
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            _GENERATION_CORPUS_SQL,
            (knowledge_generation_id,),
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        raise KnowledgeDbError(
            f"Embedding 대상 accepted Knowledge Item이 없습니다: {knowledge_generation_id}"
        )
    states = {str(row["generation_state"]) for row in rows}
    if not states.issubset({"candidate", "active"}):
        raise KnowledgeDbError(
            "Embedding 대상 Generation 상태가 candidate/active가 아닙니다: "
            f"generation={knowledge_generation_id}, states={sorted(states)}"
        )

    result: list[EmbeddingCorpusRow] = []
    for row in rows:
        category = str(row["category"])
        if category not in _CATEGORY_ORDER:
            raise KnowledgeDbError(f"지원하지 않는 Knowledge category입니다: {category}")
        text = str(row["statement"]).strip()
        if not text:
            raise KnowledgeDbError(
                f"Embedding statement가 비어 있습니다: {row['knowledge_item_id']}"
            )
        result.append(
            EmbeddingCorpusRow(
                corpus_schema_version=CORPUS_SCHEMA_VERSION,
                text_profile=text_profile,
                knowledge_item_id=str(row["knowledge_item_id"]),
                knowledge_attempt_id=str(row["knowledge_attempt_id"]),
                knowledge_generation_id=str(row["knowledge_generation_id"]),
                issue_version_id=str(row["issue_version_id"]),
                jira_id=str(row["jira_id"]),
                category=category,
                ordinal=int(row["ordinal"]),
                embedding_text=text,
                embedding_text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return tuple(result)


def export_generation_corpus_atomic(
    rows: tuple[EmbeddingCorpusRow, ...],
    output_path: str | Path,
) -> Path:
    """Work 단위 corpus를 부분 파일 노출 없이 저장합니다."""

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    payload = "".join(
        json.dumps(
            row.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


class OperationalEmbeddingWorker:
    """Loop B의 latest-only incremental BGE-M3 stage입니다."""

    def __init__(
        self,
        state: StateStore,
        knowledge_database_path: str | Path,
        artifact_root: str | Path,
        settings: EmbeddingRuntimeSettings,
        *,
        client: OpenAICompatibleEmbeddingClient | None = None,
        rate_limiter: _RateLimiter | None = None,
    ) -> None:
        self.state = state
        self.knowledge_database_path = Path(knowledge_database_path).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.settings = settings
        self.client = client
        self.rate_limiter = rate_limiter

    def process_work(self, work_item_id: str) -> OperationalEmbeddingResult:
        work = self.state.get_work_item(work_item_id)
        self._validate_work(work)
        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StaleEmbeddingWorkError(f"latest Work가 아닙니다: {work_item_id}")
        if not self.state.mark_embedding_running(work_item_id):
            raise StaleEmbeddingWorkError(
                f"Embedding 시작 직전에 stale이 됐습니다: {work_item_id}"
            )

        try:
            generation_id = str(work["knowledge_generation_id"])
            corpus_rows = load_generation_embedding_corpus(
                self.knowledge_database_path,
                generation_id,
                text_profile=self.settings.text_profile,
            )
            work_root = self.artifact_root / "work" / work_item_id
            corpus_path = export_generation_corpus_atomic(
                corpus_rows,
                work_root / "corpus.jsonl",
            )

            artifact_rows = embed_corpus_rows(
                corpus_rows,
                self.settings,
                client=self.client,
                rate_limiter=self.rate_limiter,
            )
            if not self.state.work_item_is_latest(work_item_id, log_stale=True):
                raise StaleEmbeddingWorkError(
                    f"Embedding API 응답 후 stale이 됐습니다: {work_item_id}"
                )

            embedding_path = export_embedding_artifact_atomic(
                artifact_rows,
                work_root / "embeddings.jsonl",
            )
            if not self.state.work_item_is_latest(work_item_id, log_stale=True):
                raise StaleEmbeddingWorkError(
                    f"Embedding artifact 저장 후 stale이 됐습니다: {work_item_id}"
                )
            if not self.state.mark_embedding_completed(work_item_id):
                raise StaleEmbeddingWorkError(
                    f"Embedding checkpoint 직전에 stale이 됐습니다: {work_item_id}"
                )

            return OperationalEmbeddingResult(
                work_item_id=work_item_id,
                knowledge_generation_id=generation_id,
                corpus_rows=len(corpus_rows),
                embedding_rows=len(artifact_rows),
                batch_count=len(partition_batches(corpus_rows, self.settings.batch_size)),
                embedding_dimension=self.settings.dimension,
                embedding_contract_hash=artifact_rows[0].embedding_contract_hash,
                corpus_path=corpus_path,
                embedding_path=embedding_path,
            )
        except Exception as exc:
            self.state.mark_work_failed(
                work_item_id,
                stage="embedding",
                error_message=str(exc),
            )
            raise

    @staticmethod
    def _validate_work(work: dict[str, object]) -> None:
        if work.get("knowledge_status") != "completed":
            raise KnowledgeDbError("Knowledge stage가 completed가 아닙니다.")
        if work.get("embedding_status") not in {"pending", "failed", "running"}:
            raise KnowledgeDbError(
                f"Embedding 가능한 상태가 아닙니다: {work.get('embedding_status')}"
            )
        if work.get("last_source_committed_run_id") != work.get("last_observed_source_run_id"):
            raise KnowledgeDbError("Source Ready Gate가 열리지 않은 Work입니다.")
        if work.get("superseded_by_work_item_id") is not None:
            raise KnowledgeDbError("superseded Work는 Embedding 대상이 아닙니다.")
        generation_id = work.get("knowledge_generation_id")
        if not isinstance(generation_id, str) or not generation_id.strip():
            raise KnowledgeDbError("State에 knowledge_generation_id가 없습니다.")


__all__ = [
    "OperationalEmbeddingResult",
    "OperationalEmbeddingWorker",
    "StaleEmbeddingWorkError",
    "export_generation_corpus_atomic",
    "load_generation_embedding_corpus",
]
