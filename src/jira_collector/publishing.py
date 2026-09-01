from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jira_collector.embedding.validation import validate_embedding_artifact
from jira_collector.knowledge_db import KnowledgeDbError, connect_database
from jira_collector.retrieval import (
    build_retrieval_artifacts,
    load_retrieval_mapping,
    load_retrieval_searcher,
    validate_retrieval_artifact,
)
from jira_collector.state_store import StateStore, utc_now_iso


_BUNDLE_METADATA_FILENAME = "publish.bundle.json"
_SOURCE_CORPUS_FILENAME = "source.corpus.jsonl"
_SOURCE_EMBEDDING_FILENAME = "source.embeddings.jsonl"
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


class StalePublishWorkError(KnowledgeDbError):
    """Publish 직전 Work가 더 이상 latest가 아니게 된 경우입니다."""


class SnapshotChangedPublishError(KnowledgeDbError):
    """Retrieval staging 뒤 다른 Publish가 active Generation 집합을 바꾼 경우입니다."""


class PublishedHeadCheckpointError(KnowledgeDbError):
    """Knowledge/FAISS head는 전환됐지만 State checkpoint가 끝나지 않은 경우입니다."""


@dataclass(frozen=True)
class AtomicPublishResult:
    work_item_id: str
    processing_run_id: str
    knowledge_generation_id: str
    faiss_index_id: str
    vector_count: int
    dimension: int
    generation_count: int
    artifact_dir: Path


@dataclass(frozen=True)
class OperationalPublishRunResult:
    processing_run_id: str
    status: str
    selected_count: int
    published_count: int
    failed_count: int
    superseded_count: int
    publish_backlog_before: int
    publish_backlog_after: int
    publish_result: AtomicPublishResult | None


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


class OperationalPublishWorker:
    """Validated Retrieval snapshot을 staging한 뒤 service head를 원자적으로 전환합니다.

    State DB는 의도적으로 WAL mode이므로 Knowledge DB와 ATTACH한 cross-file transaction으로
    묶지 않습니다. 대신 immutable Retrieval bundle을 먼저 만들고, Knowledge DB의 active
    Generation 집합 하나를 service-facing commit point로 사용합니다. State는 그 직후 별도
    WAL transaction으로 published checkpoint를 기록하며, 중간 crash는 같은 Work 재실행으로
    수렴합니다.
    """

    def __init__(
        self,
        state: StateStore,
        knowledge_database_path: str | Path,
        embedding_artifact_root: str | Path,
        retrieval_artifact_root: str | Path,
        *,
        default_top_k: int = 3,
    ) -> None:
        if default_top_k < 1:
            raise ValueError("default_top_k는 1 이상이어야 합니다.")
        self.state = state
        self.knowledge_database_path = Path(knowledge_database_path).resolve()
        self.embedding_artifact_root = Path(embedding_artifact_root).resolve()
        self.retrieval_artifact_root = Path(retrieval_artifact_root).resolve()
        self.default_top_k = default_top_k

    def run(self) -> OperationalPublishRunResult:
        """Publish-ready latest Work 하나를 한 Processing Run으로 처리합니다."""

        backlog_before = self._count_publish_backlog()
        selected = self._list_publish_work(limit=1)
        processing_run_id = self.state.create_processing_run(
            selected_count=len(selected),
            backlog_before=backlog_before,
        )
        if not selected:
            self._finish_empty_run(processing_run_id)
            return self._run_result(
                processing_run_id,
                "completed",
                selected_count=0,
                published_count=0,
                failed_count=0,
                superseded_count=0,
                backlog_before=backlog_before,
                publish_result=None,
            )

        work_item_id = selected[0]
        if not self.state.claim_work_item(work_item_id, processing_run_id):
            self._finish_claim_skip(processing_run_id)
            return self._run_result(
                processing_run_id,
                "completed",
                selected_count=1,
                published_count=0,
                failed_count=0,
                superseded_count=1,
                backlog_before=backlog_before,
                publish_result=None,
            )

        try:
            published = self.process_work(work_item_id, processing_run_id)
        except Exception as exc:
            failed_count, superseded_count, status = self._checkpoint_failure(
                work_item_id,
                processing_run_id,
                exc,
            )
            return self._run_result(
                processing_run_id,
                status,
                selected_count=1,
                published_count=0,
                failed_count=failed_count,
                superseded_count=superseded_count,
                backlog_before=backlog_before,
                publish_result=None,
            )

        return OperationalPublishRunResult(
            processing_run_id=processing_run_id,
            status="completed",
            selected_count=1,
            published_count=1,
            failed_count=0,
            superseded_count=0,
            publish_backlog_before=backlog_before,
            publish_backlog_after=self._count_publish_backlog(),
            publish_result=published,
        )

    def process_work(
        self,
        work_item_id: str,
        processing_run_id: str,
    ) -> AtomicPublishResult:
        work = self.state.get_work_item(work_item_id)
        self._validate_claimed_work(work, processing_run_id)
        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StalePublishWorkError(f"latest Work가 아닙니다: {work_item_id}")
        if not self.state.mark_publish_running(work_item_id):
            raise StalePublishWorkError(
                f"Publish 시작 직전에 stale이 됐습니다: {work_item_id}"
            )

        work = self.state.get_work_item(work_item_id)
        generation_id = str(work["knowledge_generation_id"])
        sources, staged_generations = self._expected_snapshot_sources(work)
        artifact_dir = self.retrieval_artifact_root / "runs" / processing_run_id
        build_result = self._stage_retrieval_bundle(
            artifact_dir,
            work_item_id,
            processing_run_id,
            generation_id,
            sources,
            staged_generations,
        )
        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StalePublishWorkError(
                f"Retrieval staging 후 stale이 됐습니다: {work_item_id}"
            )

        self._commit_head_and_checkpoint_state(
            work_item_id,
            processing_run_id,
            generation_id,
            staged_generations,
        )
        return AtomicPublishResult(
            work_item_id=work_item_id,
            processing_run_id=processing_run_id,
            knowledge_generation_id=generation_id,
            faiss_index_id=build_result.faiss_index_id,
            vector_count=build_result.vector_count,
            dimension=build_result.dimension,
            generation_count=len(staged_generations),
            artifact_dir=artifact_dir,
        )

    def _expected_snapshot_sources(
        self,
        work: dict[str, object],
    ) -> tuple[dict[str, str], frozenset[str]]:
        target_generation = str(work["knowledge_generation_id"])
        target_jira_id = str(work["jira_id"])
        target_work_id = str(work["work_item_id"])
        connection = connect_database(self.knowledge_database_path)
        try:
            target = connection.execute(
                """
                SELECT knowledge_generation_id, jira_id, state, accepted_attempt_id
                FROM knowledge_generation
                WHERE knowledge_generation_id=?
                """,
                (target_generation,),
            ).fetchone()
            _validate_target_generation(target, target_generation, target_jira_id)
            active = connection.execute(
                """
                SELECT knowledge_generation_id, jira_id
                FROM knowledge_generation
                WHERE state='active'
                ORDER BY jira_id, knowledge_generation_id
                """
            ).fetchall()
        finally:
            connection.close()

        sources = {target_generation: target_work_id}
        for row in active:
            generation_id = str(row["knowledge_generation_id"])
            if str(row["jira_id"]) == target_jira_id:
                continue
            sources[generation_id] = self._find_embedding_source_work(generation_id)
        return sources, frozenset(sources)

    def _find_embedding_source_work(self, generation_id: str) -> str:
        with self.state.connect() as connection:
            row = connection.execute(
                """
                SELECT work_item_id
                FROM sync_issue_change
                WHERE knowledge_generation_id=?
                  AND knowledge_status='completed'
                  AND embedding_status='completed'
                ORDER BY
                    CASE WHEN last_published_at IS NULL THEN 1 ELSE 0 END,
                    last_published_at DESC,
                    updated_at DESC,
                    work_item_id
                LIMIT 1
                """,
                (generation_id,),
            ).fetchone()
        if row is None:
            raise KnowledgeDbError(
                "active Generation의 operational embedding source Work를 찾을 수 없습니다: "
                f"{generation_id}"
            )
        return str(row["work_item_id"])

    def _stage_retrieval_bundle(
        self,
        artifact_dir: Path,
        work_item_id: str,
        processing_run_id: str,
        target_generation_id: str,
        sources: dict[str, str],
        expected_generations: frozenset[str],
    ):
        artifact_dir.mkdir(parents=True, exist_ok=False)
        corpus_path, embedding_path, count, dimension = self._merge_embedding_sources(
            artifact_dir,
            sources,
        )
        build_result = build_retrieval_artifacts(
            corpus_path,
            embedding_path,
            artifact_dir,
            expected_count=count,
            expected_dimension=dimension,
            default_top_k=self.default_top_k,
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
        metadata = RetrievalBundleMetadata(
            processing_run_id=processing_run_id,
            work_item_id=work_item_id,
            target_knowledge_generation_id=target_generation_id,
            knowledge_generation_ids=tuple(sorted(expected_generations)),
            source_work_by_generation=dict(sorted(sources.items())),
            faiss_index_id=build_result.faiss_index_id,
            vector_count=build_result.vector_count,
            dimension=build_result.dimension,
            staged_at=utc_now_iso(),
        )
        _write_bundle_metadata(artifact_dir, metadata)
        return build_result

    def _merge_embedding_sources(
        self,
        artifact_dir: Path,
        sources: dict[str, str],
    ) -> tuple[Path, Path, int, int]:
        corpus_by_item: dict[str, dict[str, object]] = {}
        embedding_by_item: dict[str, dict[str, object]] = {}
        for generation_id, work_item_id in sorted(sources.items()):
            work_root = self.embedding_artifact_root / "work" / work_item_id
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

    def _commit_head_and_checkpoint_state(
        self,
        work_item_id: str,
        processing_run_id: str,
        generation_id: str,
        staged_generations: frozenset[str],
    ) -> None:
        knowledge_committed = False
        try:
            with self.state.connect() as state_connection:
                state_connection.execute("BEGIN IMMEDIATE")
                work = _load_publish_work_for_commit(
                    state_connection,
                    work_item_id,
                    processing_run_id,
                )
                self._commit_knowledge_head(
                    generation_id,
                    str(work["jira_id"]),
                    staged_generations,
                )
                knowledge_committed = True
                published_at = utc_now_iso()
                _mark_state_published(
                    state_connection,
                    work_item_id,
                    processing_run_id,
                    published_at,
                )
                backlog_after = _count_publish_backlog_connection(state_connection)
                _finish_publish_run(
                    state_connection,
                    processing_run_id,
                    published_at,
                    backlog_after,
                )
        except Exception as exc:
            if knowledge_committed:
                raise PublishedHeadCheckpointError(
                    "Knowledge/FAISS service head commit 뒤 State published checkpoint가 완료되지 않았습니다. "
                    "같은 Work를 재시도하면 수렴합니다."
                ) from exc
            raise

    def _commit_knowledge_head(
        self,
        generation_id: str,
        jira_id: str,
        staged_generations: frozenset[str],
    ) -> None:
        connection = connect_database(self.knowledge_database_path)
        try:
            with connection:
                target = connection.execute(
                    """
                    SELECT knowledge_generation_id, jira_id, state, accepted_attempt_id
                    FROM knowledge_generation
                    WHERE knowledge_generation_id=?
                    """,
                    (generation_id,),
                ).fetchone()
                _validate_target_generation(target, generation_id, jira_id)
                expected = _expected_generation_set_for_commit(connection, jira_id, generation_id)
                if expected != staged_generations:
                    raise SnapshotChangedPublishError(
                        "Retrieval staging 이후 active Generation 집합이 변경됐습니다. 재시도가 필요합니다."
                    )
                _activate_generation(connection, generation_id, jira_id)
        finally:
            connection.close()

    def _checkpoint_failure(
        self,
        work_item_id: str,
        processing_run_id: str,
        exc: Exception,
    ) -> tuple[int, int, str]:
        message = str(exc)[:2000]
        with self.state.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            work = connection.execute(
                "SELECT * FROM sync_issue_change WHERE work_item_id=?",
                (work_item_id,),
            ).fetchone()
            if work is None:
                raise KeyError(f"work_item_id를 찾을 수 없습니다: {work_item_id}")
            if str(work["work_status"]) == "superseded":
                failed_count, superseded_count, status = 0, 1, "completed"
            else:
                cursor = connection.execute(
                    """
                    UPDATE sync_issue_change
                    SET publish_status='failed', work_status='failed',
                        error_stage='publish', error_message=?, updated_at=?
                    WHERE work_item_id=?
                      AND last_processing_run_id=?
                      AND work_status='running'
                      AND superseded_by_work_item_id IS NULL
                    """,
                    (message, utc_now_iso(), work_item_id, processing_run_id),
                )
                if cursor.rowcount != 1:
                    raise KnowledgeDbError(
                        f"Publish failure checkpoint 실패: {work_item_id}"
                    )
                failed_count, superseded_count, status = 1, 0, "failed"
            backlog_after = _count_publish_backlog_connection(connection)
            _finish_nonpublished_run(
                connection,
                processing_run_id,
                status=status,
                failed_count=failed_count,
                superseded_count=superseded_count,
                backlog_after=backlog_after,
                error_summary=message if failed_count else None,
            )
        return failed_count, superseded_count, status

    def _list_publish_work(self, *, limit: int) -> list[str]:
        with self.state.connect() as connection:
            rows = connection.execute(
                _PUBLISH_BACKLOG_SQL
                + " ORDER BY last_source_committed_at, created_at, work_item_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(row["work_item_id"]) for row in rows]

    def _count_publish_backlog(self) -> int:
        with self.state.connect() as connection:
            return _count_publish_backlog_connection(connection)

    def _finish_empty_run(self, processing_run_id: str) -> None:
        self.state.finish_processing_run(
            processing_run_id,
            run_status="completed",
            published_count=0,
            failed_count=0,
            superseded_count=0,
            backlog_after=self._count_publish_backlog(),
        )

    def _finish_claim_skip(self, processing_run_id: str) -> None:
        self.state.finish_processing_run(
            processing_run_id,
            run_status="completed",
            published_count=0,
            failed_count=0,
            superseded_count=1,
            backlog_after=self._count_publish_backlog(),
        )

    def _run_result(
        self,
        processing_run_id: str,
        status: str,
        *,
        selected_count: int,
        published_count: int,
        failed_count: int,
        superseded_count: int,
        backlog_before: int,
        publish_result: AtomicPublishResult | None,
    ) -> OperationalPublishRunResult:
        return OperationalPublishRunResult(
            processing_run_id=processing_run_id,
            status=status,
            selected_count=selected_count,
            published_count=published_count,
            failed_count=failed_count,
            superseded_count=superseded_count,
            publish_backlog_before=backlog_before,
            publish_backlog_after=self._count_publish_backlog(),
            publish_result=publish_result,
        )

    @staticmethod
    def _validate_claimed_work(
        work: dict[str, object],
        processing_run_id: str,
    ) -> None:
        if work.get("work_status") != "running":
            raise KnowledgeDbError(
                f"Publish claim 상태가 running이 아닙니다: {work.get('work_status')}"
            )
        if work.get("last_processing_run_id") != processing_run_id:
            raise KnowledgeDbError("Publish Processing Run identity가 State와 다릅니다.")
        if work.get("knowledge_status") != "completed":
            raise KnowledgeDbError("Knowledge stage가 completed가 아닙니다.")
        if work.get("embedding_status") != "completed":
            raise KnowledgeDbError("Embedding stage가 completed가 아닙니다.")
        if work.get("publish_status") not in {"pending", "failed"}:
            raise KnowledgeDbError(
                f"Publish 가능한 상태가 아닙니다: {work.get('publish_status')}"
            )
        if work.get("last_source_committed_run_id") != work.get("last_observed_source_run_id"):
            raise KnowledgeDbError("Source Ready Gate가 열리지 않은 Work입니다.")
        if work.get("superseded_by_work_item_id") is not None:
            raise KnowledgeDbError("superseded Work는 Publish 대상이 아닙니다.")
        if not work.get("knowledge_generation_id"):
            raise KnowledgeDbError("State에 knowledge_generation_id가 없습니다.")


_PUBLISH_BACKLOG_SQL = """
SELECT work_item_id
FROM sync_issue_change
WHERE last_source_committed_run_id IS NOT NULL
  AND last_source_committed_run_id = last_observed_source_run_id
  AND work_status IN ('pending','failed')
  AND knowledge_status='completed'
  AND embedding_status='completed'
  AND publish_status IN ('pending','failed')
  AND superseded_by_work_item_id IS NULL
"""


def active_retrieval_artifact_dir(
    knowledge_database_path: str | Path,
    retrieval_artifact_root: str | Path,
) -> Path:
    """Knowledge DB active Generation 집합과 정확히 맞는 검증된 Retrieval bundle을 반환합니다."""

    active_generations = _active_generation_ids(knowledge_database_path)
    if not active_generations:
        raise KnowledgeDbError("active Knowledge Generation이 아직 없습니다.")

    root = Path(retrieval_artifact_root).resolve() / "runs"
    candidates: list[tuple[str, str, Path]] = []
    if root.is_dir():
        for artifact_dir in root.iterdir():
            if not artifact_dir.is_dir():
                continue
            metadata = _try_load_bundle_metadata(artifact_dir)
            if metadata is None:
                continue
            if frozenset(metadata.knowledge_generation_ids) != active_generations:
                continue
            if not _bundle_matches_active_set(artifact_dir, active_generations):
                continue
            candidates.append(
                (metadata.staged_at, metadata.processing_run_id, artifact_dir)
            )
    if not candidates:
        raise KnowledgeDbError(
            "active Knowledge Generation 집합과 일치하는 Published Retrieval bundle이 없습니다."
        )
    return max(candidates, key=lambda value: (value[0], value[1]))[2]


def load_active_retrieval_searcher(
    knowledge_database_path: str | Path,
    retrieval_artifact_root: str | Path,
):
    """현재 service-facing active Generation 집합에 맞는 RetrievalSearcher를 엽니다."""

    return load_retrieval_searcher(
        active_retrieval_artifact_dir(
            knowledge_database_path,
            retrieval_artifact_root,
        )
    )


def _active_generation_ids(database_path: str | Path) -> frozenset[str]:
    connection = connect_database(database_path)
    try:
        rows = connection.execute(
            """
            SELECT knowledge_generation_id
            FROM knowledge_generation
            WHERE state='active' AND accepted_attempt_id IS NOT NULL
            ORDER BY knowledge_generation_id
            """
        ).fetchall()
    finally:
        connection.close()
    return frozenset(str(row[0]) for row in rows)


def _validate_target_generation(
    row: sqlite3.Row | None,
    generation_id: str,
    jira_id: str,
) -> None:
    if row is None or str(row["jira_id"]) != jira_id:
        raise KnowledgeDbError(
            f"State와 Knowledge Generation identity가 다릅니다: {generation_id}"
        )
    if row["accepted_attempt_id"] is None:
        raise KnowledgeDbError("Publish 대상 Generation에 accepted_attempt_id가 없습니다.")
    if str(row["state"]) not in {"candidate", "active", "historical"}:
        raise KnowledgeDbError(
            f"Publish 가능한 Generation 상태가 아닙니다: {row['state']}"
        )


def _load_publish_work_for_commit(
    connection: sqlite3.Connection,
    work_item_id: str,
    processing_run_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT work_item_id, jira_id, knowledge_generation_id,
               last_processing_run_id, work_status, knowledge_status,
               embedding_status, publish_status,
               last_source_committed_run_id, last_observed_source_run_id,
               superseded_by_work_item_id
        FROM sync_issue_change
        WHERE work_item_id=?
        """,
        (work_item_id,),
    ).fetchone()
    if row is None:
        raise StalePublishWorkError(f"Publish Work를 찾을 수 없습니다: {work_item_id}")
    valid = (
        row["last_processing_run_id"] == processing_run_id
        and row["work_status"] == "running"
        and row["knowledge_status"] == "completed"
        and row["embedding_status"] == "completed"
        and row["publish_status"] == "running"
        and row["last_source_committed_run_id"] is not None
        and row["last_source_committed_run_id"] == row["last_observed_source_run_id"]
        and row["superseded_by_work_item_id"] is None
    )
    if not valid:
        raise StalePublishWorkError(
            f"Service head commit 직전 Work가 stale입니다: {work_item_id}"
        )
    return row


def _expected_generation_set_for_commit(
    connection: sqlite3.Connection,
    target_jira_id: str,
    target_generation_id: str,
) -> frozenset[str]:
    rows = connection.execute(
        """
        SELECT knowledge_generation_id
        FROM knowledge_generation
        WHERE state='active' AND jira_id<>?
        """,
        (target_jira_id,),
    ).fetchall()
    result = {str(row[0]) for row in rows}
    result.add(target_generation_id)
    return frozenset(result)


def _activate_generation(
    connection: sqlite3.Connection,
    generation_id: str,
    jira_id: str,
) -> None:
    connection.execute(
        """
        UPDATE knowledge_generation
        SET state='historical'
        WHERE jira_id=? AND state='active' AND knowledge_generation_id<>?
        """,
        (jira_id, generation_id),
    )
    cursor = connection.execute(
        """
        UPDATE knowledge_generation
        SET state='active'
        WHERE knowledge_generation_id=?
          AND accepted_attempt_id IS NOT NULL
          AND state IN ('candidate','active','historical')
        """,
        (generation_id,),
    )
    if cursor.rowcount != 1:
        raise KnowledgeDbError(f"Generation active 전환 실패: {generation_id}")


def _mark_state_published(
    connection: sqlite3.Connection,
    work_item_id: str,
    processing_run_id: str,
    published_at: str,
) -> None:
    cursor = connection.execute(
        """
        UPDATE sync_issue_change
        SET work_status='published', publish_status='published',
            error_stage=NULL, error_message=NULL,
            last_published_at=?, updated_at=?
        WHERE work_item_id=?
          AND last_processing_run_id=?
          AND work_status='running'
          AND knowledge_status='completed'
          AND embedding_status='completed'
          AND publish_status='running'
          AND last_source_committed_run_id=last_observed_source_run_id
          AND superseded_by_work_item_id IS NULL
        """,
        (published_at, published_at, work_item_id, processing_run_id),
    )
    if cursor.rowcount != 1:
        raise StalePublishWorkError(f"State published 전환 실패: {work_item_id}")


def _finish_publish_run(
    connection: sqlite3.Connection,
    processing_run_id: str,
    finished_at: str,
    backlog_after: int,
) -> None:
    cursor = connection.execute(
        """
        UPDATE processing_run
        SET finished_at=?, run_status='completed',
            published_count=1, failed_count=0, superseded_count=0,
            backlog_after=?, error_summary=NULL
        WHERE processing_run_id=?
          AND run_status='running'
          AND selected_count=1
        """,
        (finished_at, backlog_after, processing_run_id),
    )
    if cursor.rowcount != 1:
        raise KnowledgeDbError(
            f"Publish Processing Run finalize 실패: {processing_run_id}"
        )


def _finish_nonpublished_run(
    connection: sqlite3.Connection,
    processing_run_id: str,
    *,
    status: str,
    failed_count: int,
    superseded_count: int,
    backlog_after: int,
    error_summary: str | None,
) -> None:
    cursor = connection.execute(
        """
        UPDATE processing_run
        SET finished_at=?, run_status=?,
            published_count=0, failed_count=?, superseded_count=?,
            backlog_after=?, error_summary=?
        WHERE processing_run_id=? AND run_status='running'
        """,
        (
            utc_now_iso(),
            status,
            failed_count,
            superseded_count,
            backlog_after,
            error_summary,
            processing_run_id,
        ),
    )
    if cursor.rowcount != 1:
        raise KnowledgeDbError(
            f"Publish failure Processing Run finalize 실패: {processing_run_id}"
        )


def _count_publish_backlog_connection(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM (" + _PUBLISH_BACKLOG_SQL + ")"
    ).fetchone()
    return int(row[0]) if row is not None else 0


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
        if row.get("knowledge_generation_id") != generation_id:
            raise KnowledgeDbError(f"Corpus Generation identity 불일치: {generation_id}")
        item_id = str(row["knowledge_item_id"])
        if item_id in corpus_by_item:
            raise KnowledgeDbError(f"중복 Knowledge Item입니다: {item_id}")
        corpus_by_item[item_id] = row
    for row in embedding_rows:
        if row.get("knowledge_generation_id") != generation_id:
            raise KnowledgeDbError(f"Embedding Generation identity 불일치: {generation_id}")
        item_id = str(row["knowledge_item_id"])
        if item_id in embedding_by_item:
            raise KnowledgeDbError(f"중복 Embedding Knowledge Item입니다: {item_id}")
        embedding_by_item[item_id] = row


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


def _try_load_bundle_metadata(artifact_dir: Path) -> RetrievalBundleMetadata | None:
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
    sources = document.get("source_work_by_generation")
    if not isinstance(generations, list) or not generations:
        return None
    if not all(isinstance(value, str) and value for value in generations):
        return None
    if not isinstance(sources, dict) or not all(
        isinstance(key, str)
        and isinstance(value, str)
        and key
        and value
        for key, value in sources.items()
    ):
        return None
    try:
        return RetrievalBundleMetadata(
            processing_run_id=_required_metadata_text(document, "processing_run_id"),
            work_item_id=_required_metadata_text(document, "work_item_id"),
            target_knowledge_generation_id=_required_metadata_text(
                document,
                "target_knowledge_generation_id",
            ),
            knowledge_generation_ids=tuple(generations),
            source_work_by_generation=dict(sources),
            faiss_index_id=_required_metadata_text(document, "faiss_index_id"),
            vector_count=_required_metadata_int(document, "vector_count"),
            dimension=_required_metadata_int(document, "dimension"),
            staged_at=_required_metadata_text(document, "staged_at"),
        )
    except ValueError:
        return None


def _bundle_matches_active_set(
    artifact_dir: Path,
    active_generations: frozenset[str],
) -> bool:
    try:
        validation = validate_retrieval_artifact(artifact_dir)
        if not validation.passed:
            return False
        mappings = load_retrieval_mapping(artifact_dir)
    except (KnowledgeDbError, OSError):
        return False
    mapped = frozenset(row.knowledge_generation_id for row in mappings)
    return mapped == active_generations


def _required_metadata_text(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"metadata {key}가 비어 있습니다.")
    return value.strip()


def _required_metadata_int(document: dict[str, object], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"metadata {key}가 잘못됐습니다.")
    return value


__all__ = [
    "AtomicPublishResult",
    "OperationalPublishRunResult",
    "OperationalPublishWorker",
    "PublishedHeadCheckpointError",
    "RetrievalBundleMetadata",
    "SnapshotChangedPublishError",
    "StalePublishWorkError",
    "active_retrieval_artifact_dir",
    "load_active_retrieval_searcher",
]
