from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .exporter.atomic_writer import AtomicTextWriter
from .knowledge_db.ids import (
    KnowledgeContract,
    issue_version_id,
    knowledge_generation_id,
)
from .state_store import StateStore, WorkItemRecord, utc_now_iso

LOGGER = logging.getLogger(__name__)
_REVIEW_FILE = re.compile(r"^(.+)\.review\.attempt([1-9][0-9]*)\.json$")
_EVIDENCE_RE = re.compile(
    r"^(summary|description|comment:[^:]+|attachment:[^:]+|"
    r"relationship:[^:]+|custom_field:[^:]+)$"
)
_KNOWLEDGE_FIELDS = {
    "knowledge_schema_version",
    "issue_key",
    "issue_summary",
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
}
_KNOWLEDGE_ARRAY_FIELDS = (
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
)


class KnowledgeProcessingError(RuntimeError):
    """Loop B Knowledge stage를 안전하게 완료하지 못한 오류입니다."""


@dataclass(frozen=True)
class KnowledgeProcessResult:
    knowledge_path: Path
    review_paths: tuple[Path, ...]
    final_attempt: int
    final_score: float


@dataclass(frozen=True)
class KnowledgeWorkerRunResult:
    processing_run_id: str
    status: str
    selected_count: int
    knowledge_completed_count: int
    failed_count: int
    superseded_count: int
    knowledge_backlog_before: int
    knowledge_backlog_after: int


class KnowledgeProcessor(Protocol):
    def process(
        self,
        *,
        work_item: WorkItemRecord,
        input_path: Path,
        output_path: Path,
        review_dir: Path,
    ) -> KnowledgeProcessResult: ...


class OpenCodeKnowledgeProcessor:
    """기존 Jira Knowledge Orchestrator를 opencode run으로 한 Work Item씩 실행합니다."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        binary: str = "opencode",
        agent: str = "jira-knowledge-orchestrator",
        model: str | None = None,
        attach_url: str | None = None,
        timeout_seconds: int = 3600,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 1 이상이어야 합니다.")
        if model is not None and not model.strip():
            raise ValueError("OpenCode model은 비어 있지 않은 문자열이어야 합니다.")
        self.project_root = Path(project_root).resolve()
        self.binary = binary
        self.agent = agent
        self.model = model.strip() if model is not None else None
        self.attach_url = attach_url
        self.timeout_seconds = timeout_seconds

    def process(
        self,
        *,
        work_item: WorkItemRecord,
        input_path: Path,
        output_path: Path,
        review_dir: Path,
    ) -> KnowledgeProcessResult:
        if not input_path.is_file():
            raise KnowledgeProcessingError(f"Knowledge Input이 없습니다: {input_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)

        prompt = self._prompt(input_path, output_path, review_dir)
        command = [self.binary, "run"]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(["--agent", self.agent])
        if self.attach_url:
            command.extend(["--attach", self.attach_url])
        command.append(prompt)

        LOGGER.info(
            "opencode_event=knowledge_run_started issue_key=%s agent=%s model=%s timeout_seconds=%s",
            work_item.observed_issue_key,
            self.agent,
            self.model or "session-default",
            self.timeout_seconds,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=self.project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise KnowledgeProcessingError(
                f"OpenCode 실행 파일을 찾을 수 없습니다: {self.binary}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise KnowledgeProcessingError(
                f"OpenCode Knowledge 처리 timeout: {self.timeout_seconds}s"
            ) from exc

        LOGGER.info(
            "opencode_event=knowledge_run_finished issue_key=%s agent=%s model=%s returncode=%s",
            work_item.observed_issue_key,
            self.agent,
            self.model or "session-default",
            completed.returncode,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()[-2000:]
            raise KnowledgeProcessingError(
                f"OpenCode가 실패했습니다: exit={completed.returncode}, stderr={stderr}"
            )

        knowledge_doc = _read_json_object(output_path, "Knowledge output")
        input_doc = _read_json_object(input_path, "Knowledge input")
        errors = validate_knowledge_document(knowledge_doc, input_doc)
        if errors:
            raise KnowledgeProcessingError(
                "Knowledge validator 실패: " + "; ".join(errors[:10])
            )

        review_paths, final_attempt, final_review = _load_reviews(
            review_dir,
            work_item.observed_issue_key,
        )
        _assert_review_pass(final_review, work_item.observed_issue_key)
        return KnowledgeProcessResult(
            knowledge_path=output_path,
            review_paths=review_paths,
            final_attempt=final_attempt,
            final_score=float(final_review["score"]),
        )

    def _prompt(self, input_path: Path, output_path: Path, review_dir: Path) -> str:
        return (
            "jira-knowledge-orchestrator v0.9로 Jira Knowledge Extraction 1건을 수행해줘.\n\n"
            f"[KNOWLEDGE INPUT]\n{self._display_path(input_path)}\n\n"
            f"[KNOWLEDGE OUTPUT]\n{self._display_path(output_path)}\n\n"
            f"[KNOWLEDGE REVIEW]\n{self._display_path(review_dir)}\n\n"
            "Per-Work 단일 Issue 모드다. workspace 진단이나 batch 집계를 하지 마. "
            "echo/pwd/ls/cat/find/test/mkdir 등 shell 탐색을 하지 말고, "
            "지정한 로컬 INPUT FILE만 사실 근거로 사용해 기존 Worker→Validator→Reviewer 규칙대로 처리해. "
            "외부 Jira/Web/MCP를 조회하지 말고, 최종 Knowledge와 Attempt별 Review JSON을 반드시 지정 경로에 저장해."
        )

    def _display_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.project_root).as_posix()
        except ValueError:
            return resolved.as_posix()


class LoopBKnowledgeWorker:
    """Source-ready 최신 Work를 한 번에 하나씩 Knowledge checkpoint까지 처리합니다."""

    def __init__(
        self,
        state: StateStore,
        data_root: str | Path,
        processor: KnowledgeProcessor,
        *,
        knowledge_contract: KnowledgeContract,
    ) -> None:
        self.state = state
        self.data_root = Path(data_root).resolve()
        self.processor = processor
        self.knowledge_contract = knowledge_contract
        self.knowledge_writer = AtomicTextWriter(self.data_root / "knowledge")

    def run(self, *, limit: int = 1) -> KnowledgeWorkerRunResult:
        if limit <= 0:
            raise ValueError("limit은 1 이상이어야 합니다.")

        backlog_before = self._count_knowledge_backlog()
        selected = self._list_knowledge_work(limit=limit)
        processing_run_id = self.state.create_processing_run(
            selected_count=len(selected),
            backlog_before=backlog_before,
        )

        completed_count = 0
        failed_count = 0
        superseded_count = 0
        error_messages: list[str] = []

        for work_item in selected:
            if not self.state.claim_work_item(work_item.work_item_id, processing_run_id):
                superseded_count += 1
                continue
            if not self.state.mark_knowledge_running(work_item.work_item_id):
                superseded_count += 1
                continue

            paths = self._paths(work_item, processing_run_id)
            try:
                result = self.processor.process(
                    work_item=work_item,
                    input_path=paths["input"],
                    output_path=paths["staging_output"],
                    review_dir=paths["staging_reviews"],
                )
                # OpenCode가 느린 동안 더 최신 Source가 Commit됐을 수 있습니다.
                if not self.state.work_item_is_latest(
                    work_item.work_item_id,
                    log_stale=True,
                ):
                    superseded_count += 1
                    continue

                self._promote_knowledge(
                    result,
                    canonical_output=paths["canonical_output"],
                    canonical_reviews=paths["canonical_reviews"],
                )

                version_id = issue_version_id(work_item.jira_id, work_item.source_hash)
                generation_id = knowledge_generation_id(
                    version_id,
                    self.knowledge_contract.logical_hash(),
                )
                if not self.state.mark_knowledge_completed(
                    work_item.work_item_id,
                    issue_version_id=version_id,
                    knowledge_generation_id=generation_id,
                ):
                    superseded_count += 1
                    continue

                # Knowledge는 durable checkpoint가 됐지만 Embedding/Publish가 남아 있으므로
                # 다음 Processing Run이 이 Work를 이어갈 수 있게 pending으로 돌려놓습니다.
                self._release_after_knowledge(
                    work_item.work_item_id,
                    processing_run_id,
                )
                completed_count += 1
            except Exception as exc:
                message = str(exc)
                if self.state.mark_work_failed(
                    work_item.work_item_id,
                    stage="knowledge",
                    error_message=message,
                ):
                    failed_count += 1
                    error_messages.append(
                        f"{work_item.work_item_id}: {message[:500]}"
                    )
                else:
                    superseded_count += 1

        backlog_after = self._count_knowledge_backlog()
        status = self._run_status(
            selected_count=len(selected),
            completed_count=completed_count,
            failed_count=failed_count,
            superseded_count=superseded_count,
        )
        self.state.finish_processing_run(
            processing_run_id,
            run_status=status,
            published_count=0,
            failed_count=failed_count,
            superseded_count=superseded_count,
            backlog_after=backlog_after,
            error_summary="; ".join(error_messages) if error_messages else None,
        )
        return KnowledgeWorkerRunResult(
            processing_run_id=processing_run_id,
            status=status,
            selected_count=len(selected),
            knowledge_completed_count=completed_count,
            failed_count=failed_count,
            superseded_count=superseded_count,
            knowledge_backlog_before=backlog_before,
            knowledge_backlog_after=backlog_after,
        )

    def _list_knowledge_work(self, *, limit: int) -> list[WorkItemRecord]:
        with self.state.connect() as connection:
            rows = connection.execute(
                """
                SELECT work_item_id, project_id, jira_id, observed_issue_key,
                       source_hash, source_hash_profile, change_kind,
                       last_observed_source_run_id, last_source_committed_run_id,
                       last_processing_run_id, work_status,
                       knowledge_status, embedding_status, publish_status,
                       superseded_by_work_item_id
                FROM sync_issue_change
                WHERE last_source_committed_run_id IS NOT NULL
                  AND last_source_committed_run_id = last_observed_source_run_id
                  AND work_status IN ('pending','failed')
                  AND knowledge_status IN ('pending','failed','running')
                  AND superseded_by_work_item_id IS NULL
                ORDER BY last_source_committed_at, created_at, work_item_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [WorkItemRecord(**dict(row)) for row in rows]

    def _count_knowledge_backlog(self) -> int:
        with self.state.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM sync_issue_change
                WHERE last_source_committed_run_id IS NOT NULL
                  AND last_source_committed_run_id = last_observed_source_run_id
                  AND work_status IN ('pending','failed')
                  AND knowledge_status IN ('pending','failed','running')
                  AND superseded_by_work_item_id IS NULL
                """
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _paths(
        self,
        work_item: WorkItemRecord,
        processing_run_id: str,
    ) -> dict[str, Path]:
        source_run_id = work_item.last_observed_source_run_id
        issue_key = work_item.observed_issue_key
        staging_root = (
            self.data_root
            / "knowledge"
            / "runs"
            / source_run_id
            / "staging"
            / processing_run_id
            / work_item.work_item_id
        )
        return {
            "input": (
                self.data_root
                / "knowledge_input"
                / "runs"
                / source_run_id
                / "issues"
                / f"{issue_key}.json"
            ),
            "staging_output": staging_root / "issues" / f"{issue_key}.json",
            "staging_reviews": staging_root / "reviews",
            "canonical_output": (
                self.data_root
                / "knowledge"
                / "runs"
                / source_run_id
                / "issues"
                / f"{issue_key}.json"
            ),
            "canonical_reviews": (
                self.data_root
                / "knowledge"
                / "runs"
                / source_run_id
                / "reviews"
            ),
        }

    def _promote_knowledge(
        self,
        result: KnowledgeProcessResult,
        *,
        canonical_output: Path,
        canonical_reviews: Path,
    ) -> None:
        # Staging 파일을 다시 읽어 AtomicTextWriter로 canonical 위치에 승격합니다.
        output_relative = canonical_output.relative_to(self.data_root / "knowledge")
        self.knowledge_writer.write_text(
            output_relative,
            result.knowledge_path.read_text(encoding="utf-8"),
        )
        for review_path in result.review_paths:
            relative = canonical_reviews.relative_to(self.data_root / "knowledge") / review_path.name
            self.knowledge_writer.write_text(
                relative,
                review_path.read_text(encoding="utf-8"),
            )

    def _release_after_knowledge(
        self,
        work_item_id: str,
        processing_run_id: str,
    ) -> None:
        with self.state.connect() as connection:
            connection.execute(
                """
                UPDATE sync_issue_change
                SET work_status = 'pending', updated_at = ?
                WHERE work_item_id = ?
                  AND last_processing_run_id = ?
                  AND work_status = 'running'
                  AND knowledge_status = 'completed'
                  AND last_source_committed_run_id = last_observed_source_run_id
                  AND superseded_by_work_item_id IS NULL
                """,
                (utc_now_iso(), work_item_id, processing_run_id),
            )

    @staticmethod
    def _run_status(
        *,
        selected_count: int,
        completed_count: int,
        failed_count: int,
        superseded_count: int,
    ) -> str:
        if selected_count == 0 or superseded_count == selected_count:
            return "completed"
        if failed_count == selected_count:
            return "failed"
        # 이 구현 단위는 Knowledge checkpoint까지만 완료하며 Embedding/Publish가 남습니다.
        if completed_count or failed_count:
            return "partial"
        return "failed"


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeProcessingError(f"{label} JSON을 읽을 수 없습니다: {path}") from exc
    if not isinstance(value, dict):
        raise KnowledgeProcessingError(f"{label}은 JSON object여야 합니다: {path}")
    return value


def _valid_evidence_refs(input_doc: dict[str, Any]) -> set[str]:
    refs = {"summary", "description"}
    for field, key, prefix in (
        ("comments", "comment_id", "comment"),
        ("attachments", "attachment_id", "attachment"),
        ("relationships", "relationship_id", "relationship"),
        ("custom_fields", "field_id", "custom_field"),
    ):
        values = input_doc.get(field, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and item.get(key):
                refs.add(f"{prefix}:{item[key]}")
    return refs


def _validate_knowledge_item(
    item: Any,
    location: str,
    valid_refs: set[str],
) -> list[str]:
    if not isinstance(item, dict):
        return [f"{location}: object 필요"]
    errors: list[str] = []
    if set(item) != {"statement", "evidence_refs"}:
        errors.append(f"{location}: 필드 오류")
    statement = item.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        errors.append(f"{location}.statement: 문자열 필요")
    refs = item.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        errors.append(f"{location}.evidence_refs: 1개 이상 필요")
        return errors
    string_refs = [ref for ref in refs if isinstance(ref, str)]
    if len(string_refs) != len(set(string_refs)):
        errors.append(f"{location}.evidence_refs: 중복 Evidence 금지")
    for ref in refs:
        if not isinstance(ref, str) or not _EVIDENCE_RE.fullmatch(ref):
            errors.append(f"{location}: 잘못된 Evidence 형식 {ref!r}")
        elif ref not in valid_refs:
            errors.append(f"{location}: Input에 없는 Evidence {ref}")
    return errors


def validate_knowledge_document(
    knowledge_doc: dict[str, Any],
    input_doc: dict[str, Any],
) -> list[str]:
    """기존 M4 Python Validator와 같은 핵심 계약을 Runtime 안에서도 재검증합니다."""

    errors: list[str] = []
    if set(knowledge_doc) != _KNOWLEDGE_FIELDS:
        errors.append("최상위 필드 불일치")
    if knowledge_doc.get("knowledge_schema_version") != "0.1":
        errors.append("knowledge_schema_version != 0.1")
    if knowledge_doc.get("issue_key") != input_doc.get("issue_key"):
        errors.append("issue_key 불일치")
    valid_refs = _valid_evidence_refs(input_doc)
    errors.extend(
        _validate_knowledge_item(
            knowledge_doc.get("issue_summary"),
            "issue_summary",
            valid_refs,
        )
    )
    for field in _KNOWLEDGE_ARRAY_FIELDS:
        values = knowledge_doc.get(field)
        if not isinstance(values, list):
            errors.append(f"{field}: 배열 필요")
            continue
        for index, item in enumerate(values):
            errors.extend(
                _validate_knowledge_item(
                    item,
                    f"{field}[{index}]",
                    valid_refs,
                )
            )
    return errors


def _load_reviews(
    review_dir: Path,
    issue_key: str,
) -> tuple[tuple[Path, ...], int, dict[str, Any]]:
    if not review_dir.is_dir():
        raise KnowledgeProcessingError(f"Review 디렉터리가 없습니다: {review_dir}")
    attempts: list[tuple[int, Path, dict[str, Any]]] = []
    for path in sorted(review_dir.glob("*.json")):
        match = _REVIEW_FILE.match(path.name)
        if match is None or match.group(1) != issue_key:
            continue
        attempt = int(match.group(2))
        review = _read_json_object(path, "Review")
        if review.get("issue_key") != issue_key:
            raise KnowledgeProcessingError(f"Review issue_key 불일치: {path}")
        attempts.append((attempt, path, review))
    if not attempts:
        raise KnowledgeProcessingError(f"Review JSON이 없습니다: {issue_key}")
    attempts.sort(key=lambda item: item[0])
    final_attempt, _, final_review = attempts[-1]
    return tuple(item[1] for item in attempts), final_attempt, final_review


def _assert_review_pass(review: dict[str, Any], issue_key: str) -> None:
    try:
        score = float(review.get("score"))
        major_count = int(review.get("major_issue_count"))
    except (TypeError, ValueError) as exc:
        raise KnowledgeProcessingError(f"Review score/major_issue_count 형식 오류: {issue_key}") from exc
    passed = (
        review.get("verdict") == "PASS"
        and score >= 8.5
        and review.get("critical_error") is False
        and major_count == 0
    )
    if not passed:
        raise KnowledgeProcessingError(
            f"Review PASS 조건 미충족: issue={issue_key}, verdict={review.get('verdict')}, "
            f"score={score}, critical={review.get('critical_error')}, major={major_count}"
        )


__all__ = [
    "KnowledgeProcessResult",
    "KnowledgeProcessingError",
    "KnowledgeProcessor",
    "KnowledgeWorkerRunResult",
    "LoopBKnowledgeWorker",
    "OpenCodeKnowledgeProcessor",
    "validate_knowledge_document",
]
