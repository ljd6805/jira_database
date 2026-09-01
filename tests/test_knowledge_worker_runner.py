from __future__ import annotations

import subprocess
import sys


def test_knowledge_worker_help_is_available() -> None:
    result = subprocess.run(
        [sys.executable, "tools/run_knowledge_worker.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "latest-only Knowledge stage" in result.stdout
    assert "--model-profile" in result.stdout
    assert "--opencode-model" in result.stdout
    assert "codemate/CodeLLMPro" in result.stdout
    assert "--opencode-attach" in result.stdout
    assert "--stale-after-seconds" in result.stdout
    assert "--limit" in result.stdout
    assert "Embedding/Publish" in result.stdout
