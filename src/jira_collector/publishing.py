from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from jira_collector.knowledge_db import KnowledgeDbError, connect_database
from jira_collector.publish_bundle import RetrievalBundleMetadata, stage_retrieval_bundle
from jira_collector.retrieval_head import (
    active_retrieval_artifact_dir,
    load_active_retrieval_searcher,
)
from jira_collector.state_store import StateStore, utc_now_iso


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


class OperationalPublishWorker:
    """Immutable Retrieval snapshot을 staging한 뒤 Knowledge head와 State를 전환합니다.

    State DB는 WAL이므로 Knowledge DB와 cross-file transaction으로 묶지 않습니다.
    Retrieval bundle을 먼저 완성하고 Knowledge DB의 active Generation 집합을 service-facing
    commit point로 사용합니다. State checkpoint 실패는 같은 Work 재실행으로 수렴합니다.
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
            return self._result(
                processing_run_id,
                "completed",
                0,
                0,
                0,
                0,
                backlog_before,
                None,
            )

        work_item_id = selected[0]
        if not self.state.claim_work_item(work_item_id, processing_run_id):
            self._finish_claim_skip(processing_run_id)
            return self._result(
                processing_run_id,
                "completed",
                1,
                0,
                0,
                1,
                backlog_before,
                None,
            )

        try:
            published = self.process_work(work_item_id, processing_run_id)
        except Exception as exc:
            failed, superseded, status = self._checkpoint_failure(
                work_item_id,
                processing_run_id,
                exc,
            )
            return self._result(
                processing_run_id,
                status,
                1,
                0,
                failed,
                superseded,
                backlog_before,
                None,
            )

        return self._result(
            processing_run_id,
            "completed",
            1,
            1,
            0,
            0,
            backlog_before,
            published,
        )

    def process_work(
        self,
        work_item_id: str,
        processing_run_id: str,
    ) -> AtomicPublishResult:
        """Claim된 Work를 staging → latest re-check → service head commit까지 처리합니다."""

        work = self.state.get_work_item(work_item_id)
        self._validate_claimed_work(work, processing_run_id)
        self._require_latest(work_item_id, "Publish 시작 전")
        if not self.state.mark_publish_running(work_item_id):
            raise StalePublishWorkError(
                f"Publish 시작 직전에 stale이 됐습니다: {work_item_id}"
            )

        work = self.state.get_work_item(work_item_id)
        generation_id = str(work["knowledge_generation_id"])
        sources, generations = self._expected_snapshot_sources(work)
        artifact_dir = self.retrieval_artifact_root / "runs" / processing_run_id
        build_result = self._stage_retrieval_bundle(
            artifact_dir,
            work_item_id,
            processing_run_id,
            generation_id,
            sources,
            generations,
        )
        self._require_latest(work_item_id, "Retrieval staging 후")
        self._commit_head_and_checkpoint_state(
            work_item_id,
            processing_run_id,
            generation_id,
            generations,
        )
        return AtomicPublishResult(
            work_item_id=work_item_id,
            processing_run_id=processing_run_id,
            knowledge_generation_id=generation_id,
            faiss_index_id=build_result.faiss_index_id,
            vector_count=build_result.vector_count,
            dimension=build_result.dimension,
            generation_count=len(generations),
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
            if str(row["jira_id"]) != target_jira_id:
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
        """테스트에서 staging/동시 Publish 경계를 주입할 수 있게 둔 얇은 wrapper입니다."""

        return stage_retrieval_bundle(
            artifact_dir=artifact_dir,
            embedding_artifact_root=self.embedding_artifact_root,
            work_item_id=work_item_id,
            processing_run_id=processing_run_id,
            target_generation_id=target_generation_id,
            sources=sources,
            expected_generations=expected_generations,
            default_top_k=self.default_top_k,
        )

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
                _finish_publish_run(
                    state_connection,
                    processing_run_id,
                    published_at,
                    _count_publish_backlog_connection(state_connection),
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
                expected = _expected_generation_set_for_commit(
                    connection,
                    jira_id,
                    generation_id,
                )
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
                "SELECT work_status FROM sync_issue_change WHERE work_item_id=?",
                (work_item_id,),
            ).fetchone()
            if work is None:
                raise KeyError(f"work_item_id를 찾을 수 없습니다: {work_item_id}")
            if str(work["work_status"]) == "superseded":
                failed, superseded, status = 0, 1, "completed"
            else:
                _mark_publish_failed(
                    connection,
                    work_item_id,
                    processing_run_id,
                    message,
                )
                failed, superseded, status = 1, 0, "failed"
            _finish_nonpublished_run(
                connection,
                processing_run_id,
                status=status,
                failed_count=failed,
                superseded_count=superseded,
                backlog_after=_count_publish_backlog_connection(connection),
                error_summary=message if failed else None,
            )
        return failed, superseded, status

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

    def _result(
        self,
        processing_run_id: str,
        status: str,
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

    def _require_latest(self, work_item_id: str, point: str) -> None:
        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StalePublishWorkError(f"{point} latest Work가 아닙니다: {work_item_id}")

    @staticmethod
    def _validate_claimed_work(
        work: dict[str, object],
        processing_run_id: str,
    ) -> None:
        _validate_claimed_work(work, processing_run_id)


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


def _validate_claimed_work(work: dict[str, object], processing_run_id: str) -> None:
    checks = (
        (work.get("work_status") == "running", "Publish claim 상태가 running이 아닙니다."),
        (
            work.get("last_processing_run_id") == processing_run_id,
            "Publish Processing Run identity가 State와 다릅니다.",
        ),
        (work.get("knowledge_status") == "completed", "Knowledge stage가 completed가 아닙니다."),
        (work.get("embedding_status") == "completed", "Embedding stage가 completed가 아닙니다."),
        (
            work.get("publish_status") in {"pending", "failed"},
            f"Publish 가능한 상태가 아닙니다: {work.get('publish_status')}",
        ),
        (
            work.get("last_source_committed_run_id") == work.get("last_observed_source_run_id"),
            "Source Ready Gate가 열리지 않은 Work입니다.",
        ),
        (work.get("superseded_by_work_item_id") is None, "superseded Work는 Publish 대상이 아닙니다."),
        (bool(work.get("knowledge_generation_id")), "State에 knowledge_generation_id가 없습니다."),
    )
    for passed, message in checks:
        if not passed:
            raise KnowledgeDbError(message)


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


def _mark_publish_failed(
    connection: sqlite3.Connection,
    work_item_id: str,
    processing_run_id: str,
    message: str,
) -> None:
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
        raise KnowledgeDbError(f"Publish failure checkpoint 실패: {work_item_id}")


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
