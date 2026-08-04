from __future__ import annotations

import json
from pathlib import Path

import pytest

from jira_collector.exporter import RunWarningStore, RunWarningStoreError


def _read_lines(path: Path) -> list[dict[str, object]]:
    """테스트용 경고 JSONL을 객체 목록으로 읽습니다."""

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_preserves_other_component_and_replaces_current_component(
    tmp_path: Path,
) -> None:
    """다른 Exporter의 경고는 유지하고 현재 component 경고만 교체하는지 확인합니다."""

    data_root = tmp_path / "data"
    store = RunWarningStore(data_root)
    path = store.replace_component(
        "run1",
        "issues",
        [{"code": "issue_warning"}],
    )
    store.replace_component(
        "run1",
        "comments",
        [{"code": "comment_warning"}],
    )

    assert [
        (item["component"], item["code"])
        for item in _read_lines(path)
    ] == [
        ("issues", "issue_warning"),
        ("comments", "comment_warning"),
    ]

    store.replace_component("run1", "issues", [])
    assert [
        (item["component"], item["code"])
        for item in _read_lines(path)
    ] == [("comments", "comment_warning")]


def test_treats_legacy_warning_without_component_as_issue_warning(
    tmp_path: Path,
) -> None:
    """이전 이슈 전용 경고 문서에는 component가 없어도 issues로 해석하는지 확인합니다."""

    data_root = tmp_path / "data"
    path = data_root / "analysis" / "run1" / "parse_warnings.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"code":"legacy_issue_warning"}\n', encoding="utf-8")

    RunWarningStore(data_root).replace_component(
        "run1",
        "comments",
        [{"code": "comment_warning"}],
    )

    lines = _read_lines(path)
    assert lines[0]["code"] == "legacy_issue_warning"
    assert "component" not in lines[0]
    assert lines[1]["component"] == "comments"


def test_rejects_broken_warning_file_without_overwriting_it(
    tmp_path: Path,
) -> None:
    """깨진 기존 경고 파일은 자동으로 덮어쓰지 않고 오류를 발생시키는지 확인합니다."""

    data_root = tmp_path / "data"
    path = data_root / "analysis" / "run1" / "parse_warnings.jsonl"
    path.parent.mkdir(parents=True)
    original = "{not-json\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(RunWarningStoreError):
        RunWarningStore(data_root).replace_component(
            "run1",
            "comments",
            [],
        )

    assert path.read_text(encoding="utf-8") == original
