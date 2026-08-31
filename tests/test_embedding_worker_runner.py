from __future__ import annotations

import subprocess
import sys


def test_embedding_worker_runner_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "tools/run_embedding_worker.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Incremental Embedding" in result.stdout
    assert "--knowledge-db" in result.stdout
    assert "JIRA_KNOWLEDGE_DB_PATH" in result.stdout
    assert "--artifact-root" in result.stdout
    assert "--limit" in result.stdout
