from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .state_store import StateStore, utc_now_iso


LOGGER = logging.getLogger(__name__)

_STAGE_COLUMN = {
    "knowledge": "knowledge_status",
    "embedding": "embedding_status",
    "publish": "publish_status",
}


@dataclass(frozen=True)
class StaleRecoveryResult:
    stage: str
    stale_after_seconds: int
    recovered_work_count: int
    recovered_processing_run_count: int
    work_item_ids: tuple[str, ...]
    processing_run_ids: tuple[str, ...]


def recover_stale_inflight(
    state: StateStore,
    *,
    stage: str,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> StaleRecoveryResult:
    """중단된 Single Worker가 남긴 stale running Work를 failed backlog로 복구합니다.

    현재 State Schema v3에는 heartbeat/lease 컬럼이 없습니다. 따라서 살아 있는 장시간
    작업을 오인하지 않도록 기본 Runner는 stage timeout보다 긴 stale 기준을 사용합니다.
    Smoke/troubleshooting에서는 명시적으로 0을 전달해 즉시 복구할 수 있습니다.
    """

    column = _STAGE_COLUMN.get(stage)
    if column is None:
        raise ValueError(f"지원하지 않는 stale recovery stage: {stage}")
    if stale_after_seconds < 0:
        raise ValueError("stale_after_seconds는 0 이상이어야 합니다.")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now는 timezone-aware datetime이어야 합니다.")
    current = current.astimezone(timezone.utc)
    current_iso = current.isoformat()
    cutoff_iso = (current - timedelta(seconds=stale_after_seconds)).isoformat()

    recovered_work_ids: list[str] = []
    recovered_run_ids: set[str] = set()

    with state.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT
                w.work_item_id,
                w.jira_id,
                w.last_processing_run_id,
                w.updated_at,
                p.run_status
            FROM sync_issue_change AS w
            JOIN processing_run AS p
              ON p.processing_run_id = w.last_processing_run_id
            WHERE w.work_status = 'running'
              AND w.{column} = 'running'
              AND w.superseded_by_work_item_id IS NULL
              AND (
                    p.run_status != 'running'
                    OR w.updated_at <= ?
                  )
            ORDER BY w.updated_at, w.work_item_id
            """,
            (cutoff_iso,),
        ).fetchall()

        for row in rows:
            work_item_id = str(row["work_item_id"])
            processing_run_id = str(row["last_processing_run_id"])
            reason = (
                "stale in-flight recovery: "
                f"stage={stage}, processing_run_id={processing_run_id}, "
                f"stale_after_seconds={stale_after_seconds}"
            )
            updated = connection.execute(
                f"""
                UPDATE sync_issue_change
                SET {column} = 'failed',
                    work_status = 'failed',
                    error_stage = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE work_item_id = ?
                  AND work_status = 'running'
                  AND {column} = 'running'
                  AND last_processing_run_id = ?
                  AND superseded_by_work_item_id IS NULL
                """,
                (
                    stage,
                    reason[:2000],
                    current_iso,
                    work_item_id,
                    processing_run_id,
                ),
            )
            if updated.rowcount != 1:
                continue

            recovered_work_ids.append(work_item_id)
            recovered_run_ids.add(processing_run_id)
            LOGGER.warning(
                "state_event=stale_inflight_recovered stage=%s jira_id=%s "
                "processing_run_id=%s work_item_id=%s stale_after_seconds=%s",
                stage,
                row["jira_id"],
                processing_run_id,
                work_item_id,
                stale_after_seconds,
            )

        for processing_run_id in sorted(recovered_run_ids):
            run = connection.execute(
                """
                SELECT selected_count, published_count, failed_count,
                       superseded_count, error_summary, run_status
                FROM processing_run
                WHERE processing_run_id = ?
                """,
                (processing_run_id,),
            ).fetchone()
            if run is None or str(run["run_status"]) != "running":
                continue

            recovered_for_run = sum(
                1
                for row in rows
                if str(row["last_processing_run_id"]) == processing_run_id
                and str(row["work_item_id"]) in recovered_work_ids
            )
            selected_count = int(run["selected_count"])
            published_count = int(run["published_count"])
            superseded_count = int(run["superseded_count"])
            existing_failed_count = int(run["failed_count"])
            remaining_capacity = max(
                0,
                selected_count - published_count - superseded_count,
            )
            failed_count = min(
                remaining_capacity,
                max(existing_failed_count, recovered_for_run),
            )
            summary = (
                f"stale in-flight recovery closed interrupted {stage} run; "
                f"recovered_work_count={recovered_for_run}"
            )
            previous = str(run["error_summary"] or "").strip()
            if previous:
                summary = f"{previous}; {summary}"

            backlog_after = _count_stage_backlog(connection, stage)
            connection.execute(
                """
                UPDATE processing_run
                SET finished_at = ?,
                    run_status = 'failed',
                    failed_count = ?,
                    backlog_after = ?,
                    error_summary = ?
                WHERE processing_run_id = ?
                  AND run_status = 'running'
                """,
                (
                    current_iso,
                    failed_count,
                    backlog_after,
                    summary[:2000],
                    processing_run_id,
                ),
            )
            LOGGER.warning(
                "state_event=stale_processing_run_closed stage=%s "
                "processing_run_id=%s recovered_work_count=%s",
                stage,
                processing_run_id,
                recovered_for_run,
            )

    return StaleRecoveryResult(
        stage=stage,
        stale_after_seconds=stale_after_seconds,
        recovered_work_count=len(recovered_work_ids),
        recovered_processing_run_count=len(recovered_run_ids),
        work_item_ids=tuple(recovered_work_ids),
        processing_run_ids=tuple(sorted(recovered_run_ids)),
    )


def _count_stage_backlog(connection: object, stage: str) -> int:
    if stage == "knowledge":
        sql = """
            SELECT COUNT(*)
            FROM sync_issue_change
            WHERE last_source_committed_run_id IS NOT NULL
              AND last_source_committed_run_id = last_observed_source_run_id
              AND work_status IN ('pending','failed')
              AND knowledge_status IN ('pending','failed','running')
              AND superseded_by_work_item_id IS NULL
        """
    elif stage == "embedding":
        sql = """
            SELECT COUNT(*)
            FROM sync_issue_change
            WHERE last_source_committed_run_id IS NOT NULL
              AND last_source_committed_run_id = last_observed_source_run_id
              AND work_status IN ('pending','failed')
              AND knowledge_status = 'completed'
              AND embedding_status IN ('pending','failed')
              AND superseded_by_work_item_id IS NULL
        """
    else:
        sql = """
            SELECT COUNT(*)
            FROM sync_issue_change
            WHERE last_source_committed_run_id IS NOT NULL
              AND last_source_committed_run_id = last_observed_source_run_id
              AND work_status IN ('pending','failed')
              AND knowledge_status = 'completed'
              AND embedding_status = 'completed'
              AND publish_status IN ('pending','failed')
              AND superseded_by_work_item_id IS NULL
        """
    row = connection.execute(sql).fetchone()  # type: ignore[attr-defined]
    return int(row[0]) if row is not None else 0


__all__ = ["StaleRecoveryResult", "recover_stale_inflight"]
