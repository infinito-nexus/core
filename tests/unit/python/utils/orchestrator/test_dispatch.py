"""Unit test: a trigger starts the roles whose agent.yml lists it, an
outsider's event and a gated role's start go through the planner, a board
work package starts its role only once Approved, and a failed run or a new
pull request notifies the owner over Matrix."""

from __future__ import annotations

import unittest

from plugins.lookup.agent_config import LookupModule
from tests.lint.agents import ROLES_DIR, role_names
from utils.orchestrator.channels import EmailChannel, MatrixChannel, dispatch
from utils.orchestrator.dispatch import board_start, notices, route, routine_of
from utils.orchestrator.webhook import Event

MODULE = LookupModule()
ROLES = role_names(ROLES_DIR)
TRIGGERS = {role: MODULE.run([role, "triggers"], variables={})[0] for role in ROLES}
OWNERS = {role: MODULE.run([role, "owner"], variables={})[0] for role in ROLES}
ENTRIES = [
    {**entry, "role": role}
    for role in ROLES
    for entry in MODULE.run([role, "cron"], variables={})[0]
]
ROUTINES = ["implementer", "legal_audit", "maintainer", "reviewer"]
CORE = "infinito-nexus/core"


def _wp(status: str, assignee: str) -> dict:
    return {
        "id": 7,
        "_links": {"status": {"title": status}, "assignee": {"title": assignee}},
    }


class TestRoute(unittest.TestCase):
    def test_a_failed_run_starts_the_maintainer_routine_ungated(self) -> None:
        roles = route(Event("workflow_run_failed", CORE, False), TRIGGERS)
        self.assertEqual(roles, ["maintainer"])
        self.assertEqual(routine_of("maintainer", ENTRIES, ROUTINES), "maintainer")

    def test_a_security_alert_starts_the_maintainer_ungated(self) -> None:
        self.assertEqual(
            route(Event("security_alert", CORE, False), TRIGGERS), ["maintainer"]
        )

    def test_an_outsiders_issue_and_a_fork_run_start_only_the_planner(self) -> None:
        for trigger in ("issue_opened", "workflow_run_failed"):
            with self.subTest(trigger=trigger):
                self.assertEqual(
                    route(Event(trigger, CORE, True), TRIGGERS), ["planner"]
                )

    def test_a_collaborators_issue_goes_through_the_planner_and_the_gate(
        self,
    ) -> None:
        self.assertEqual(
            route(Event("issue_opened", CORE, False), TRIGGERS), ["planner"]
        )
        self.assertIsNone(routine_of("planner", ENTRIES, ROUTINES))

    def test_a_changed_lockfile_starts_the_counsel_legal_audit(self) -> None:
        event = Event("dependency_manifest_changed", CORE, False, ("uv.lock",))
        self.assertEqual(route(event, TRIGGERS), ["counsel"])
        self.assertEqual(routine_of("counsel", ENTRIES, ROUTINES), "legal_audit")


class TestBoardStart(unittest.TestCase):
    def test_a_proposed_work_package_starts_nothing(self) -> None:
        self.assertIsNone(board_start(_wp("Proposed", "agent-implementer"), TRIGGERS))

    def test_an_approved_assignment_starts_the_implementer_routine(self) -> None:
        role = board_start(_wp("Approved", "agent-implementer"), TRIGGERS)
        self.assertEqual(role, "implementer")
        self.assertEqual(routine_of(role, ENTRIES, ROUTINES), "implementer")

    def test_a_role_without_board_assignment_or_a_human_assignee_starts_nothing(
        self,
    ) -> None:
        self.assertIsNone(board_start(_wp("Approved", "agent-maintainer"), TRIGGERS))
        self.assertIsNone(board_start(_wp("Approved", "biber"), TRIGGERS))


class TestNotices(unittest.TestCase):
    def test_a_failed_run_and_a_new_pull_request_notify_over_matrix(self) -> None:
        channels = [
            MatrixChannel(homeserver="matrix.infinito.example"),
            EmailChannel(
                domain="infinito.example", sender="orch0main@infinito.example"
            ),
        ]
        for trigger in ("workflow_run_failed", "pull_request_opened"):
            with self.subTest(trigger=trigger):
                event = Event(trigger, CORE, False)
                pending = notices(event, route(event, TRIGGERS), OWNERS)
                self.assertEqual([owner for owner, _ in pending], ["operator"])
                request = dispatch(channels, *pending[0])
                self.assertEqual(request["channel"], "matrix")
                self.assertEqual(request["to"], "@operator:matrix.infinito.example")
                self.assertIn(CORE, request["content"]["body"])

    def test_other_triggers_notify_nobody(self) -> None:
        event = Event("security_alert", CORE, False)
        self.assertEqual(notices(event, route(event, TRIGGERS), OWNERS), [])


if __name__ == "__main__":
    unittest.main()
