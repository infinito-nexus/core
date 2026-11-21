"""Unit test: the orchestrator creates a requirement work package as
``Proposed`` under the acting agent's token on the board ``BOARD_URL`` names,
and an agent starts only an ``Approved`` work package of its role's group."""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.orchestrator.board import Board, startable
from utils.roles.mapping import ROLE_FILE_META_SERVICES

LOCAL = "https://openproject.infinito.example"
REMOTE = "https://board.live.example"
STATUSES = {
    "_embedded": {
        "elements": [
            {"name": "Approved", "_links": {"self": {"href": "/api/v3/statuses/8"}}},
            {"name": "Proposed", "_links": {"self": {"href": "/api/v3/statuses/7"}}},
        ]
    }
}
ROLE = PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator"


class _Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, dict | None]] = []

    def __call__(self, method: str, url: str, headers: dict, body: dict | None):
        self.requests.append((method, url, headers, body))
        return STATUSES if method == "GET" else {"id": 31, **(body or {})}


class TestCreateWorkPackage(unittest.TestCase):
    def test_the_work_package_is_proposed_under_the_agents_token(self) -> None:
        transport = _Transport()
        Board(LOCAL, transport).create_work_package(
            "requirements", "Dark mode", "As a user ...\n- [ ] works", "plan-token"
        )
        method, url, headers, body = transport.requests[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(url, f"{LOCAL}/api/v3/projects/requirements/work_packages")
        self.assertEqual(headers["Authorization"], "Bearer plan-token")
        self.assertEqual(body["_links"]["status"]["href"], "/api/v3/statuses/7")
        self.assertEqual(body["description"]["raw"], "As a user ...\n- [ ] works")

    def test_a_board_without_the_status_refuses(self) -> None:
        board = Board(LOCAL, lambda *_: {"_embedded": {"elements": []}})
        with self.assertRaises(LookupError):
            board.create_work_package("requirements", "x", "y", "plan-token")


class TestBoardUrl(unittest.TestCase):
    def test_an_overridden_board_url_receives_every_board_request(self) -> None:
        transport = _Transport()
        Board(f"{REMOTE}/", transport).create_work_package(
            "requirements", "x", "y", "plan-token"
        )
        self.assertTrue(
            all(
                url.startswith(f"{REMOTE}/api/v3/")
                for _, url, _, _ in transport.requests
            )
        )

    def test_the_default_board_is_the_local_openproject(self) -> None:
        services = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
        self.assertIn(
            "lookup('tls', 'web-app-openproject', 'url.origin')",
            services["agent-orchestrator"]["board_url"],
        )
        env = read_text(str(ROLE / "templates" / "env.j2"))
        self.assertIn("BOARD_URL={{ AGENT_ORCHESTRATOR_BOARD_URL", env)


class TestStartable(unittest.TestCase):
    def _wp(self, status: str, assignee: str) -> dict:
        return {
            "_links": {"status": {"title": status}, "assignee": {"title": assignee}}
        }

    def test_only_an_approved_work_package_of_the_role_group_starts(self) -> None:
        self.assertFalse(
            startable(self._wp("Proposed", "agent-implementer"), "implementer")
        )
        self.assertTrue(
            startable(self._wp("Approved", "agent-implementer"), "implementer")
        )
        self.assertFalse(
            startable(self._wp("Approved", "agent-designer"), "implementer")
        )
        self.assertFalse(startable({}, "implementer"))


if __name__ == "__main__":
    unittest.main()
