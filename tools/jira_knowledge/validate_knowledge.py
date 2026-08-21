#!/usr/bin/env python3
"""Knowledge JSON 구조와 Evidence reference 존재 여부를 검증한다."""

from __future__ import annotations
import json, re, sys
from pathlib import Path

EVIDENCE_RE = re.compile(
    r"^(summary|description|comment:[^:]+|attachment:[^:]+|"
    r"relationship:[^:]+|custom_field:[^:]+)$"
)

FIELDS = {
    "knowledge_schema_version", "issue_key", "issue_summary",
    "problem_or_goal", "key_findings", "actions_and_decisions",
    "outcomes", "open_items"
}
ARRAY_FIELDS = (
    "problem_or_goal", "key_findings", "actions_and_decisions",
    "outcomes", "open_items"
)

def load(path: Path):
    """JSON object를 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))

def refs_from_input(doc):
    """Input에서 허용 Evidence 집합을 만든다."""
    refs = {"summary", "description"}
    for field, key, prefix in (
        ("comments", "comment_id", "comment"),
        ("attachments", "attachment_id", "attachment"),
        ("relationships", "relationship_id", "relationship"),
        ("custom_fields", "field_id", "custom_field"),
    ):
        for item in doc.get(field, []):
            if item.get(key):
                refs.add(f"{prefix}:{item[key]}")
    return refs

def check_item(item, loc, valid):
    """Knowledge Item 구조를 검사한다."""
    errors = []
    if not isinstance(item, dict):
        return [f"{loc}: object 필요"]
    if set(item) != {"statement", "evidence_refs"}:
        errors.append(f"{loc}: 필드 오류")
    if not isinstance(item.get("statement"), str) or not item["statement"].strip():
        errors.append(f"{loc}.statement: 문자열 필요")
    refs = item.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        errors.append(f"{loc}.evidence_refs: 1개 이상 필요")
        return errors
    for ref in refs:
        if not isinstance(ref, str) or not EVIDENCE_RE.fullmatch(ref):
            errors.append(f"{loc}: 잘못된 Evidence 형식 {ref!r}")
        elif ref not in valid:
            errors.append(f"{loc}: Input에 없는 Evidence {ref}")
    return errors

def validate(k, i):
    """Knowledge 전체를 검사한다."""
    errors = []
    if set(k) != FIELDS:
        errors.append("최상위 필드 불일치")
    if k.get("knowledge_schema_version") != "0.1":
        errors.append("knowledge_schema_version != 0.1")
    if k.get("issue_key") != i.get("issue_key"):
        errors.append("issue_key 불일치")
    valid = refs_from_input(i)
    errors += check_item(k.get("issue_summary"), "issue_summary", valid)
    for field in ARRAY_FIELDS:
        values = k.get(field)
        if not isinstance(values, list):
            errors.append(f"{field}: 배열 필요")
            continue
        for idx, item in enumerate(values):
            errors += check_item(item, f"{field}[{idx}]", valid)
    return errors

def main():
    """CLI 진입점."""
    if len(sys.argv) != 3:
        print("사용법: validate_knowledge.py <knowledge> <input>", file=sys.stderr)
        return 2
    try:
        k = load(Path(sys.argv[1]))
        i = load(Path(sys.argv[2]))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1
    errors = validate(k, i)
    if errors:
        print(f"[FAIL] {len(errors)}건")
        for e in errors:
            print(" -", e)
        return 1
    print("[PASS] 구조와 Evidence reference가 유효합니다.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
