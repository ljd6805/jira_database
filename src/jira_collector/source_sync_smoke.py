from __future__ import annotations

from pathlib import Path

from .jira_client import JiraClient
from .raw_store import RawStore
from .source_sync import DiscoveredProject, OperationalSourceSync, SourceSyncError
from .state_store import StateStore


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
