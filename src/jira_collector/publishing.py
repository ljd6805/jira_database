from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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
_ROLLBACK_JOURNAL_MODES = {"delete", "persist", "truncate"}


class StalePublishWorkError(KnowledgeDbError):
    """Publish 직전 Work가 latest가 아니게 된 경우입니다."""


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
    """Validated Retrieval bundle과 Knowledge/State head를 한 commit 경계로 전환합니다."""

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
        """Publish-ready Work 하나를 하나의 Processing Run으로 처리합니다."""

        backlog_before = self._count_publish_backlog()
        selected = self._list_publish_work(limit=1)
        processing_run_id = self.state.create_processing_run(
            selected_count=len(selected),
            backlog_before=backlog_before,
        )
        if not selected:
            self._finish_nonpublished_run(
                processing_run_id,
                run_status="completed",
                failed_count=0,
                superseded_count=0,
            )
            return self._run_result(
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
            self._finish_nonpublished_run(
                processing_run_id,
                run_status="completed",
                failed_count=0,
                superseded_count=1,
            )
            return self._run_result(
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
        except StalePublishWorkError:
            self._finish_nonpublished_run(
                processing_run_id,
                run_status="completed",
                failed_count=0,
                superseded_count=1,
            )
            return self._run_result(
                processing_run_id,
                "completed",
                1,
                0,
                0,
                1,
                backlog_before,
                None,
            )
        except Exception as exc:
            work = self.state.get_work_item(work_item_id)
            if work.get("work_status") != "superseded":
                self.state.mark_work_failed(
                    work_item_id,
                    stage="publish",
                    error_message=str(exc),
                )
                failed_count, superseded_count = 1, 0
                status = "failed"
            else:
                failed_count, superseded_count = 0, 1
                status = "completed"
            self._finish_nonpublished_run(
                processing_run_id,
                run_status=status,
                failed_count=failed_count,
                superseded_count=superseded_count,
                error_summary=str(exc) if failed_count else None,
            )
            return self._run_result(
                processing_run_id,
                status,
                1,
                0,
                failed_count,
                superseded_count,
                backlog_before,
                None,
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
        sources, expected_generations = self._expected_snapshot_sources(work)
        artifact_dir = self.retrieval_artifact_root / "runs" / processing_run_id
        build_result = self._stage_retrieval_bundle(
            artifact_dir,
            work_item_id,
            processing_run_id,
            generation_id,
            sources,
            expected_generations,
        )

        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StalePublishWorkError(
                f"Retrieval staging 후 stale이 됐습니다: {work_item_id}"
            )
        self._atomic_commit(
            work_item_id,
            processing_run_id,
            generation_id,
            expected_generations,
        )
        return AtomicPublishResult(
            work_item_id=work_item_id,
            processing_run_id=processing_run_id,
            knowledge_generation_id=generation_id,
            faiss_index_id=build_result.faiss_index_id,
            vector_count=build_result.vector_count,
            dimension=build_result.dimension,
            generation_count=len(expected_generations),
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
            if target is None or str(target["jira_id"]) != target_jira_id:
                raise KnowledgeDbError("State와 Knowledge Generation identity가 다릅니다.")
            if target["accepted_attempt_id"] is None:
                raise KnowledgeDbError("Publish 대상 Generation에 accepted_attempt_id가 없습니다.")
            if str(target["state"]) not in {"candidate", "active", "historical"}:
                raise KnowledgeDbError(
                    f"Publish 가능한 Generation 상태가 아닙니다: {target['state']}"
                )
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
        validation = validate_retrieval_artifact(artifact_dir)
        if not validation.passed:
            raise KnowledgeDbError("G4 Retrieval staging artifact 검증에 실패했습니다.")
        staged_generations = frozenset(
            row.knowledge_generation_id for row in load_retrieval_mapping(artifact_dir)
        )
        if staged_generations != expected_generations:
            raise KnowledgeDbError(
                "G4 Retrieval bundle Generation 집합이 expected active set과 다릅니다."
            )
        metadata = {
            "processing_run_id": processing_run_id,
            "work_item_id": work_item_id,
            "target_knowledge_generation_id": target_generation_id,
            "knowledge_generation_ids": sorted(expected_generations),
            "source_work_by_generation": dict(sorted(sources.items())),
            "faiss_index_id": build_result.faiss_index_id,
            "vector_count": build_result.vector_count,
            "dimension": build_result.dimension,
        }
        (artifact_dir / _BUNDLE_METADATA_FILENAME).write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
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
            corpus_rows = _read_jsonl(corpus_path)
            embedding_rows = _read_jsonl(embedding_path)
            _merge_generation_rows(
                generation_id,
                corpus_rows,
                embedding_rows,
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
        _write_jsonl(embedding_path, embedding_by_item.values(), "embedding_id")
        return corpus_path, embedding_path, len(embedding_by_item), dimensions.pop()

    def _atomic_commit(
        self,
        work_item_id: str,
        processing_run_id: str,
        generation_id: str,
        staged_generations: frozenset[str],
    ) -> None:
        connection = sqlite3.connect(self.knowledge_database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            connection.execute(
                "ATTACH DATABASE ? AS state_db",
                (str(self.state.database_path.resolve()),),
            )
            _assert_atomic_journal_modes(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                work = _load_publish_work_for_commit(
                    connection,
                    work_item_id,
                    processing_run_id,
                )
                generation = _load_generation_for_commit(connection, generation_id, work)
                expected = _expected_generation_set_for_commit(connection, generation)
                if expected != staged_generations:
                    raise StalePublishWorkError(
                        "Retrieval staging 이후 active Generation 집합이 변경됐습니다."
                    )
                published_at = utc_now_iso()
                _activate_generation(connection, generation_id, str(generation["jira_id"]))
                _mark_state_published(
                    connection,
                    work_item_id,
                    processing_run_id,
                    published_at,
                )
                backlog_after = _count_publish_backlog_in_transaction(connection)
                _finish_publish_run_in_transaction(
                    connection,
                    processing_run_id,
                    published_at,
                    backlog_after,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        finally:
            connection.close()

    def _list_publish_work(self, *, limit: int) -> list[str]:
        with self.state.connect() as connection:
            rows = connection.execute(
                _PUBLISH_BACKLOG_SQL + " ORDER BY last_source_committed_at, created_at, work_item_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(row["work_item_id"]) for row in rows]

    def _count_publish_backlog(self) -> int:
        with self.state.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM (" + _PUBLISH_BACKLOG_SQL + ")"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _finish_nonpublished_run(
        self,
        processing_run_id: str,
        *,
        run_status: str,
        failed_count: int,
        superseded_count: int,
        error_summary: str | None = None,
    ) -> None:
        self.state.finish_processing_run(
            processing_run_id,
            run_status=run_status,
            published_count=0,
            failed_count=failed_count,
            superseded_count=superseded_count,
            backlog_after=self._count_publish_backlog(),
            error_summary=error_summary,
        )

    def _run_result(
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

    @staticmethod
    def _validate_claimed_work(
        work: dict[str, object],
        processing_run_id: str,
    ) -> None:
        if work.get("work_status") != "running":
            raise KnowledgeDbError(f"Publish claim 상태가 running이 아닙니다: {work.get('work_status')}")
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
    state: StateStore,
    retrieval_artifact_root: str | Path,
) -> Path:
    """가장 최근 atomic Publish Processing Run이 가리키는 immutable bundle을 반환합니다."""

    with state.connect() as connection:
        row = connection.execute(
            """
            SELECT processing_run_id
            FROM processing_run
            WHERE run_status='completed'
              AND published_count > 0
            ORDER BY finished_at DESC, started_at DESC, processing_run_id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise KnowledgeDbError("Published Retrieval head가 아직 없습니다.")
    artifact_dir = Path(retrieval_artifact_root).resolve() / "runs" / str(row[0])
    validation = validate_retrieval_artifact(artifact_dir)
    if not validation.passed:
        raise KnowledgeDbError(
            f"Published Retrieval head artifact가 손상됐습니다: {artifact_dir}"
        )
    return artifact_dir


def load_active_retrieval_searcher(
    state: StateStore,
    retrieval_artifact_root: str | Path,
):
    """State의 atomic Publish head를 따라 검증된 RetrievalSearcher를 엽니다."""

    return load_retrieval_searcher(
        active_retrieval_artifact_dir(state, retrieval_artifact_root)
    )


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


def _write_jsonl(
    path: Path,
    rows,
    sort_key: str,
) -> None:
    ordered = sorted(rows, key=lambda row: str(row[sort_key]))
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in ordered
        ),
        encoding="utf-8",
    )


def _assert_atomic_journal_modes(connection: sqlite3.Connection) -> None:
    main_mode = str(connection.execute("PRAGMA main.journal_mode").fetchone()[0]).lower()
    state_mode = str(connection.execute("PRAGMA state_db.journal_mode").fetchone()[0]).lower()
    if main_mode not in _ROLLBACK_JOURNAL_MODES or state_mode not in _ROLLBACK_JOURNAL_MODES:
        raise KnowledgeDbError(
            "Cross-DB Atomic Publish는 rollback-journal mode가 필요합니다: "
            f"knowledge={main_mode}, state={state_mode}"
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
        FROM state_db.sync_issue_change
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
        raise StalePublishWorkError(f"Atomic commit 직전 Work가 stale입니다: {work_item_id}")
    return row


def _load_generation_for_commit(
    connection: sqlite3.Connection,
    generation_id: str,
    work: sqlite3.Row,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT knowledge_generation_id, jira_id, state, accepted_attempt_id
        FROM knowledge_generation
        WHERE knowledge_generation_id=?
        """,
        (generation_id,),
    ).fetchone()
    if row is None or row["jira_id"] != work["jira_id"]:
        raise KnowledgeDbError("Atomic Publish Generation identity가 State와 다릅니다.")
    if work["knowledge_generation_id"] != generation_id:
        raise KnowledgeDbError("Atomic Publish State Generation checkpoint가 변경됐습니다.")
    if row["accepted_attempt_id"] is None:
        raise KnowledgeDbError("Atomic Publish Generation에 accepted_attempt_id가 없습니다.")
    if row["state"] not in {"candidate", "active", "historical"}:
        raise KnowledgeDbError(f"Atomic Publish 가능한 Generation 상태가 아닙니다: {row['state']}")
    return row


def _expected_generation_set_for_commit(
    connection: sqlite3.Connection,
    target_generation: sqlite3.Row,
) -> frozenset[str]:
    rows = connection.execute(
        """
        SELECT knowledge_generation_id
        FROM knowledge_generation
        WHERE state='active' AND jira_id<>?
        """,
        (target_generation["jira_id"],),
    ).fetchall()
    result = {str(row[0]) for row in rows}
    result.add(str(target_generation["knowledge_generation_id"]))
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
        UPDATE state_db.sync_issue_change
        SET work_status='published',
            publish_status='published',
            error_stage=NULL,
            error_message=NULL,
            last_published_at=?,
            updated_at=?
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


def _count_publish_backlog_in_transaction(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM state_db.sync_issue_change
        WHERE last_source_committed_run_id IS NOT NULL
          AND last_source_committed_run_id=last_observed_source_run_id
          AND work_status IN ('pending','failed')
          AND knowledge_status='completed'
          AND embedding_status='completed'
          AND publish_status IN ('pending','failed')
          AND superseded_by_work_item_id IS NULL
        """
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _finish_publish_run_in_transaction(
    connection: sqlite3.Connection,
    processing_run_id: str,
    finished_at: str,
    backlog_after: int,
) -> None:
    cursor = connection.execute(
        """
        UPDATE state_db.processing_run
        SET finished_at=?,
            run_status='completed',
            published_count=1,
            failed_count=0,
            superseded_count=0,
            backlog_after=?,
            error_summary=NULL
        WHERE processing_run_id=?
          AND run_status='running'
          AND selected_count=1
        """,
        (finished_at, backlog_after, processing_run_id),
    )
    if cursor.rowcount != 1:
        raise KnowledgeDbError(
            f"Atomic Publish Processing Run finalize 실패: {processing_run_id}"
        )


__all__ = [
    "AtomicPublishResult",
    "OperationalPublishRunResult",
    "OperationalPublishWorker",
    "StalePublishWorkError",
    "active_retrieval_artifact_dir",
    "load_active_retrieval_searcher",
]
