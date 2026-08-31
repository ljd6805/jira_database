from __future__ import annotations

import subprocess
import sys


def test_source_sync_runner_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "tools/run_source_sync.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Loop A(Source Sync)" in result.stdout
    assert "--resume-source-run-id" in result.stdout
    assert "--max-issues-per-project" in result.stdout
    assert "테스트/파일럿 전용" in result.stdout
