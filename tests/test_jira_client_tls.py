from __future__ import annotations

from jira_collector.jira_client import JiraClient


class FakeSession:
    def __init__(self) -> None:
        self.auth = None
        self.verify = True
        self.headers: dict[str, str] = {}
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_applies_disabled_ssl_verification_to_session(app_settings) -> None:
    session = FakeSession()

    client = JiraClient(app_settings.jira, session=session)

    assert session.verify is False
    client.close()
    assert session.closed is True
