from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jira_collector.state_store import StateStore

from .evidence import assert_accepted_evidence
from .ids import (
    KnowledgeContract,
    issue_version_id,
    knowledge_attempt_id,
    knowledge_generation_id,
)
from .loader import (
    KnowledgeDbMaterializer,
    _insert_custom_field_catalog,
    _insert_custom_field_value,
    _insert_source_attachment,
    _insert_source_comment,
    _insert_source_relationship,
    _read_json,
)
from .models import KnowledgeDbError
from .schema import connect_database, initialize_schema


@dataclass(frozen=True)
class IncrementalMaterializationResult:
    work_item_id: str
    source_run_id: str
    issue_key: str
    issue_version_id: str
    knowledge_generation_id: str
    final_attempt_id: str
    attempt_count: int
    knowledge_item_count: int
    evidence_count: int
    review_count: int
    generation_state: str


class StaleKnowledgeWorkError(KnowledgeDbError):
    """Knowledge DB 반영 직전에 Work가 더 이상 latest가 아니게 된 경우입니다."""


class IncrementalKnowledgeDbMaterializer(KnowledgeDbMaterializer):
    """Loop B Work Item 하나를 Knowledge DB candidate Generation으로 idempotent 적재합니다.

    운영 경로에서는 Review PASS가 나와도 즉시 ``active``로 전환하지 않습니다.
    기존 Published Retrieval이 참조하는 last-known-good active Generation을 보존하기 위해
    ``candidate + accepted_attempt_id``까지만 준비하고, active 전환은 FAISS Publish 단계가 맡습니다.
    """

    ANALYSIS_SCHEMA_VERSION = "operational_issue_v1"

    def __init__(
        self,
        state: StateStore,
        data_root: str | Path,
        database_path: str | Path,
        *,
        skill_version: str,
        runtime_version: str,
        model_profile: str,
        review_schema_version: str = "0.3",
    ) -> None:
        super().__init__(
            data_root,
            database_path,
            skill_version=skill_version,
            runtime_version=runtime_version,
            model_profile=model_profile,
            review_schema_version=review_schema_version,
        )
        self.state = state

    def materialize_work(self, work_item_id: str) -> IncrementalMaterializationResult:
        work = self.state.get_work_item(work_item_id)
        self._validate_state_work(work)
        if not self.state.work_item_is_latest(work_item_id, log_stale=True):
            raise StaleKnowledgeWorkError(f"latest Work가 아닙니다: {work_item_id}")

        source_run_id = str(work["last_observed_source_run_id"])
        issue_key = str(work["observed_issue_key"])
        analysis = self._load_analysis(source_run_id, issue_key, str(work["project_id"]))
        package = self._load_input_package(source_run_id, issue_key)
        knowledge = self._load_knowledge(source_run_id, issue_key)
        reviews = self._load_issue_reviews(source_run_id, issue_key)
        self._validate_artifact_identity(work, analysis, package, knowledge)

        contract = KnowledgeContract(
            knowledge_schema_version=str(knowledge.get("knowledge_schema_version") or ""),
            skill_version=self.skill_version,
            runtime_version=self.runtime_version,
            model_profile=self.model_profile,
        )
        expected_version_id = issue_version_id(str(work["jira_id"]), str(work["source_hash"]))
        expected_generation_id = knowledge_generation_id(
            expected_version_id,
            contract.logical_hash(),
        )
        if work.get("issue_version_id") != expected_version_id:
            raise KnowledgeDbError(
                f"State issue_version_id 불일치: expected={expected_version_id}, "
                f"actual={work.get('issue_version_id')}"
            )
        if work.get("knowledge_generation_id") != expected_generation_id:
            raise KnowledgeDbError(
                "State knowledge_generation_id 불일치: "
                f"expected={expected_generation_id}, actual={work.get('knowledge_generation_id')}"
            )

        connection = connect_database(self.database_path)
        try:
            initialize_schema(connection)
            with connection:
                self._ensure_operational_pipeline_run(
                    connection,
                    source_run_id,
                    str(package.get("package_schema_version") or ""),
                )
                self._load_operational_source_entities(connection, analysis)

                issue_row = _required_dict(analysis.get("issue"), "issue")
                self._upsert_issue(connection, issue_row)
                jira_id = str(issue_row.get("jira_id") or "")
                if jira_id != str(work["jira_id"]):
                    raise KnowledgeDbError(
                        f"Knowledge DB jira_id 불일치: state={work['jira_id']}, analysis={jira_id}"
                    )

                self._ensure_issue_version(
                    connection,
                    source_run_id,
                    issue_key,
                    expected_version_id,
                    package,
                )
                version_id = expected_version_id
                self._ensure_observation(
                    connection,
                    source_run_id,
                    jira_id,
                    issue_key,
                    version_id,
                )
                self._ensure_generation(
                    connection,
                    expected_generation_id,
                    version_id,
                    jira_id,
                    source_run_id,
                    issue_key,
                    str(package["source_hash"]),
                    contract,
                )
                counters, final_attempt_id = self._load_candidate_attempts(
                    connection,
                    expected_generation_id,
                    source_run_id,
                    issue_key,
                    knowledge,
                    reviews,
                )

                # cross-DB transaction은 불가능하므로 active switch는 여기서 하지 않습니다.
                # 최소한 candidate commit 직전 latest를 다시 확인해 이미 stale인 결과는 전부 rollback합니다.
                if not self.state.work_item_is_latest(work_item_id, log_stale=True):
                    raise StaleKnowledgeWorkError(
                        f"Knowledge DB commit 직전에 stale이 됐습니다: {work_item_id}"
                    )

                self._accept_candidate_generation(
                    connection,
                    expected_generation_id,
                    final_attempt_id,
                )
                assert_accepted_evidence(connection)
                state = self._generation_state(connection, expected_generation_id)
        finally:
            connection.close()

        return IncrementalMaterializationResult(
            work_item_id=work_item_id,
            source_run_id=source_run_id,
            issue_key=issue_key,
            issue_version_id=expected_version_id,
            knowledge_generation_id=expected_generation_id,
            final_attempt_id=final_attempt_id,
            attempt_count=counters["attempt"],
            knowledge_item_count=counters["item"],
            evidence_count=counters["evidence"],
            review_count=counters["review"],
            generation_state=state,
        )

    @staticmethod
    def _validate_state_work(work: dict[str, object]) -> None:
        if work.get("knowledge_status") != "completed":
            raise KnowledgeDbError(
                f"Knowledge checkpoint가 completed가 아닙니다: {work.get('work_item_id')}"
            )
        if work.get("work_status") not in {"pending", "published"}:
            raise KnowledgeDbError(
                f"Materialize 가능한 Work 상태가 아닙니다: {work.get('work_status')}"
            )
        if work.get("last_source_committed_run_id") != work.get("last_observed_source_run_id"):
            raise KnowledgeDbError("Source Ready Gate가 열리지 않은 Work입니다.")
        if work.get("superseded_by_work_item_id") is not None:
            raise KnowledgeDbError("superseded Work는 Knowledge DB materialize 대상이 아닙니다.")
        if not work.get("issue_version_id") or not work.get("knowledge_generation_id"):
            raise KnowledgeDbError("State에 iv_/kg_ checkpoint가 없습니다.")

    def _load_analysis(
        self,
        source_run_id: str,
        issue_key: str,
        project_id: str,
    ) -> dict[str, Any]:
        project = self.state.get_project_state(project_id)
        project_key = str(project["current_key"])
        path = (
            self.data_root
            / "analysis"
            / source_run_id
            / "projects"
            / project_key
            / "issues"
            / issue_key
            / "analysis.json"
        )
        document = _read_json(path)
        if document.get("source_run_id") != source_run_id:
            raise KnowledgeDbError(f"Analysis source_run_id 불일치: {path}")
        if str(document.get("project_id") or "") != project_id:
            raise KnowledgeDbError(f"Analysis project_id 불일치: {path}")
        issue = document.get("issue")
        if not isinstance(issue, dict) or issue.get("issue_key") != issue_key:
            raise KnowledgeDbError(f"Analysis issue_key 불일치: {path}")
        return document

    def _load_input_package(self, source_run_id: str, issue_key: str) -> dict[str, Any]:
        path = (
            self.data_root
            / "knowledge_input"
            / "runs"
            / source_run_id
            / "issues"
            / f"{issue_key}.json"
        )
        package = _read_json(path)
        if package.get("run_id") != source_run_id or package.get("issue_key") != issue_key:
            raise KnowledgeDbError(f"Knowledge Input identity 불일치: {path}")
        if package.get("source_hash_profile") != "semantic_v2":
            raise KnowledgeDbError(f"semantic_v2 package가 아닙니다: {path}")
        return package

    def _load_knowledge(self, source_run_id: str, issue_key: str) -> dict[str, Any]:
        path = (
            self.data_root
            / "knowledge"
            / "runs"
            / source_run_id
            / "issues"
            / f"{issue_key}.json"
        )
        knowledge = _read_json(path)
        if knowledge.get("issue_key") != issue_key:
            raise KnowledgeDbError(f"Knowledge issue_key 불일치: {path}")
        return knowledge

    def _load_issue_reviews(
        self,
        source_run_id: str,
        issue_key: str,
    ) -> dict[int, dict[str, Any]]:
        root = self.data_root / "knowledge" / "runs" / source_run_id / "reviews"
        if not root.is_dir():
            raise KnowledgeDbError(f"Knowledge Review 디렉터리가 없습니다: {root}")
        result: dict[int, dict[str, Any]] = {}
        pattern = re.compile(
            rf"^{re.escape(issue_key)}\.review\.attempt([1-9][0-9]*)\.json$"
        )
        for path in sorted(root.glob(f"{issue_key}.review.attempt*.json")):
            match = pattern.match(path.name)
            if match is None:
                raise KnowledgeDbError(f"Review 파일명이 계약과 다릅니다: {path.name}")
            attempt_no = int(match.group(1))
            review = _read_json(path)
            if review.get("issue_key") != issue_key:
                raise KnowledgeDbError(f"Review issue_key 불일치: {path}")
            if attempt_no in result:
                raise KnowledgeDbError(f"중복 Review Attempt: {path}")
            result[attempt_no] = review
        if not result:
            raise KnowledgeDbError(f"Review Attempt가 없습니다: {issue_key}")
        return result

    @staticmethod
    def _validate_artifact_identity(
        work: dict[str, object],
        analysis: dict[str, Any],
        package: dict[str, Any],
        knowledge: dict[str, Any],
    ) -> None:
        issue = analysis.get("issue")
        if not isinstance(issue, dict):
            raise KnowledgeDbError("Analysis issue가 객체가 아닙니다.")
        if str(issue.get("jira_id") or "") != str(work["jira_id"]):
            raise KnowledgeDbError("Analysis jira_id와 State jira_id가 다릅니다.")
        if package.get("source_hash") != work.get("source_hash"):
            raise KnowledgeDbError("Knowledge Input source_hash와 State source_hash가 다릅니다.")
        if package.get("source_hash_profile") != work.get("source_hash_profile"):
            raise KnowledgeDbError("Knowledge Input source_hash_profile과 State가 다릅니다.")
        if knowledge.get("issue_key") != work.get("observed_issue_key"):
            raise KnowledgeDbError("Knowledge issue_key와 State observed_issue_key가 다릅니다.")

    def _ensure_operational_pipeline_run(
        self,
        connection: sqlite3.Connection,
        source_run_id: str,
        input_schema_version: str,
    ) -> None:
        values = (
            source_run_id,
            self.ANALYSIS_SCHEMA_VERSION,
            input_schema_version or None,
            "completed",
            None,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO pipeline_run(
                run_id, analysis_schema_version, knowledge_input_schema_version,
                status, generated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            values,
        )
        row = connection.execute(
            """
            SELECT run_id, analysis_schema_version, knowledge_input_schema_version,
                   status, generated_at
            FROM pipeline_run WHERE run_id=?
            """,
            (source_run_id,),
        ).fetchone()
        if row is None or tuple(row) != values:
            raise KnowledgeDbError(f"pipeline_run identity drift: {source_run_id}")

    @staticmethod
    def _load_operational_source_entities(
        connection: sqlite3.Connection,
        analysis: dict[str, Any],
    ) -> None:
        comments = analysis.get("comments")
        attachments = analysis.get("attachments")
        relationships = analysis.get("relationships")
        catalog = analysis.get("custom_field_catalog")
        custom_fields = analysis.get("custom_fields")
        if not isinstance(comments, list):
            raise KnowledgeDbError("Analysis comments가 배열이 아닙니다.")
        if not isinstance(attachments, list):
            raise KnowledgeDbError("Analysis attachments가 배열이 아닙니다.")
        if not isinstance(relationships, list):
            raise KnowledgeDbError("Analysis relationships가 배열이 아닙니다.")
        if not isinstance(catalog, dict):
            raise KnowledgeDbError("Analysis custom_field_catalog가 객체가 아닙니다.")
        if not isinstance(custom_fields, list):
            raise KnowledgeDbError("Analysis custom_fields가 배열이 아닙니다.")

        for row in comments:
            _insert_source_comment(connection, _required_dict(row, "comment"))
        for row in attachments:
            _insert_source_attachment(connection, _required_dict(row, "attachment"))
        for row in relationships:
            _insert_source_relationship(connection, _required_dict(row, "relationship"))
        for row in catalog.values():
            _insert_custom_field_catalog(
                connection,
                _required_dict(row, "custom_field_definition"),
            )
        for row in custom_fields:
            _insert_custom_field_value(
                connection,
                _required_dict(row, "custom_field_value"),
            )

    def _load_candidate_attempts(
        self,
        connection: sqlite3.Connection,
        generation_id: str,
        run_id: str,
        issue_key: str,
        knowledge: dict[str, Any],
        reviews: dict[int, dict[str, Any]],
    ) -> tuple[dict[str, int], str]:
        if not reviews:
            raise KnowledgeDbError(f"Review Attempt가 없습니다: {issue_key}")
        attempt_numbers = sorted(reviews)
        expected = list(range(1, attempt_numbers[-1] + 1))
        if attempt_numbers != expected:
            raise KnowledgeDbError(f"Review Attempt가 연속적이지 않습니다: {issue_key}")

        final_no = attempt_numbers[-1]
        counters = {"attempt": 0, "item": 0, "evidence": 0, "review": 0}
        final_attempt_id = ""
        for attempt_no in attempt_numbers:
            attempt_id = knowledge_attempt_id(generation_id, attempt_no)
            has_content = attempt_no == final_no
            self._ensure_attempt(
                connection,
                attempt_id,
                generation_id,
                attempt_no,
                knowledge if has_content else None,
            )
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
        if str(final_review.get("verdict") or "") != "PASS":
            raise KnowledgeDbError(
                f"Operational materializer는 PASS Generation만 받습니다: {issue_key}"
            )
        return counters, final_attempt_id

    @staticmethod
    def _accept_candidate_generation(
        connection: sqlite3.Connection,
        generation_id: str,
        final_attempt_id: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT state, accepted_attempt_id
            FROM knowledge_generation
            WHERE knowledge_generation_id=?
            """,
            (generation_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeDbError(f"Generation이 없습니다: {generation_id}")
        state = str(row["state"])
        accepted = row["accepted_attempt_id"]
        if state == "active" and accepted == final_attempt_id:
            # A→B→A처럼 이미 Published됐던 semantic Generation이 다시 최신인 경우 재사용합니다.
            return
        if state not in {"candidate", "historical"}:
            raise KnowledgeDbError(
                f"Operational candidate로 사용할 수 없는 Generation state입니다: {state}"
            )
        connection.execute(
            """
            UPDATE knowledge_generation
            SET state='candidate', accepted_attempt_id=?
            WHERE knowledge_generation_id=?
            """,
            (final_attempt_id, generation_id),
        )

    @staticmethod
    def _generation_state(connection: sqlite3.Connection, generation_id: str) -> str:
        row = connection.execute(
            "SELECT state FROM knowledge_generation WHERE knowledge_generation_id=?",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeDbError(f"Generation이 없습니다: {generation_id}")
        return str(row["state"])


def _required_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise KnowledgeDbError(f"{label}은 객체여야 합니다.")
    return value


__all__ = [
    "IncrementalKnowledgeDbMaterializer",
    "IncrementalMaterializationResult",
    "StaleKnowledgeWorkError",
]
