from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from jira_collector.knowledge_input.analysis_loader import AnalysisRunLoader

from .evidence import assert_accepted_evidence, parse_evidence_ref
from .ids import (
    KnowledgeContract,
    canonical_json,
    content_hash,
    issue_version_id,
    knowledge_attempt_id,
    knowledge_evidence_id,
    knowledge_generation_id,
    knowledge_item_id,
)
from .models import KnowledgeDbError, MaterializationResult
from .schema import connect_database, initialize_schema


_KNOWLEDGE_CATEGORIES = (
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
)
_REVIEW_FILE = re.compile(r"^(.+)\.review\.attempt([1-9][0-9]*)\.json$")


class KnowledgeDbMaterializer:
    """완료된 ANALYSIS/KNOWLEDGE 산출물을 SQLite Knowledge DB로 적재합니다."""

    def __init__(
        self,
        data_root: str | Path,
        database_path: str | Path,
        *,
        skill_version: str,
        runtime_version: str,
        model_profile: str,
        review_schema_version: str = "0.3",
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.database_path = Path(database_path).resolve()
        self.skill_version = _required_text(skill_version, "skill_version")
        self.runtime_version = _required_text(runtime_version, "runtime_version")
        self.model_profile = _required_text(model_profile, "model_profile")
        self.review_schema_version = _required_text(
            review_schema_version,
            "review_schema_version",
        )

    def materialize_run(self, run_id: str) -> MaterializationResult:
        """한 Run을 idempotent하게 적재하고 accepted Evidence round-trip을 검증합니다."""

        run_id = _required_text(run_id, "run_id")
        loaded = AnalysisRunLoader(self.data_root / "analysis").load(run_id)
        manifest, packages = self._load_packages(run_id)
        knowledge_docs = self._load_knowledge_docs(run_id)
        review_docs = self._load_review_docs(run_id)
        self._validate_artifact_sets(loaded, packages, knowledge_docs, review_docs)

        connection = connect_database(self.database_path)
        try:
            initialize_schema(connection)
            counts = {"generation": 0, "attempt": 0, "item": 0, "evidence": 0, "review": 0}
            with connection:
                self._load_pipeline_run(connection, run_id, loaded, manifest)
                self._load_source_entities(connection, run_id, loaded)
                for issue_key in sorted(packages):
                    current = self._load_issue_knowledge(
                        connection,
                        run_id,
                        packages[issue_key],
                        knowledge_docs[issue_key],
                        review_docs[issue_key],
                    )
                    for name, value in current.items():
                        counts[name] += value
                assert_accepted_evidence(connection)
        finally:
            connection.close()

        return MaterializationResult(
            run_id=run_id,
            database_path=self.database_path,
            issue_count=len(packages),
            generation_count=counts["generation"],
            attempt_count=counts["attempt"],
            knowledge_item_count=counts["item"],
            evidence_count=counts["evidence"],
            review_count=counts["review"],
        )

    def _load_packages(self, run_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """완료된 Knowledge Input manifest와 Issue package를 읽습니다."""

        root = self.data_root / "knowledge_input" / "runs" / run_id
        manifest = _read_json(root / "manifest.json")
        if manifest.get("run_id") != run_id or manifest.get("status") != "completed":
            raise KnowledgeDbError(f"완료된 Knowledge Input manifest가 아닙니다: {run_id}")

        issue_root = root / "issues"
        packages = _read_issue_documents(issue_root)
        for issue_key, package in packages.items():
            if package.get("run_id") != run_id or package.get("issue_key") != issue_key:
                raise KnowledgeDbError(f"Knowledge Input identity 불일치: {issue_key}")
        return manifest, packages

    def _load_knowledge_docs(self, run_id: str) -> dict[str, dict[str, Any]]:
        """Issue별 최종 Knowledge artifact를 읽습니다."""

        root = self.data_root / "knowledge" / "runs" / run_id / "issues"
        documents = _read_issue_documents(root)
        for issue_key, document in documents.items():
            if document.get("issue_key") != issue_key:
                raise KnowledgeDbError(f"Knowledge issue_key 불일치: {issue_key}")
        return documents

    def _load_review_docs(self, run_id: str) -> dict[str, dict[int, dict[str, Any]]]:
        """Attempt별 Review artifact를 issue_key/attempt_no로 인덱싱합니다."""

        root = self.data_root / "knowledge" / "runs" / run_id / "reviews"
        if not root.is_dir():
            raise KnowledgeDbError(f"Knowledge Review 디렉터리가 없습니다: {root}")

        result: dict[str, dict[int, dict[str, Any]]] = {}
        for path in sorted(root.glob("*.json")):
            match = _REVIEW_FILE.match(path.name)
            if match is None:
                raise KnowledgeDbError(f"Review 파일명이 계약과 다릅니다: {path.name}")
            issue_key, attempt_text = match.groups()
            attempt_no = int(attempt_text)
            document = _read_json(path)
            if document.get("issue_key") != issue_key:
                raise KnowledgeDbError(f"Review issue_key 불일치: {path.name}")
            issue_reviews = result.setdefault(issue_key, {})
            if attempt_no in issue_reviews:
                raise KnowledgeDbError(f"중복 Review Attempt입니다: {path.name}")
            issue_reviews[attempt_no] = document
        return result

    def _validate_artifact_sets(
        self,
        loaded: dict[str, Any],
        packages: dict[str, Any],
        knowledge_docs: dict[str, Any],
        review_docs: dict[str, Any],
    ) -> None:
        """ANALYSIS/Input/Knowledge/Review의 Issue 집합이 정확히 일치하는지 확인합니다."""

        expected = set(loaded["issues"])
        actual_sets = {
            "Knowledge Input": set(packages),
            "Knowledge": set(knowledge_docs),
            "Review": set(review_docs),
        }
        for label, actual in actual_sets.items():
            if actual != expected:
                missing = sorted(expected - actual)
                extra = sorted(actual - expected)
                raise KnowledgeDbError(
                    f"{label} Issue 집합 불일치: missing={missing}, extra={extra}"
                )

    def _load_pipeline_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        loaded: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        """Run metadata를 upsert합니다."""

        summary = _read_json(loaded["summary_path"])
        connection.execute(
            """
            INSERT INTO pipeline_run(
                run_id, status, generated_at,
                analysis_schema_version, knowledge_input_schema_version
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                generated_at=excluded.generated_at,
                analysis_schema_version=excluded.analysis_schema_version,
                knowledge_input_schema_version=excluded.knowledge_input_schema_version
            """,
            (
                run_id,
                str(manifest.get("status") or "completed"),
                manifest.get("generated_at"),
                summary.get("schema_version"),
                manifest.get("schema_version"),
            ),
        )

    def _load_source_entities(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        loaded: dict[str, Any],
    ) -> None:
        """ANALYSIS source Entity를 run-scoped 원본 테이블에 적재합니다."""

        for row in loaded["issues"].values():
            self._upsert_issue(connection, row)
        for row in _flatten(loaded["comments"].values()):
            _insert_source_comment(connection, row)
        for row in _flatten(loaded["attachments"].values()):
            _insert_source_attachment(connection, row)
        for row in loaded["relationship_rows"]:
            _insert_source_relationship(connection, row)
        for row in loaded["catalog"].values():
            _insert_custom_field_catalog(connection, row)
        for row in _flatten(loaded["custom_values"].values()):
            _insert_custom_field_value(connection, row)

    @staticmethod
    def _upsert_issue(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
        """Jira ID를 identity로 두고 현재 human-readable key를 갱신합니다."""

        jira_id = _required_text(row.get("jira_id"), "jira_id")
        issue_key = _required_text(row.get("issue_key"), "issue_key")
        connection.execute(
            """
            INSERT INTO issue(jira_id, issue_key, project_key)
            VALUES (?, ?, ?)
            ON CONFLICT(jira_id) DO UPDATE SET
                issue_key=excluded.issue_key,
                project_key=excluded.project_key
            """,
            (jira_id, issue_key, row.get("project_key")),
        )

    def _load_issue_knowledge(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        package: dict[str, Any],
        knowledge: dict[str, Any],
        reviews: dict[int, dict[str, Any]],
    ) -> dict[str, int]:
        """Issue Version부터 Generation/Attempt/Knowledge/Review까지 한 lineage를 적재합니다."""

        issue_key = _required_text(package.get("issue_key"), "issue_key")
        issue_doc = _required_dict(package.get("issue"), "issue")
        jira_id = _required_text(issue_doc.get("jira_id"), "jira_id")
        source_hash = _required_text(package.get("source_hash"), "source_hash")
        version_id = issue_version_id(jira_id, source_hash)
        self._ensure_issue_version(connection, run_id, issue_key, version_id, package)
        self._ensure_observation(connection, run_id, jira_id, issue_key, version_id)

        schema_version = _required_text(
            knowledge.get("knowledge_schema_version"),
            "knowledge_schema_version",
        )
        contract = KnowledgeContract(
            schema_version,
            self.skill_version,
            self.runtime_version,
            self.model_profile,
        )
        generation_id = knowledge_generation_id(version_id, contract.logical_hash())
        self._ensure_generation(
            connection,
            generation_id,
            version_id,
            jira_id,
            run_id,
            issue_key,
            source_hash,
            contract,
        )
        return self._load_attempts(
            connection,
            generation_id,
            jira_id,
            run_id,
            issue_key,
            knowledge,
            reviews,
        )

    def _ensure_issue_version(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        issue_key: str,
        version_id: str,
        package: dict[str, Any],
    ) -> None:
        """새 semantic Version만 immutable row로 추가합니다."""

        issue_doc = _required_dict(package.get("issue"), "issue")
        values = (
            version_id,
            _required_text(issue_doc.get("jira_id"), "jira_id"),
            _required_text(package.get("source_hash"), "source_hash"),
            run_id,
            issue_key,
            issue_doc.get("summary"),
            issue_doc.get("description"),
            issue_doc.get("description_format"),
            issue_doc.get("issue_type"),
            issue_doc.get("status"),
            issue_doc.get("priority"),
            issue_doc.get("created_at"),
            issue_doc.get("updated_at"),
            issue_doc.get("source_path"),
        )
        _insert_immutable(
            connection,
            "issue_version",
            (
                "issue_version_id", "jira_id", "source_hash", "source_run_id",
                "source_issue_key", "summary", "description", "description_format",
                "issue_type", "status", "priority", "created_at", "updated_at",
                "source_path",
            ),
            values,
            ("issue_version_id",),
        )

    @staticmethod
    def _ensure_observation(
        connection: sqlite3.Connection,
        run_id: str,
        jira_id: str,
        issue_key: str,
        version_id: str,
    ) -> None:
        """Run chronology와 semantic Version의 mapping을 immutable하게 기록합니다."""

        _insert_immutable(
            connection,
            "issue_version_observation",
            ("run_id", "jira_id", "observed_issue_key", "issue_version_id"),
            (run_id, jira_id, issue_key, version_id),
            ("run_id", "jira_id"),
        )

    @staticmethod
    def _ensure_generation(
        connection: sqlite3.Connection,
        generation_id: str,
        version_id: str,
        jira_id: str,
        run_id: str,
        issue_key: str,
        source_hash: str,
        contract: KnowledgeContract,
    ) -> None:
        """Generation의 immutable contract 필드를 확인하고 lifecycle 필드는 별도로 둡니다."""

        stable = (
            generation_id,
            version_id,
            jira_id,
            run_id,
            issue_key,
            source_hash,
            contract.logical_hash(),
            contract.knowledge_schema_version,
            contract.skill_version,
            contract.runtime_version,
            contract.model_profile,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_generation(
                knowledge_generation_id, issue_version_id, jira_id, source_run_id,
                source_issue_key, source_hash, knowledge_contract_hash,
                knowledge_schema_version, skill_version, runtime_version,
                model_profile, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate')
            """,
            stable,
        )
        row = connection.execute(
            """
            SELECT knowledge_generation_id, issue_version_id, jira_id, source_run_id,
                   source_issue_key, source_hash, knowledge_contract_hash,
                   knowledge_schema_version, skill_version, runtime_version, model_profile
            FROM knowledge_generation WHERE knowledge_generation_id=?
            """,
            (generation_id,),
        ).fetchone()
        if row is None or tuple(row) != stable:
            raise KnowledgeDbError(f"Knowledge Generation identity drift: {generation_id}")

    def _load_attempts(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        jira_id: str,
        run_id: str,
        issue_key: str,
        knowledge: dict[str, Any],
        reviews: dict[int, dict[str, Any]],
    ) -> dict[str, int]:
        """Review Attempt를 보존하고 최종 artifact가 속한 Attempt에만 Knowledge를 연결합니다."""

        if not reviews:
            raise KnowledgeDbError(f"Review Attempt가 없습니다: {issue_key}")
        attempt_numbers = sorted(reviews)
        expected = list(range(1, attempt_numbers[-1] + 1))
        if attempt_numbers != expected:
            raise KnowledgeDbError(f"Review Attempt가 연속적이지 않습니다: {issue_key}")

        final_no = attempt_numbers[-1]
        counters = {"generation": 1, "attempt": 0, "item": 0, "evidence": 0, "review": 0}
        final_attempt_id = ""
        for attempt_no in attempt_numbers:
            attempt_id = knowledge_attempt_id(generation_id, attempt_no)
            has_content = attempt_no == final_no
            self._ensure_attempt(connection, attempt_id, generation_id, attempt_no, knowledge if has_content else None)
            self._load_review(connection, attempt_id, issue_key, reviews[attempt_no])
            counters["attempt"] += 1
            counters["review"] += 1
            if has_content:
                item_count, evidence_count = self._load_knowledge_items(
                    connection,
                    attempt_id,
                    run_id,
                    issue_key,
                    knowledge,
                )
                counters["item"] += item_count
                counters["evidence"] += evidence_count
                final_attempt_id = attempt_id

        final_review = reviews[final_no]
        self._publish_generation(
            connection,
            generation_id,
            jira_id,
            final_attempt_id,
            str(final_review.get("verdict") or ""),
        )
        return counters

    @staticmethod
    def _ensure_attempt(
        connection: sqlite3.Connection,
        attempt_id: str,
        generation_id: str,
        attempt_no: int,
        knowledge: dict[str, Any] | None,
    ) -> None:
        """Legacy failed Attempt는 content unavailable로, final Attempt는 content hash와 함께 저장합니다."""

        values = (
            attempt_id,
            generation_id,
            attempt_no,
            content_hash(knowledge) if knowledge is not None else None,
            1 if knowledge is not None else 0,
            None,
            None,
        )
        _insert_immutable(
            connection,
            "knowledge_attempt",
            (
                "knowledge_attempt_id", "knowledge_generation_id", "attempt_no",
                "knowledge_content_hash", "content_available", "validator_status",
                "generated_at",
            ),
            values,
            ("knowledge_attempt_id",),
        )

    def _load_knowledge_items(
        self,
        connection: sqlite3.Connection,
        attempt_id: str,
        run_id: str,
        issue_key: str,
        knowledge: dict[str, Any],
    ) -> tuple[int, int]:
        """최종 Attempt의 generic Knowledge Item과 Evidence를 materialize합니다."""

        if knowledge.get("issue_key") != issue_key:
            raise KnowledgeDbError(f"Knowledge/Input issue_key 불일치: {issue_key}")

        entries: list[tuple[str, int, dict[str, Any]]] = [
            ("issue_summary", 0, _required_dict(knowledge.get("issue_summary"), "issue_summary"))
        ]
        for category in _KNOWLEDGE_CATEGORIES:
            items = knowledge.get(category)
            if not isinstance(items, list):
                raise KnowledgeDbError(f"Knowledge category가 배열이 아닙니다: {category}")
            entries.extend((category, ordinal, _required_dict(item, category)) for ordinal, item in enumerate(items))

        evidence_count = 0
        for category, ordinal, item in entries:
            item_id = knowledge_item_id(attempt_id, category, ordinal)
            statement = _required_text(item.get("statement"), f"{category}.statement")
            _insert_immutable(
                connection,
                "knowledge_item",
                ("knowledge_item_id", "knowledge_attempt_id", "category", "ordinal", "statement"),
                (item_id, attempt_id, category, ordinal, statement),
                ("knowledge_item_id",),
            )
            evidence_count += self._load_item_evidence(
                connection,
                item_id,
                run_id,
                issue_key,
                item.get("evidence_refs"),
            )
        return len(entries), evidence_count

    @staticmethod
    def _load_item_evidence(
        connection: sqlite3.Connection,
        item_id: str,
        run_id: str,
        issue_key: str,
        refs: Any,
    ) -> int:
        """Historical duplicate ref는 첫 occurrence만 DB에 materialize하고 raw ordinal은 보존합니다."""

        if not isinstance(refs, list) or not refs:
            raise KnowledgeDbError(f"Knowledge Item Evidence가 비어 있습니다: {item_id}")

        seen: set[str] = set()
        materialized_count = 0
        for ordinal, raw_ref in enumerate(refs):
            evidence_ref = _required_text(raw_ref, "evidence_ref")
            if evidence_ref in seen:
                continue
            seen.add(evidence_ref)
            evidence_type, entity_key = parse_evidence_ref(evidence_ref)
            evidence_id = knowledge_evidence_id(item_id, ordinal, evidence_ref)
            _insert_immutable(
                connection,
                "knowledge_evidence",
                (
                    "knowledge_evidence_id", "knowledge_item_id", "ordinal",
                    "evidence_ref", "evidence_type", "source_run_id",
                    "source_issue_key", "source_entity_key",
                ),
                (
                    evidence_id, item_id, ordinal, evidence_ref, evidence_type,
                    run_id, issue_key, entity_key,
                ),
                ("knowledge_evidence_id",),
            )
            materialized_count += 1
        return materialized_count

    def _load_review(
        self,
        connection: sqlite3.Connection,
        attempt_id: str,
        issue_key: str,
        review: dict[str, Any],
    ) -> None:
        """Attempt Review와 상세 Finding을 content hash 기반 immutable audit로 저장합니다."""

        if review.get("issue_key") != issue_key:
            raise KnowledgeDbError(f"Review/Input issue_key 불일치: {issue_key}")
        _validate_review(review)
        scores = _required_dict(review.get("category_scores"), "category_scores")
        review_hash = content_hash(review)
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_review(
                knowledge_attempt_id, review_schema_version, review_content_hash,
                score, verdict, critical_error, major_issue_count,
                factual_fidelity_score, evidence_coverage_score,
                certainty_preservation_score, classification_score,
                retrieval_value_score, language_quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id, self.review_schema_version, review_hash,
                float(review["score"]), str(review["verdict"]),
                int(bool(review["critical_error"])), int(review["major_issue_count"]),
                float(scores["factual_fidelity"]), float(scores["evidence_coverage"]),
                float(scores["certainty_preservation"]), float(scores["classification"]),
                float(scores["retrieval_value"]), float(scores["language_quality"]),
            ),
        )
        row = connection.execute(
            "SELECT knowledge_review_id, review_content_hash FROM knowledge_review WHERE knowledge_attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if row is None or row["review_content_hash"] != review_hash:
            raise KnowledgeDbError(f"Review Attempt content drift: {attempt_id}")
        self._load_review_findings(connection, int(row["knowledge_review_id"]), review)

    @staticmethod
    def _load_review_findings(
        connection: sqlite3.Connection,
        review_id: int,
        review: dict[str, Any],
    ) -> None:
        """Audit/Critical/Major/Improvement 구조를 하나의 queryable finding table로 펼칩니다."""

        audits = _required_dict(review.get("audit_findings"), "audit_findings")
        for category, items in audits.items():
            for ordinal, item in enumerate(_required_list(items, category)):
                finding = _required_dict(item, category)
                _insert_finding(
                    connection, review_id, "audit", "audit", category, ordinal,
                    "", finding.get("location"), finding.get("message"),
                )
        _insert_critical_findings(connection, review_id, review.get("critical_issues"))
        _insert_object_findings(connection, review_id, "major", review.get("major_issues"))
        _insert_object_findings(connection, review_id, "improvement", review.get("improvement_points"))

    @staticmethod
    def _publish_generation(
        connection: sqlite3.Connection,
        generation_id: str,
        jira_id: str,
        final_attempt_id: str,
        verdict: str,
    ) -> None:
        """PASS Generation만 active로 원자 전환하고 실패 Generation은 review_required로 둡니다."""

        if verdict == "PASS":
            connection.execute(
                """
                UPDATE knowledge_generation SET state='historical'
                WHERE jira_id=? AND state='active' AND knowledge_generation_id<>?
                """,
                (jira_id, generation_id),
            )
            connection.execute(
                """
                UPDATE knowledge_generation
                SET accepted_attempt_id=?, state='active'
                WHERE knowledge_generation_id=?
                """,
                (final_attempt_id, generation_id),
            )
            return
        if verdict == "REGENERATE":
            connection.execute(
                """
                UPDATE knowledge_generation
                SET accepted_attempt_id=NULL, state='review_required'
                WHERE knowledge_generation_id=? AND state<>'active'
                """,
                (generation_id,),
            )
            return
        raise KnowledgeDbError(f"지원하지 않는 Review verdict입니다: {verdict}")


def _insert_source_comment(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    _insert_immutable(
        connection,
        "comment",
        (
            "run_id", "issue_key", "comment_id", "sequence", "author_name",
            "author_key", "created_at", "updated_at", "body", "body_format",
            "source_path", "source_page",
        ),
        (
            row.get("run_id"), row.get("issue_key"), row.get("comment_id"),
            int(row.get("sequence") or 0), row.get("author_name"), row.get("author_key"),
            row.get("created_at"), row.get("updated_at"), row.get("body_text"),
            row.get("body_format"), row.get("source_path"), row.get("source_page"),
        ),
        ("run_id", "issue_key", "comment_id"),
    )


def _insert_source_attachment(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    _insert_immutable(
        connection,
        "attachment",
        (
            "run_id", "issue_key", "attachment_id", "filename", "author_name",
            "author_key", "created_at", "size_bytes", "mime_type",
            "content_available", "source_path",
        ),
        (
            row.get("run_id"), row.get("issue_key"), row.get("attachment_id"),
            row.get("filename"), row.get("author_name"), row.get("author_key"),
            row.get("created_at"), row.get("size_bytes"), row.get("mime_type"),
            int(bool(row.get("content_available", False))), row.get("source_path"),
        ),
        ("run_id", "attachment_id"),
    )


def _insert_source_relationship(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    _insert_immutable(
        connection,
        "relationship",
        (
            "run_id", "relationship_id", "relationship_category", "relationship_type",
            "relationship_text", "source_issue_key", "target_issue_key", "derived",
            "source_path",
        ),
        (
            row.get("run_id"), row.get("relationship_id"), row.get("relationship_category"),
            row.get("relationship_type"), row.get("relationship_text"),
            row.get("source_issue_key"), row.get("target_issue_key"),
            int(bool(row.get("derived", False))), row.get("source_path"),
        ),
        ("run_id", "relationship_id"),
    )


def _insert_custom_field_catalog(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    _insert_immutable(
        connection,
        "custom_field_catalog",
        (
            "run_id", "field_id", "field_name", "schema_type", "schema_items",
            "schema_custom", "schema_custom_id",
        ),
        (
            row.get("run_id"), row.get("field_id"), row.get("field_name"),
            row.get("schema_type"), _text_or_json(row.get("schema_items")),
            row.get("schema_custom"), _text_or_json(row.get("schema_custom_id")),
        ),
        ("run_id", "field_id"),
    )


def _insert_custom_field_value(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    _insert_immutable(
        connection,
        "custom_field_value",
        (
            "run_id", "issue_key", "field_id", "actual_type", "value_kind",
            "display_value", "display_values_json", "value_id", "value_ids_json",
            "user_keys_json", "value_shape_json", "source_path",
        ),
        (
            row.get("run_id"), row.get("issue_key"), row.get("field_id"),
            row.get("actual_type"), row.get("value_kind"), row.get("display_value"),
            _json_or_none(row.get("display_values")), row.get("value_id"),
            _json_or_none(row.get("value_ids")), _json_or_none(row.get("user_keys")),
            _json_or_none(row.get("value_shape")), row.get("source_path"),
        ),
        ("run_id", "issue_key", "field_id"),
    )


def _insert_immutable(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    values: tuple[Any, ...],
    key_columns: tuple[str, ...],
) -> None:
    """같은 identity 재적재는 허용하되 기존 immutable 내용이 달라지면 실패합니다."""

    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR IGNORE INTO {table}({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    key_values = tuple(values[columns.index(name)] for name in key_columns)
    where = " AND ".join(f"{name}=?" for name in key_columns)
    row = connection.execute(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {where}",
        key_values,
    ).fetchone()
    if row is None or tuple(row) != values:
        identity = ", ".join(f"{key}={value}" for key, value in zip(key_columns, key_values))
        raise KnowledgeDbError(f"Immutable row drift: {table}({identity})")


def _insert_finding(
    connection: sqlite3.Connection,
    review_id: int,
    group: str,
    severity: str,
    audit_category: str,
    ordinal: int,
    finding_type: Any,
    location: Any,
    message: Any,
) -> None:
    """Review finding 한 건을 deterministic 위치 key로 idempotent하게 적재합니다."""

    values = (
        review_id, group, severity, audit_category, ordinal,
        str(finding_type or ""), str(location or ""), _required_text(message, "finding.message"),
    )
    _insert_immutable(
        connection,
        "review_finding",
        (
            "knowledge_review_id", "finding_group", "severity", "audit_category",
            "ordinal", "finding_type", "location", "message",
        ),
        values,
        ("knowledge_review_id", "finding_group", "audit_category", "ordinal"),
    )


def _insert_critical_findings(
    connection: sqlite3.Connection,
    review_id: int,
    raw_items: Any,
) -> None:
    """Current 문자열과 legacy M4 object 형식의 Critical Finding을 모두 보존합니다."""

    for ordinal, raw in enumerate(_required_list(raw_items, "critical_issues")):
        if isinstance(raw, str):
            _insert_finding(
                connection, review_id, "critical", "critical", "", ordinal,
                "", "", raw,
            )
            continue
        item = _required_dict(raw, "critical_issues")
        _insert_finding(
            connection,
            review_id,
            "critical",
            "critical",
            "",
            ordinal,
            item.get("type"),
            item.get("location"),
            item.get("message"),
        )


def _insert_object_findings(
    connection: sqlite3.Connection,
    review_id: int,
    group: str,
    raw_items: Any,
) -> None:
    """Major/Improvement object 배열을 공통 finding 구조로 저장합니다."""

    for ordinal, raw in enumerate(_required_list(raw_items, group)):
        item = _required_dict(raw, group)
        _insert_finding(
            connection,
            review_id,
            group,
            group,
            "",
            ordinal,
            item.get("type"),
            item.get("location"),
            item.get("message"),
        )


def _validate_review(review: dict[str, Any]) -> None:
    """Reviewer verdict와 PASS gate의 최소 정합성을 deterministic하게 확인합니다."""

    try:
        score = float(review["score"])
        verdict = str(review["verdict"])
        critical = bool(review["critical_error"])
        major_count = int(review["major_issue_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KnowledgeDbError("Review 필수 점수/판정 필드가 잘못됐습니다.") from exc

    if verdict not in {"PASS", "REGENERATE"}:
        raise KnowledgeDbError(f"지원하지 않는 Review verdict입니다: {verdict}")
    if verdict == "PASS" and (score < 8.5 or critical or major_count != 0):
        raise KnowledgeDbError("PASS Review가 score/critical/major Gate와 모순됩니다.")


def _read_issue_documents(root: Path) -> dict[str, dict[str, Any]]:
    """Issue 파일명 stem을 identity로 사용해 JSON 문서를 읽습니다."""

    if not root.is_dir():
        raise KnowledgeDbError(f"Issue artifact 디렉터리가 없습니다: {root}")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        issue_key = path.stem
        if issue_key in result:
            raise KnowledgeDbError(f"중복 Issue artifact입니다: {issue_key}")
        result[issue_key] = _read_json(path)
    if not result:
        raise KnowledgeDbError(f"Issue artifact가 없습니다: {root}")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    """UTF-8 JSON object만 허용합니다."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeDbError(f"JSON을 읽을 수 없습니다: {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise KnowledgeDbError(f"JSON object가 아닙니다: {path}")
    return document


def _required_text(value: Any, label: str) -> str:
    """필수 문자열을 정규화합니다."""

    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDbError(f"필수 문자열이 없습니다: {label}")
    return value.strip()


def _required_dict(value: Any, label: str) -> dict[str, Any]:
    """필수 JSON object 타입을 확인합니다."""

    if not isinstance(value, dict):
        raise KnowledgeDbError(f"JSON object가 필요합니다: {label}")
    return value


def _required_list(value: Any, label: str) -> list[Any]:
    """필수 JSON array 타입을 확인합니다."""

    if not isinstance(value, list):
        raise KnowledgeDbError(f"JSON array가 필요합니다: {label}")
    return value


def _flatten(groups: Iterable[list[dict[str, Any]]]) -> Iterable[dict[str, Any]]:
    """issue_key별 그룹을 source row stream으로 평탄화합니다."""

    for group in groups:
        yield from group


def _json_or_none(value: Any) -> str | None:
    """Multi-value가 존재할 때만 canonical JSON text로 저장합니다."""

    return None if value is None else canonical_json(value)


def _text_or_json(value: Any) -> Any:
    """Scalar는 그대로, list/dict는 canonical JSON text로 저장합니다."""

    return canonical_json(value) if isinstance(value, (list, dict)) else value
