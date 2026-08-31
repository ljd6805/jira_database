from pathlib import Path


AGENTS = Path("AGENTS.md")
POLICY = Path("docs/DOCUMENTATION_POLICY.html")
SKILL = Path(".opencode/skills/html-diagram-visual-qa/SKILL.md")


def test_visualization_must_preserve_existing_explanations() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")

    for text in (agents, policy, skill):
        assert "시각화는 설명을 대체하지 않고 보강한다" in text
        assert "기존의 유효한 설명" in text
        assert "그림 → 상세 설명 → 관계/표 → 쉬운 예시 → Source of Truth" in text


def test_visual_refactor_requires_explicit_reason_for_content_removal() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")

    for text in (agents, policy, skill):
        assert "사용자가 명시적으로 삭제/축약을 요청" in text
        assert "오래되어 틀린 내용" in text
        assert "삭제 이유를 문서에 남긴다" in text
