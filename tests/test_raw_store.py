from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jira_collector.raw_store import RawStore


class WindowsSharingViolation(OSError):
    winerror = 32


def test_saves_json_atomically_and_verifies_hash(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "data")
    artifact = store.save_json("runs/run1/test.json", {"message": "안녕하세요"})

    target = tmp_path / "data" / artifact.relative_path
    assert json.loads(target.read_text(encoding="utf-8")) == {"message": "안녕하세요"}
    assert store.verify(artifact.relative_path, artifact.content_sha256)
    assert not list(target.parent.glob("*.tmp"))


def test_rejects_path_traversal(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "data")
    with pytest.raises(ValueError):
        store.save_json("../../outside.json", {"bad": True})


def test_retries_transient_windows_file_lock(tmp_path: Path) -> None:
    attempts = 0
    delays: list[float] = []

    def flaky_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise WindowsSharingViolation("file is temporarily locked")
        os.replace(source, target)

    store = RawStore(
        tmp_path / "data",
        replace_attempts=4,
        replace_initial_delay_seconds=0.1,
        replace_max_delay_seconds=0.2,
        sleeper=delays.append,
        replacer=flaky_replace,
    )

    artifact = store.save_json("runs/run1/retry.json", {"ok": True})
    target = tmp_path / "data" / artifact.relative_path

    assert attempts == 3
    assert delays == [0.1, 0.2]
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert not list(target.parent.glob("*.tmp"))


def test_cleanup_failure_does_not_hide_original_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_error = WindowsSharingViolation("target remains locked")

    def always_locked(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
    ) -> None:
        raise original_error

    def cleanup_fails(path: str | os.PathLike[str]) -> None:
        raise PermissionError("temporary file is also locked")

    store = RawStore(
        tmp_path / "data",
        replace_attempts=1,
        sleeper=lambda _: None,
        replacer=always_locked,
    )
    monkeypatch.setattr("jira_collector.raw_store.os.unlink", cleanup_fails)

    with pytest.raises(WindowsSharingViolation) as raised:
        store.save_json("runs/run1/fail.json", {"ok": False})

    assert raised.value is original_error
