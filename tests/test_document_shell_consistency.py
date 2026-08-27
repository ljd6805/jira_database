from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path("docs")
HUB = DOCS / "index.html"
ASSETS = DOCS / "assets"
REGISTRY = ASSETS / "document-registry.js"
HUB_SECTION_IDS = (
    "hub-start",
    "hub-roadmap",
    "hub-service",
    "hub-milestones",
    "hub-reference",
)


def _documents() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.html") if path != HUB)


def _asset_prefix(path: Path) -> str:
    return Path(os.path.relpath(ASSETS, path.parent)).as_posix()


def test_hub_uses_locked_frame_v1() -> None:
    text = HUB.read_text(encoding="utf-8")
    assert 'data-hub-frame="v1"' in text
    assert 'href="assets/hub-frame.css" data-hub-frame="v1"' in text
    assert not re.search(r"<style\b", text, flags=re.IGNORECASE)
    for section_id in HUB_SECTION_IDS:
        assert f'id="{section_id}"' in text


def test_every_html_document_uses_common_shell_v1() -> None:
    documents = _documents()
    assert documents
    for path in documents:
        text = path.read_text(encoding="utf-8")
        prefix = _asset_prefix(path)
        assert 'data-doc-shell="v1"' in text, path
        assert f'href="{prefix}/document-shell.css" data-doc-shell="v1"' in text, path
        assert f'src="{prefix}/document-navigation.js" data-doc-shell="v1"' in text, path


def test_navigation_contract_keeps_previous_hub_next_visible() -> None:
    text = (ASSETS / "document-navigation.js").read_text(encoding="utf-8")
    for token in (
        'control("previous", "← 이전 문서"',
        'control("hub", "⌂ 문서 Hub"',
        'control("next", "다음 문서 →"',
        'aria-disabled',
        'doc-global-nav--top',
        'doc-global-nav--bottom',
    ):
        assert token in text


def test_registry_covers_every_document() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    match = re.search(r"Object\.freeze\((\[.*\])\);", text, flags=re.DOTALL)
    assert match
    registry = json.loads(match.group(1))
    registered = [entry["path"] for entry in registry]
    expected = [path.relative_to(DOCS).as_posix() for path in _documents()]
    assert len(registered) == len(set(registered))
    assert set(registered) == set(expected)


def test_document_shell_sync_check_is_clean() -> None:
    result = subprocess.run(
        [sys.executable, "tools/docs/sync_document_shell.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DOCUMENT_SHELL_CHECK = PASS" in result.stdout
