from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


_HTML_TAG_PATTERN = re.compile(r"<[A-Za-z][^>]*>")


class JiraHtmlTextExtractor(HTMLParser):
    """Convert Jira-rendered HTML into readable text without executing it."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
    _IGNORED_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.lower()
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if normalized == "br":
            self._parts.append("\n")
        elif normalized == "li":
            self._parts.append("\n- ")
        elif normalized in {"td", "th"} and self._parts:
            self._parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data:
            self._parts.append(data)

    def text(self) -> str:
        decoded = unescape("".join(self._parts)).replace("\xa0", " ")
        normalized_lines: list[str] = []
        for raw_line in decoded.splitlines():
            line = re.sub(r"[ \t\r\f\v]+", " ", raw_line).strip()
            if line:
                normalized_lines.append(line)
        return "\n".join(normalized_lines)


def nested_value(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def named_value(value: Any) -> str | None:
    if isinstance(value, str):
        return optional_string(value)
    if not isinstance(value, dict):
        return None
    for key in ("displayName", "name", "value", "key", "id"):
        candidate = optional_string(value.get(key))
        if candidate is not None:
            return candidate
    return None


def looks_like_html(value: str) -> bool:
    return bool(_HTML_TAG_PATTERN.search(value))


def html_to_text(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    parser = JiraHtmlTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text() or None


def value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__
