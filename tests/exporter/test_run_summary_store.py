from __future__ import annotations

import json
from pathlib import Path

import pytest

from jira_collector.exporter import RunSummaryError, RunSummaryStore


def test_creates_summary_when_file_does_not_exist(tmp_path: Path) -> None:
    """기존 요약이 없으면 not_run 기본 영역과 새 댓글 통계를 생성하는지 확인합니다."""

    data_root = tmp_path / "data"
    path = RunSummaryStore(data_root).update_section(
        "run1",
        "comments",
        {"status": "completed", "exported_count": 8},
        {"comments": "analysis/run1/comments.jsonl"},
    )
    summary = json.loads(path.read_text(encoding="utf-8"))

    assert summary["schema_version"] == "2.0"
    assert summary["run_id"] == "run1"
    assert summary["status"] == "incomplete"
    assert summary["issues"]["status"] == "not_run"
    assert summary["comments"]["exported_count"] == 8


def test_rejects_invalid_json_without_overwriting_existing_file(
    tmp_path: Path,
) -> None:
    """깨진 기존 요약은 자동 복구로 덮어쓰지 않고 원문을 보존하는지 확인합니다."""

    data_root = tmp_path / "data"
    path = data_root / "analysis" / "run1" / "summary.json"
    path.parent.mkdir(parents=True)
    original = "{not-json"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(RunSummaryError):
        RunSummaryStore(data_root).update_section(
            "run1",
            "comments",
            {"status": "completed"},
            {},
        )

    assert path.read_text(encoding="utf-8") == original


def test_rejects_run_id_mismatch(tmp_path: Path) -> None:
    """경로와 summary 내부 run_id가 다르면 서로 다른 실행 통계를 합치지 않는지 확인합니다."""

    data_root = tmp_path / "data"
    path = data_root / "analysis" / "run1" / "summary.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "run_id": "other-run",
                "issues": {"status": "not_run"},
                "comments": {"status": "not_run"},
                "output_files": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RunSummaryError):
        RunSummaryStore(data_root).update_section(
            "run1",
            "issues",
            {"status": "completed"},
            {},
        )
