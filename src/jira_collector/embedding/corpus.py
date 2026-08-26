from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from jira_collector.knowledge_db import KnowledgeDbError, connect_database


CORPUS_SCHEMA_VERSION = "0.1"
TEXT_PROFILE_STATEMENT_V1 = "statement_v1"

_CATEGORY_ORDER = (
    "issue_summary",
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
)
_CORPUS_FIELDS = {
    "corpus_schema_version",
    "text_profile",
    "knowledge_item_id",
    "knowledge_attempt_id",
    "knowledge_generation_id",
    "issue_version_id",
    "jira_id",
    "category",
    "ordinal",
    "embedding_text",
    "embedding_text_hash",
}

_ACTIVE_CORPUS_SQL = """
SELECT
    ki.knowledge_item_id,
    ki.knowledge_attempt_id,
    ka.knowledge_generation_id,
    kg.issue_version_id,
    kg.jira_id,
    ki.category,
    ki.ordinal,
    ki.statement
FROM knowledge_generation AS kg
JOIN knowledge_attempt AS ka
  ON ka.knowledge_attempt_id = kg.accepted_attempt_id
 AND ka.knowledge_generation_id = kg.knowledge_generation_id
JOIN knowledge_item AS ki
  ON ki.knowledge_attempt_id = ka.knowledge_attempt_id
WHERE kg.state = 'active'
  AND kg.accepted_attempt_id IS NOT NULL
  AND ka.content_available = 1
ORDER BY
    kg.jira_id,
    CASE ki.category
        WHEN 'issue_summary' THEN 0
        WHEN 'problem_or_goal' THEN 1
        WHEN 'key_findings' THEN 2
        WHEN 'actions_and_decisions' THEN 3
        WHEN 'outcomes' THEN 4
        WHEN 'open_items' THEN 5
        ELSE 99
    END,
    ki.ordinal,
    ki.knowledge_item_id
"""


@dataclass(frozen=True)
class EmbeddingCorpusRow:
    """BGE-M3 호출 전 deterministic embedding corpus 한 행입니다."""

    corpus_schema_version: str
    text_profile: str
    knowledge_item_id: str
    knowledge_attempt_id: str
    knowledge_generation_id: str
    issue_version_id: str
    jira_id: str
    category: str
    ordinal: int
    embedding_text: str
    embedding_text_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_active_embedding_corpus(
    database_path: str | Path,
    *,
    text_profile: str = TEXT_PROFILE_STATEMENT_V1,
) -> tuple[EmbeddingCorpusRow, ...]:
    """M7 DB에서 active accepted Knowledge Item만 deterministic 순서로 읽습니다."""

    _validate_text_profile(text_profile)
    connection = connect_database(database_path)
    try:
        rows = connection.execute(_ACTIVE_CORPUS_SQL).fetchall()
    finally:
        connection.close()

    return tuple(_build_row(row, text_profile) for row in rows)


def load_embedding_corpus_file(path: str | Path) -> tuple[EmbeddingCorpusRow, ...]:
    """M8-01 JSONL을 다시 읽고 schema/text hash를 deterministic하게 검증합니다."""

    source = Path(path).resolve()
    if not source.is_file():
        raise KnowledgeDbError(f"Embedding corpus 파일이 없습니다: {source}")
    result: list[EmbeddingCorpusRow] = []
    for line_no, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            document = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise KnowledgeDbError(f"Corpus JSONL 파싱 실패: line={line_no}: {exc}") from exc
        result.append(_corpus_row_from_document(document, line_no))
    if not result:
        raise KnowledgeDbError(f"Embedding corpus가 비어 있습니다: {source}")
    return tuple(result)


def export_embedding_corpus(
    database_path: str | Path,
    output_path: str | Path,
    *,
    text_profile: str = TEXT_PROFILE_STATEMENT_V1,
) -> tuple[EmbeddingCorpusRow, ...]:
    """active accepted corpus를 deterministic UTF-8 JSONL로 저장합니다."""

    rows = load_active_embedding_corpus(database_path, text_profile=text_profile)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_json_line(row) for row in rows)
    destination.write_text(payload, encoding="utf-8")
    return rows


def _build_row(row, text_profile: str) -> EmbeddingCorpusRow:
    category = str(row["category"])
    if category not in _CATEGORY_ORDER:
        raise KnowledgeDbError(f"지원하지 않는 Knowledge category입니다: {category}")

    embedding_text = _embedding_text(str(row["statement"]), text_profile)
    return EmbeddingCorpusRow(
        corpus_schema_version=CORPUS_SCHEMA_VERSION,
        text_profile=text_profile,
        knowledge_item_id=str(row["knowledge_item_id"]),
        knowledge_attempt_id=str(row["knowledge_attempt_id"]),
        knowledge_generation_id=str(row["knowledge_generation_id"]),
        issue_version_id=str(row["issue_version_id"]),
        jira_id=str(row["jira_id"]),
        category=category,
        ordinal=int(row["ordinal"]),
        embedding_text=embedding_text,
        embedding_text_hash=_sha256_text(embedding_text),
    )


def _corpus_row_from_document(document: object, line_no: int) -> EmbeddingCorpusRow:
    if not isinstance(document, dict) or set(document) != _CORPUS_FIELDS:
        raise KnowledgeDbError(f"Corpus row 필드가 계약과 다릅니다: line={line_no}")
    if document.get("corpus_schema_version") != CORPUS_SCHEMA_VERSION:
        raise KnowledgeDbError(f"Corpus schema version 불일치: line={line_no}")
    text_profile = str(document.get("text_profile"))
    _validate_text_profile(text_profile)
    category = str(document.get("category"))
    if category not in _CATEGORY_ORDER:
        raise KnowledgeDbError(f"Corpus category가 잘못됐습니다: line={line_no}")
    ordinal = document.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
        raise KnowledgeDbError(f"Corpus ordinal이 잘못됐습니다: line={line_no}")
    embedding_text = document.get("embedding_text")
    if not isinstance(embedding_text, str) or not embedding_text.strip():
        raise KnowledgeDbError(f"Corpus embedding_text가 비어 있습니다: line={line_no}")
    expected_hash = _sha256_text(embedding_text)
    if document.get("embedding_text_hash") != expected_hash:
        raise KnowledgeDbError(f"Corpus embedding_text_hash 불일치: line={line_no}")
    return EmbeddingCorpusRow(
        corpus_schema_version=CORPUS_SCHEMA_VERSION,
        text_profile=text_profile,
        knowledge_item_id=_required_text(document.get("knowledge_item_id"), line_no),
        knowledge_attempt_id=_required_text(document.get("knowledge_attempt_id"), line_no),
        knowledge_generation_id=_required_text(document.get("knowledge_generation_id"), line_no),
        issue_version_id=_required_text(document.get("issue_version_id"), line_no),
        jira_id=_required_text(document.get("jira_id"), line_no),
        category=category,
        ordinal=ordinal,
        embedding_text=embedding_text,
        embedding_text_hash=expected_hash,
    )


def _embedding_text(statement: str, text_profile: str) -> str:
    _validate_text_profile(text_profile)
    text = statement.strip()
    if not text:
        raise KnowledgeDbError("Embedding text가 비어 있습니다: statement")
    return text


def _validate_text_profile(text_profile: str) -> None:
    if text_profile != TEXT_PROFILE_STATEMENT_V1:
        raise ValueError(f"지원하지 않는 embedding text profile입니다: {text_profile}")


def _required_text(value: object, line_no: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDbError(f"Corpus 필수 문자열이 비어 있습니다: line={line_no}")
    return value.strip()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_line(row: EmbeddingCorpusRow) -> str:
    return json.dumps(
        row.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
