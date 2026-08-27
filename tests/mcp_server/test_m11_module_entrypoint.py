from __future__ import annotations

import subprocess
import sys


def test_mcp_package_does_not_eager_import_server_module() -> None:
    """``python -m jira_collector.mcp_server.server``의 runpy 경고 원인을 막습니다."""

    command = (
        "import sys; "
        "import jira_collector.mcp_server; "
        "print('jira_collector.mcp_server.server' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
    assert "RuntimeWarning" not in result.stderr
