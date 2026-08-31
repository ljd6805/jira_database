from __future__ import annotations

from pathlib import Path


REPORT = Path("docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html")
GUIDE = Path("docs/architecture/jira_loop_b_opencode_automation_easy_guide.html")


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_loop_b_knowledge_report_exists_and_records_precise_gates() -> None:
    assert REPORT.is_file()
    text = _read(REPORT)
    assert "<!doctype html>" in text.lower()
    for token in (
        "AUTOMATION IMPLEMENTED",
        "CI PASS",
        "REAL INTERNAL OPENCODE RUN PENDING",
        "CONTINUOUS SCHEDULING NOT IMPLEMENTED",
        "knowledge_processing.py",
        "run_knowledge_worker.py",
        "jira-knowledge-orchestrator",
        "jira-knowledge-extraction",
        "Atomic Publish",
    ):
        assert token in text


def test_loop_b_easy_guide_records_pilot_prompt_agent_skill_mapping() -> None:
    assert GUIDE.is_file()
    text = _read(GUIDE)
    for token in (
        "파일럿",
        "opencode run",
        "jira-knowledge-orchestrator",
        "jira-knowledge-worker",
        "jira-knowledge-extraction",
        "jira-knowledge-reviewer",
        "동적 Prompt",
        "Real Internal OpenCode Run",
        "Continuous Scheduling",
        "Skill load",
    ):
        assert token in text


def test_loop_b_report_and_guide_are_linked_from_current_entry_docs() -> None:
    for path in (
        "docs/index.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html" in text, path
        assert "jira_loop_b_opencode_automation_easy_guide.html" in text, path


def test_current_docs_do_not_claim_real_opencode_or_full_publish_done() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "Loop B" in text and "Knowledge" in text
        assert "Atomic Publish" in text and "NEXT" in text
        assert "Loop B PUBLISHED DONE" not in text

    for path in (
        "docs/index.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        upper = text.upper()
        assert "OPENCODE" in upper and "PENDING" in upper
        assert "SCHEDUL" in upper and "NOT IMPLEMENTED" in upper


def test_loop_b_code_has_latest_staging_and_review_guards() -> None:
    source = _read("src/jira_collector/knowledge_processing.py")
    for token in (
        "opencode",
        "jira-knowledge-orchestrator",
        "staging",
        "validate_knowledge_document",
        "_assert_review_pass",
        "work_item_is_latest",
        "mark_knowledge_completed",
        "knowledge_generation_id",
    ):
        assert token in source


def test_worker_agent_requires_the_extraction_skill() -> None:
    worker = _read(".opencode/agents/jira-knowledge-worker.md")
    skill = _read(".opencode/skills/jira-knowledge-extraction/SKILL.md")
    assert '"jira-knowledge-extraction": allow' in worker
    assert "반드시 `jira-knowledge-extraction` Skill을 로드한다" in worker
    for token in ("입력에 없는 사실", "원문의 확실성", "Evidence", "Trade-off"):
        assert token in skill
