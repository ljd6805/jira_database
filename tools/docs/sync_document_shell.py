from __future__ import annotations

import argparse
import html
import json
import os
import posixpath
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
HUB = DOCS / "index.html"
POLICY = DOCS / "DOCUMENTATION_POLICY.html"
AGENTS = ROOT / "AGENTS.md"
ASSETS = DOCS / "assets"
REGISTRY = ASSETS / "document-registry.js"
HUB_SECTIONS = (
    ("hub-start", "지금 어디부터 읽나?"),
    ("hub-roadmap", "전체를 한 줄씩만 보면"),
    ("hub-service", "운영 서비스 핵심"),
    ("hub-milestones", "Milestone Visual Documents"),
    ("hub-reference", "Architecture / Policy"),
)
HREF_PATTERN = re.compile(r'<a\b[^>]*\bhref=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
STYLE_PATTERN = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
POLICY_MARKER = "DOCUMENT SHELL V1 · 고정 프레임"
AGENT_MARKER = "Document Shell v1 고정 규칙"


def _all_documents() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.html") if path != HUB)


def _asset_prefix(path: Path) -> str:
    relative = os.path.relpath(ASSETS, path.parent)
    return Path(relative).as_posix()


def _shell_tags(path: Path) -> str:
    prefix = _asset_prefix(path)
    return (
        f'<link rel="stylesheet" href="{prefix}/document-shell.css" data-doc-shell="v1">\n'
        f'<script defer src="{prefix}/document-navigation.js" data-doc-shell="v1"></script>'
    )


def _strip_existing_shell_tags(text: str) -> str:
    patterns = (
        r'<link\b[^>]*data-doc-shell=["\']v1["\'][^>]*>\s*',
        r'<script\b[^>]*data-doc-shell=["\']v1["\'][^>]*>\s*</script>\s*',
    )
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text


def _ensure_document_shell(text: str, path: Path) -> str:
    text = _strip_existing_shell_tags(text)
    if 'data-doc-shell="v1"' not in text.split("<head", 1)[0]:
        text = re.sub(r"<html\b", '<html data-doc-shell="v1"', text, count=1, flags=re.IGNORECASE)
    if "</head>" not in text.lower():
        raise ValueError(f"{path}: </head> not found")
    return re.sub(r"</head>", _shell_tags(path) + "</head>", text, count=1, flags=re.IGNORECASE)


def _assign_hub_section_ids(text: str) -> str:
    for index, (section_id, heading) in enumerate(HUB_SECTIONS, start=1):
        if f'id="{section_id}"' in text:
            continue
        pattern = rf'<section(?![^>]*\bid=)[^>]*>\s*<h2>{index}\.\s*{re.escape(heading)}</h2>'
        replacement = (
            f'<section id="{section_id}" data-hub-section="{index}">'
            f'<h2>{index}. {heading}</h2>'
        )
        text, count = re.subn(pattern, replacement, text, count=1, flags=re.IGNORECASE)
        if count == 0:
            raise ValueError(f"Hub fixed section missing: {index}. {heading}")
    return text


def _inject_framework_note(text: str) -> str:
    href = "DOCUMENT_FRAMEWORK_STANDARD_2026-08-27.html"
    if href in text:
        return text
    match = re.search(
        r'(<section id="hub-reference"[^>]*>\s*<h2>.*?</h2>)',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("Hub reference section heading not found")
    note = (
        '<p class="framework-note"><strong>문서 UI 규칙:</strong> '
        '<a class="btn" href="DOCUMENT_FRAMEWORK_STANDARD_2026-08-27.html">Document Framework v1</a> '
        '<a class="btn alt" href="DOCUMENTATION_POLICY.html">Documentation Policy</a></p>'
    )
    return text[: match.end()] + note + text[match.end() :]


def _ensure_hub_frame(text: str) -> str:
    text = re.sub(
        r"<html\b(?![^>]*data-hub-frame)",
        '<html data-hub-frame="v1"',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = STYLE_PATTERN.sub("", text, count=1)
    text = re.sub(
        r'<link\b[^>]*data-hub-frame=["\']v1["\'][^>]*>\s*',
        "",
        text,
        flags=re.IGNORECASE,
    )
    tag = '<link rel="stylesheet" href="assets/hub-frame.css" data-hub-frame="v1">'
    text = re.sub(r"</head>", tag + "</head>", text, count=1, flags=re.IGNORECASE)
    return _inject_framework_note(_assign_hub_section_ids(text))


def _ensure_policy_rules(text: str) -> str:
    if POLICY_MARKER in text:
        return text
    marker = '<section><h2>2. 왜 이렇게 바꾸는가</h2>'
    if marker not in text:
        raise ValueError("Documentation Policy section 2 marker not found")
    section = (
        '<section id="document-shell-v1"><h2>1.5. DOCUMENT SHELL V1 · 고정 프레임</h2>'
        '<div class="callout good"><strong>2026-08-27 고정 규칙</strong><br>'
        'Hub는 <code>assets/hub-frame.css</code>의 v1 구조를 사용하고, 모든 일반 HTML 문서는 '
        '<code>assets/document-shell.css</code> + <code>document-navigation.js</code>를 사용합니다.</div>'
        '<ul><li>모든 문서는 <strong>이전 문서 / 문서 Hub / 다음 문서</strong> 세 버튼을 항상 표시합니다.</li>'
        '<li>첫/마지막 문서도 버튼을 숨기지 않고 disabled 상태로 자리를 유지합니다.</li>'
        '<li>Hub의 5개 기본 영역과 공통 스타일은 임의로 재구성하지 않습니다.</li>'
        '<li>새 HTML 문서는 템플릿을 복사하고 <code>python tools/docs/sync_document_shell.py --write</code>를 실행합니다.</li>'
        '<li>완료 전 <code>--check</code>와 문서 회귀 테스트를 통과해야 합니다.</li></ul></section>'
    )
    return text.replace(marker, section + marker, 1)


def _ensure_agent_rules(text: str) -> str:
    if AGENT_MARKER in text:
        return text
    marker = "## 2. Milestone HTML은 필수 산출물이다"
    if marker not in text:
        raise ValueError("AGENTS.md section 2 marker not found")
    rules = (
        "## 1.1 Document Shell v1 고정 규칙\n\n"
        "- `docs/index.html`은 `data-hub-frame=\"v1\"` 구조와 `docs/assets/hub-frame.css`를 사용한다.\n"
        "- 모든 일반 HTML은 `data-doc-shell=\"v1\"`과 공통 shell CSS/JS를 포함한다.\n"
        "- `이전 문서 / 문서 Hub / 다음 문서` 버튼은 항상 유지한다. 첫/마지막 문서는 숨기지 않고 disabled로 표시한다.\n"
        "- 새 HTML 작성 후 `python tools/docs/sync_document_shell.py --write`를 실행하고 `--check`를 통과시킨다.\n"
        "- Hub 기본 5개 영역 또는 shell 계약을 바꿀 때는 임의 수정하지 말고 Documentation Policy와 Framework 문서를 함께 갱신한다.\n\n"
    )
    return text.replace(marker, rules + marker, 1)


def _hub_link_order(hub_text: str) -> list[str]:
    order: list[str] = []
    for href in HREF_PATTERN.findall(hub_text):
        path_part = href.split("#", 1)[0].split("?", 1)[0]
        if not path_part.lower().endswith(".html") or "://" in path_part or path_part.startswith("/"):
            continue
        normalized = posixpath.normpath(path_part)
        if normalized != "index.html" and normalized not in order:
            order.append(normalized)
    return order


def _title(path: Path) -> str:
    match = TITLE_PATTERN.search(path.read_text(encoding="utf-8"))
    if match:
        value = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        if value:
            return value
    return path.stem.replace("_", " ")


def _registry_entries() -> list[dict[str, str]]:
    existing = {path.relative_to(DOCS).as_posix(): path for path in _all_documents()}
    order = [item for item in _hub_link_order(HUB.read_text(encoding="utf-8")) if item in existing]
    order.extend(sorted(item for item in existing if item not in order))
    return [{"path": item, "title": _title(existing[item])} for item in order]


def _registry_text() -> str:
    payload = json.dumps(_registry_entries(), ensure_ascii=False, indent=2)
    return (
        "// GENERATED by tools/docs/sync_document_shell.py --write. DO NOT EDIT BY HAND.\n"
        f"window.JIRA_DOCUMENT_REGISTRY = Object.freeze({payload});\n"
    )


def _write_if_changed(path: Path, text: str) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def write_all() -> int:
    changed = 0
    changed += int(_write_if_changed(HUB, _ensure_hub_frame(HUB.read_text(encoding="utf-8"))))
    changed += int(_write_if_changed(POLICY, _ensure_policy_rules(POLICY.read_text(encoding="utf-8"))))
    changed += int(_write_if_changed(AGENTS, _ensure_agent_rules(AGENTS.read_text(encoding="utf-8"))))
    for path in _all_documents():
        updated = _ensure_document_shell(path.read_text(encoding="utf-8"), path)
        changed += int(_write_if_changed(path, updated))
    changed += int(_write_if_changed(REGISTRY, _registry_text()))
    print(f"DOCUMENT_SHELL_WRITE changed_files={changed}")
    return 0


def _expected_shell_tokens(path: Path) -> tuple[str, str, str]:
    prefix = _asset_prefix(path)
    return (
        'data-doc-shell="v1"',
        f'href="{prefix}/document-shell.css" data-doc-shell="v1"',
        f'src="{prefix}/document-navigation.js" data-doc-shell="v1"',
    )


def check_all() -> int:
    errors: list[str] = []
    hub = HUB.read_text(encoding="utf-8")
    if 'data-hub-frame="v1"' not in hub or 'assets/hub-frame.css' not in hub:
        errors.append("docs/index.html: hub frame v1 marker/assets missing")
    if re.search(r"<style\b", hub, flags=re.IGNORECASE):
        errors.append("docs/index.html: inline <style> is forbidden; use assets/hub-frame.css")
    for section_id, _ in HUB_SECTIONS:
        if f'id="{section_id}"' not in hub:
            errors.append(f"docs/index.html: missing fixed section {section_id}")
    if POLICY_MARKER not in POLICY.read_text(encoding="utf-8"):
        errors.append("docs/DOCUMENTATION_POLICY.html: shell v1 rule missing")
    if AGENT_MARKER not in AGENTS.read_text(encoding="utf-8"):
        errors.append("AGENTS.md: shell v1 rule missing")
    for path in _all_documents():
        text = path.read_text(encoding="utf-8")
        for token in _expected_shell_tokens(path):
            if token not in text:
                errors.append(f"{path.relative_to(ROOT)}: missing {token}")
    if not REGISTRY.exists() or REGISTRY.read_text(encoding="utf-8") != _registry_text():
        errors.append("docs/assets/document-registry.js: out of sync")
    if errors:
        print("DOCUMENT_SHELL_CHECK = FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"DOCUMENT_SHELL_CHECK = PASS docs={len(_all_documents())} hub_frame=v1")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Jira Knowledge HTML 문서 shell v1 동기화/검증")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="모든 HTML 문서를 shell v1로 동기화")
    mode.add_argument("--check", action="store_true", help="동기화 상태만 검증")
    args = parser.parse_args()
    return write_all() if args.write else check_all()


if __name__ == "__main__":
    raise SystemExit(main())
