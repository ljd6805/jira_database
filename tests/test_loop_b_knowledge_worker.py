from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jira_collector.knowledge_db.ids import KnowledgeContract
from jira_collector.knowledge_processing import (
    KnowledgeProcessResult,
    KnowledgeProcessingError,
    LoopBKnowledgeWorker,
    OpenCodeKnowledgeProcessor,
)
from jira_collector.state_store import StateStore


def _valid_input(issue_key: str = "ABC-1") -> dict[str, Any]:
    return {
        "package_schema_version": "1.0",
        "run_id": "source-run",
        "project_key": "ABC",
        "issue_key": issue_key,
        "source_hash_profile": "semantic_v2",
        "source_hash": "sha256:" + "a" * 64,
        "issue": {
            "jira_id": "20000",
            "summary": "summary",
            "description": "description",
        },
        "comments": [],
        "attachments": [],
        "relationships": [],
        "custom_fields": [],
    }


def _valid_knowledge(issue_key: str = "ABC-1") -> dict[str, Any]:
    item = {"statement": "검증 가능한 문장", "evidence_refs": ["summary"]}
    return {
        "knowledge_schema_version": "0.1",
        "issue_key": issue_key,
        "issue_summary": item,
        "problem_or_goal": [],
        "key_findings": [item],
        "actions_and_decisions": [],
        "outcomes": [],
        "open_items": [],
    }


def _pass_review(issue_key: str = "ABC-1") -> dict[str, Any]:
    return {
        "issue_key": issue_key,
        "score": 9.2,
        "verdict": "PASS",
        "critical_error": False,
        "major_issue_count": 0,
    }


def _seed_ready_work(
    state: StateStore,
    data_root: Path,
    *,
    source_hash: str = "sha256:" + "a" * 64,
) -> tuple[str, str]:
    source_run_id = state.create_source_sync_run("2026-08-31T12:00:00+00:00")
    state.upsert_visible_project(
        source_run_id=source_run_id,
        project_id="10000",
        project_key="ABC",
        project_name="Alpha",
    )
    state.start_source_project_run(
        source_run_id=source_run_id,
        project_id="10000",
        operation_kind="initial_ingest",
        lower_bound=None,
        upper_bound="2026-08-31T12:00:00+00:00",
    )
    work_item_id = state.record_source_candidate(
        source_run_id=source_run_id,
        project_id="10000",
        jira_id="20000",
        observed_issue_key="ABC-1",
        jira_updated_at="2026-08-31T11:50:00+00:00",
        cursor_updated_at="2026-08-31T11:50:00+00:00",
        cursor_jira_id="20000",
        change_kind="new",
        source_hash=source_hash,
    )
    assert work_item_id is not None
    state.commit_source_project(source_run_id, "10000")

    input_path = (
        data_root
        / "knowledge_input"
        / "runs"
        / source_run_id
        / "issues"
        / "ABC-1.json"
    )
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_doc = _valid_input()
    input_doc["run_id"] = source_run_id
    input_doc["source_hash"] = source_hash
    input_path.write_text(json.dumps(input_doc, ensure_ascii=False), encoding="utf-8")
    return source_run_id, work_item_id


class SuccessProcessor:
    def process(
        self,
        *,
        work_item: Any,
        input_path: Path,
        output_path: Path,
        review_dir: Path,
    ) -> KnowledgeProcessResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_valid_knowledge(work_item.observed_issue_key), ensure_ascii=False),
            encoding="utf-8",
        )
        review_path = review_dir / f"{work_item.observed_issue_key}.review.attempt1.json"
        review_path.write_text(
            json.dumps(_pass_review(work_item.observed_issue_key), ensure_ascii=False),
            encoding="utf-8",
        )
        return KnowledgeProcessResult(
            knowledge_path=output_path,
            review_paths=(review_path,),
            final_attempt=1,
            final_score=9.2,
        )


class FailingProcessor:
    def process(self, **_: Any) -> KnowledgeProcessResult:
        raise KnowledgeProcessingError("simulated opencode failure")


class SupersedingProcessor(SuccessProcessor):
    def __init__(self, state: StateStore) -> None:
        self.state = state
        self.new_work_item_id: str | None = None

    def process(self, **kwargs: Any) -> KnowledgeProcessResult:
        result = super().process(**kwargs)
        run_id = self.state.create_source_sync_run("2026-08-31T13:00:00+00:00")
        self.state.upsert_visible_project(
            source_run_id=run_id,
            project_id="10000",
            project_key="ABC",
            project_name="Alpha",
        )
        self.state.start_source_project_run(
            source_run_id=run_id,
            project_id="10000",
            operation_kind="delta",
            lower_bound="2026-08-31T11:55:00+00:00",
            upper_bound="2026-08-31T13:00:00+00:00",
        )
        self.new_work_item_id = self.state.record_source_candidate(
            source_run_id=run_id,
            project_id="10000",
            jira_id="20000",
            observed_issue_key="ABC-1",
            jira_updated_at="2026-08-31T12:30:00+00:00",
            cursor_updated_at="2026-08-31T12:30:00+00:00",
            cursor_jira_id="20000",
            change_kind="changed",
            source_hash="sha256:" + "b" * 64,
        )
        assert self.new_work_item_id is not None
        self.state.commit_source_project(run_id, "10000")
        return result


def _contract() -> KnowledgeContract:
    return KnowledgeContract(
        knowledge_schema_version="0.1",
        skill_version="0.9",
        runtime_version="0.9",
        model_profile="test-opencode-profile-v1",
    )


def test_knowledge_worker_promotes_valid_latest_result_and_checkpoints(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")
    source_run_id, work_item_id = _seed_ready_work(state, data_root)
    worker = LoopBKnowledgeWorker(
        state,
        data_root,
        SuccessProcessor(),
        knowledge_contract=_contract(),
    )

    result = worker.run(limit=1)

    assert result.status == "partial"
    assert result.selected_count == 1
    assert result.knowledge_completed_count == 1
    assert result.failed_count == 0
    assert result.superseded_count == 0
    assert result.knowledge_backlog_before == 1
    assert result.knowledge_backlog_after == 0

    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "pending"
    assert work["knowledge_status"] == "completed"
    assert str(work["issue_version_id"]).startswith("iv_")
    assert str(work["knowledge_generation_id"]).startswith("kg_")
    assert work["embedding_status"] == "pending"
    assert work["publish_status"] == "pending"

    canonical = data_root / "knowledge" / "runs" / source_run_id
    assert (canonical / "issues" / "ABC-1.json").is_file()
    assert (canonical / "reviews" / "ABC-1.review.attempt1.json").is_file()
    with state.connect() as connection:
        run = connection.execute(
            "SELECT * FROM processing_run WHERE processing_run_id = ?",
            (result.processing_run_id,),
        ).fetchone()
    assert run is not None
    assert run["run_status"] == "partial"


def test_stale_result_is_not_promoted_after_newer_source_commit(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")
    source_run_id, old_work_id = _seed_ready_work(state, data_root)
    processor = SupersedingProcessor(state)
    worker = LoopBKnowledgeWorker(
        state,
        data_root,
        processor,
        knowledge_contract=_contract(),
    )

    result = worker.run(limit=1)

    assert result.status == "completed"
    assert result.knowledge_completed_count == 0
    assert result.superseded_count == 1
    old = state.get_work_item(old_work_id)
    assert old["work_status"] == "superseded"
    assert old["knowledge_status"] == "running"
    assert processor.new_work_item_id is not None
    assert old["superseded_by_work_item_id"] == processor.new_work_item_id
    assert not (
        data_root / "knowledge" / "runs" / source_run_id / "issues" / "ABC-1.json"
    ).exists()


def test_processor_failure_marks_latest_work_failed(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")
    _, work_item_id = _seed_ready_work(state, data_root)
    worker = LoopBKnowledgeWorker(
        state,
        data_root,
        FailingProcessor(),
        knowledge_contract=_contract(),
    )

    result = worker.run(limit=1)

    assert result.status == "failed"
    assert result.failed_count == 1
    work = state.get_work_item(work_item_id)
    assert work["work_status"] == "failed"
    assert work["knowledge_status"] == "failed"
    assert work["error_stage"] == "knowledge"
    assert "simulated opencode failure" in str(work["error_message"])


def test_knowledge_completed_work_is_not_selected_again(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    state = StateStore(data_root / "state" / "collector.db")
    _seed_ready_work(state, data_root)
    worker = LoopBKnowledgeWorker(
        state,
        data_root,
        SuccessProcessor(),
        knowledge_contract=_contract(),
    )
    first = worker.run(limit=1)
    second = worker.run(limit=1)

    assert first.knowledge_completed_count == 1
    assert second.status == "completed"
    assert second.selected_count == 0
    assert second.knowledge_backlog_before == 0


def test_opencode_processor_uses_primary_agent_and_validates_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    input_path = project_root / "data" / "input.json"
    output_path = project_root / "data" / "staging" / "ABC-1.json"
    review_dir = project_root / "data" / "staging" / "reviews"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(json.dumps(_valid_input(), ensure_ascii=False), encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_valid_knowledge(), ensure_ascii=False),
            encoding="utf-8",
        )
        review = review_dir / "ABC-1.review.attempt1.json"
        review.write_text(json.dumps(_pass_review(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    processor = OpenCodeKnowledgeProcessor(
        project_root,
        binary="opencode",
        agent="jira-knowledge-orchestrator",
        timeout_seconds=600,
    )
    work = type(
        "Work",
        (),
        {"observed_issue_key": "ABC-1"},
    )()

    result = processor.process(
        work_item=work,
        input_path=input_path,
        output_path=output_path,
        review_dir=review_dir,
    )

    command = captured["command"]
    assert command[:4] == ["opencode", "run", "--agent", "jira-knowledge-orchestrator"]
    assert "[KNOWLEDGE INPUT]" in command[-1]
    assert "외부 Jira/Web/MCP를 조회하지 말고" in command[-1]
    assert captured["kwargs"]["cwd"] == project_root
    assert captured["kwargs"]["timeout"] == 600
    assert result.final_attempt == 1
    assert result.final_score == 9.2


def test_opencode_processor_rejects_non_pass_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    input_path = project_root / "input.json"
    output_path = project_root / "out" / "ABC-1.json"
    review_dir = project_root / "out" / "reviews"
    input_path.write_text(json.dumps(_valid_input(), ensure_ascii=False), encoding="utf-8")

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_valid_knowledge(), ensure_ascii=False), encoding="utf-8")
        bad = _pass_review()
        bad.update({"score": 8.0, "verdict": "REGENERATE", "major_issue_count": 1})
        (review_dir / "ABC-1.review.attempt1.json").write_text(
            json.dumps(bad, ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    processor = OpenCodeKnowledgeProcessor(project_root)
    work = type("Work", (), {"observed_issue_key": "ABC-1"})()

    with pytest.raises(KnowledgeProcessingError, match="Review PASS 조건 미충족"):
        processor.process(
            work_item=work,
            input_path=input_path,
            output_path=output_path,
            review_dir=review_dir,
        )
