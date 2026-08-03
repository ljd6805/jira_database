from __future__ import annotations

import json
from pathlib import Path

import pytest

from jira_collector.raw_store import RawStore


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
