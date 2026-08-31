from pathlib import Path


FRAMEWORK = Path("docs/DOCUMENT_FRAMEWORK_STANDARD_2026-08-27.html")


def test_framework_preserves_explanations_when_visuals_change() -> None:
    text = FRAMEWORK.read_text(encoding="utf-8")
    assert "시각화는 설명을 대체하지 않고 보강한다" in text
    assert "기존의 유효한 설명" in text
    assert "그림" in text
    assert "상세 설명" in text
    assert "관계/표" in text
    assert "쉬운 예시" in text
    assert "Source of Truth" in text
