from __future__ import annotations

from pathlib import Path

from .jira_client import JiraClient
from .raw_store import RawStore
from .source_sync import DiscoveredProject, OperationalSourceSync, SourceSyncError
from .state_store import StateStore


def validate_smoke_project_options(
    *,
    project_key: str | None,
    resume_source_run_id: str | None,
    data_root: Path,
) -> None:
    """--project-key Smoke Run의 production 오염 방지 규칙을 검증합니다."""

    if not project_key:
        return
    if resume_source_run_id:
        raise ValueError(
            "--project-key Smoke Run은 --resume-source-run-id와 함께 사용할 수 없습니다. "
            "실패하면 data_smoke를 비우고 새 Smoke Run으로 다시 실행하십시오."
        )
    if data_root.resolve().name != "data_smoke":
        raise ValueError(
            "--project-key는 격리된 Smoke 전용입니다. "
            "--local-config config/settings.smoke.yaml을 사용하십시오."
        )


class SmokeProjectSourceSync(OperationalSourceSync):
    """Smoke 전용: Project Discovery 결과 중 지정 Project 하나만 Source Sync합니다.

    이 클래스는 production partial ingest 용도가 아닙니다. 반드시 격리된 smoke data root와
    함께 사용합니다. 전체 Jira Project Discovery API 호출 자체는 그대로 수행하지만,
    snapshot/State/Watermark/Work Item은 선택한 Project 하나에 대해서만 생성합니다.
    """

    def __init__(
        self,
        client: JiraClient,
        raw_store: RawStore,
        state: StateStore,
        *,
        project_key: str,
        data_root: str | Path | None = None,
    ) -> None:
        super().__init__(client, raw_store, state, data_root=data_root)
        normalized = project_key.strip()
        if not normalized:
            raise ValueError("project_key는 비어 있을 수 없습니다.")
        self.project_key = normalized

    def _discover_projects(self, source_run_id: str) -> list[DiscoveredProject]:
        projects = super()._discover_projects(source_run_id)
        return [self._select_project(projects, self.project_key)]

    @staticmethod
    def _select_project(
        projects: list[DiscoveredProject],
        project_key: str,
    ) -> DiscoveredProject:
        target = project_key.strip().casefold()
        matches = [item for item in projects if item.key.casefold() == target]
        if not matches:
            visible = ", ".join(item.key for item in projects[:20]) or "(none)"
            raise SourceSyncError(
                f"Smoke 대상 Project를 찾을 수 없습니다: {project_key}. "
                f"현재 계정에서 보이는 Project 예: {visible}"
            )
        if len(matches) != 1:
            raise SourceSyncError(
                f"같은 Project key가 여러 project_id로 발견됐습니다: {project_key}"
            )
        return matches[0]
