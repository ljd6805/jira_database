from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jira_collector.knowledge_processing import OpenCodeKnowledgeProcessor


def _input_doc() -> dict[str, Any]:
    return {
        "package_schema_version": "1.0",
        "run_id": "sr_test",
        "project_key": "ABC",
        "issue_key": "ABC-1",
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


def _knowledge_doc() -> dict[str, Any]:
    item = {"statement": "검증 가능한 문장", "evidence_refs": ["summary"]}
    return {
        "knowledge_schema_version": "0.1",
        "issue_key": "ABC-1",
        "issue_summary": item,
        "problem_or_goal": [],
        "key_findings": [item],
        "actions_and_decisions": [],
        "outcomes": [],
        "open_items": [],
    }


def _review_doc() -> dict[str, Any]:
    return {
        "issue_key": "ABC-1",
        "score": 9.1,
        "verdict": "PASS",
        "critical_error": False,
        "major_issue_count": 0,
    }


def test_opencode_runtime_model_is_passed_to_headless_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    input_path = project_root / "input.json"
    output_path = project_root / "out" / "ABC-1.json"
    review_dir = project_root / "out" / "reviews"
    input_path.write_text(json.dumps(_input_doc(), ensure_ascii=False), encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path.parent.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_knowledge_doc(), ensure_ascii=False),
            encoding="utf-8",
        )
        (review_dir / "ABC-1.review.attempt1.json").write_text(
            json.dumps(_review_doc(), ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    processor = OpenCodeKnowledgeProcessor(
        project_root,
        model="codemate/CodeLLMPro",
        agent="jira-knowledge-orchestrator",
        timeout_seconds=120,
    )
    work = type("Work", (), {"observed_issue_key": "ABC-1"})()

    result = processor.process(
        work_item=work,
        input_path=input_path,
        output_path=output_path,
        review_dir=review_dir,
    )

    command = captured["command"]
    assert command[:6] == [
        "opencode",
        "run",
        "--model",
        "codemate/CodeLLMPro",
        "--agent",
        "jira-knowledge-orchestrator",
    ]
    assert "Per-Work 단일 Issue 모드" in command[-1]
    assert "shell 탐색을 하지 말고" in command[-1]
    assert captured["kwargs"]["timeout"] == 120
    assert result.final_attempt == 1


def test_opencode_runtime_model_rejects_blank_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model은 비어 있지 않은"):
        OpenCodeKnowledgeProcessor(tmp_path, model="   ")
