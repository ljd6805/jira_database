from __future__ import annotations

import re
from pathlib import Path


HUB = Path("docs/index.html")
HREF_PATTERN = re.compile(r'<a\b[^>]*\bhref=["\']([^"\']+)["\']', re.IGNORECASE)
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _local_hrefs() -> list[str]:
    """Documentation Hub의 로컬 anchor 링크만 반환합니다."""

    text = HUB.read_text(encoding="utf-8")
    return [
        href
        for href in HREF_PATTERN.findall(text)
        if not href.lower().startswith(EXTERNAL_PREFIXES)
    ]


def _path_part(href: str) -> str:
    """fragment/query를 제외한 로컬 파일 경로를 반환합니다."""

    return href.split("#", 1)[0].split("?", 1)[0]


def test_documentation_hub_links_only_html_documents() -> None:
    """Hub가 Markdown이나 다른 문서 형식을 직접 노출하지 않게 합니다."""

    bad_links = [
        href
        for href in _local_hrefs()
        if Path(_path_part(href)).suffix.lower() != ".html"
    ]
    assert not bad_links, f"docs/index.html has non-HTML local links: {bad_links}"


def test_documentation_hub_local_html_targets_exist() -> None:
    """Hub가 존재하지 않는 HTML 문서를 가리키지 않게 합니다."""

    missing = []
    for href in _local_hrefs():
        target = HUB.parent / _path_part(href)
        if not target.is_file():
            missing.append(href)

    assert not missing, f"docs/index.html has missing local targets: {missing}"
