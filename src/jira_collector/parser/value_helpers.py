from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


_HTML_TAG_PATTERN = re.compile(r"<[A-Za-z][^>]*>")


class JiraHtmlTextExtractor(HTMLParser):
    """Jira HTML을 실행하지 않고 사람이 읽을 수 있는 텍스트로 변환합니다."""

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
        """텍스트 조각과 무시할 태그의 중첩 깊이를 초기화합니다."""

        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """시작 태그를 해석해 줄바꿈과 목록·표 구분자를 추가합니다."""

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
        """종료 태그를 해석해 블록 요소 뒤에 줄바꿈을 추가합니다."""

        normalized = tag.lower()
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if normalized in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        """script와 style 영역이 아닌 실제 텍스트만 수집합니다."""

        if not self._ignored_depth and data:
            self._parts.append(data)

    def text(self) -> str:
        """수집한 텍스트를 디코딩하고 공백과 빈 줄을 정리해 반환합니다."""

        decoded = unescape("".join(self._parts)).replace("\xa0", " ")
        normalized_lines: list[str] = []
        for raw_line in decoded.splitlines():
            line = re.sub(r"[ \t\r\f\v]+", " ", raw_line).strip()
            if line:
                normalized_lines.append(line)
        return "\n".join(normalized_lines)


def nested_value(data: Any, *keys: str) -> Any:
    """중첩된 딕셔너리에서 여러 키를 안전하게 따라가 값을 반환합니다."""

    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def optional_string(value: Any) -> str | None:
    """문자열 또는 단순 값을 공백이 제거된 선택 문자열로 변환합니다."""

    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def named_value(value: Any) -> str | None:
    """Jira 객체에서 사람이 읽을 수 있는 대표 이름을 우선순위대로 찾습니다."""

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
    """문자열에 HTML 태그로 보이는 패턴이 포함됐는지 확인합니다."""

    return bool(_HTML_TAG_PATTERN.search(value))


def html_to_text(value: str | None) -> str | None:
    """HTML 문자열에서 검색과 분석에 사용할 일반 텍스트를 추출합니다."""

    if value is None or not value.strip():
        return None
    parser = JiraHtmlTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text() or None


def value_type_name(value: Any) -> str:
    """Python 값을 분석 보고서에서 사용할 안정적인 타입 이름으로 변환합니다."""

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
