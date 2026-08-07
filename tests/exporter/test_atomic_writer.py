from __future__ import annotations

from pathlib import Path

from jira_collector.exporter.atomic_writer import AtomicTextWriter


def test_atomic_writer_replaces_existing_file(tmp_path: Path) -> None:
    """기존 파일이 있어도 새 내용으로 원자 교체되는지 확인합니다."""

    writer = AtomicTextWriter(tmp_path)
    target = tmp_path / "run1" / "result.txt"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")

    written = writer.write_text("run1/result.txt", "새 내용\n")

    assert written == target.resolve()
    assert target.read_text(encoding="utf-8") == "새 내용\n"
    assert not list(target.parent.glob("*.tmp"))


def test_atomic_writer_rejects_path_escape(tmp_path: Path) -> None:
    """분석 루트 밖으로 이동하는 상대 경로를 거부하는지 확인합니다."""

    writer = AtomicTextWriter(tmp_path / "analysis")

    try:
        writer.write_text("../outside.txt", "blocked")
    except ValueError as exc:
        assert "저장 루트 밖" in str(exc)
    else:
        raise AssertionError("경로 이동이 차단되지 않았습니다.")
