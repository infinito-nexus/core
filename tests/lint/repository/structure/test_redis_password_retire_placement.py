"""A rotated Redis password is carried across the restart and retired before the checks.

A changed ``REDIS_PASSWORD`` restarts the central engine, while the shared
consumers deployed later in the pass still hold the old password. The engine
therefore keeps accepting the replaced password from its restart until every
server role has redeployed, drops it before the end-to-end tests, and fails the
pass on every client it refuses afterwards. Every edge of that window is silent
when crossed: read after the restart, nothing is left to carry and the
consumers crash-loop again; retired before the app pass ends, the same; retired
after the tests, or in the destructor that ``any_errors_fatal`` skips, a stale
consumer passes; retired without disconnecting the clients, a connection the old
password opened stays usable; verified before the retire, there is nothing to
refuse yet.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: redis-password-retire-placement`` on, or directly above, the
  retire include in the server stage.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "redis-password-retire-placement"
_ROLE_DIR = PROJECT_ROOT / "roles" / "svc-db-redis" / "tasks"
_CORE = _ROLE_DIR / "00_core.yml"
_RETIRE = _ROLE_DIR / "utils" / "rotation" / "retire.yml"
_STAGE = PROJECT_ROOT / "tasks" / "stages" / "02_server.yml"
_DESTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml"
_RETIRE_REF = "utils/rotation/retire.yml"
_VERIFY_REF = "utils/rotation/verify.yml"
_APP_PASS = "tasks/utils/setup/group.yml"
_E2E = "test-e2e-playwright"


def _line_of(lines: list[str], needle: str) -> int | None:
    return next((i for i, raw in enumerate(lines, 1) if needle in raw), None)


class TestRedisPasswordRetirePlacement(unittest.TestCase):
    def test_the_accepted_passwords_are_read_before_the_restart(self) -> None:
        lines = read_text(str(_CORE)).splitlines()
        read = _line_of(lines, "ACL LIST")
        restart = _line_of(lines, "network/routine.yml")
        self.assertIsNotNone(read, f"{_CORE.name} no longer reads the passwords")
        self.assertIsNotNone(restart, f"{_CORE.name} no longer deploys the stack")
        self.assertLess(
            read,
            restart,
            "after the restart the engine accepts only the new password, so "
            "nothing is left to carry",
        )

    def test_the_replaced_passwords_are_added_back_once_the_engine_answers(
        self,
    ) -> None:
        lines = read_text(str(_CORE)).splitlines()
        ping = _line_of(lines, "REDIS_CLI }} ping")
        carry = _line_of(lines, "ACL SETUSER default")
        self.assertIsNotNone(ping, f"{_CORE.name} no longer waits for the engine")
        self.assertIsNotNone(carry, f"{_CORE.name} no longer carries the passwords")
        self.assertLess(
            ping,
            carry,
            "the carry has to reach the restarted engine, not the one it replaces",
        )

    def test_the_retire_sits_between_the_app_pass_and_the_tests(self) -> None:
        lines = read_text(str(_STAGE)).splitlines()
        retire = _line_of(lines, _RETIRE_REF)
        self.assertIsNotNone(
            retire,
            f"{_STAGE.name} never retires a replaced Redis password, so a stale "
            "consumer passes every check",
        )
        if is_suppressed_at(lines, retire, _RULE):
            return
        app_pass = _line_of(lines, _APP_PASS)
        e2e = _line_of(lines, _E2E)
        verify = _line_of(lines, _VERIFY_REF)
        self.assertIsNotNone(app_pass, f"{_STAGE.name} no longer includes the app pass")
        self.assertIsNotNone(e2e, f"{_STAGE.name} no longer runs {_E2E}")
        self.assertIsNotNone(
            verify, f"{_STAGE.name} never fails on a client the retire refused"
        )
        self.assertLess(
            app_pass,
            retire,
            "retired before the app pass ends, the consumers still on the old "
            "password crash-loop until their own redeploy",
        )
        self.assertLess(
            retire,
            e2e,
            f"{_E2E} has to meet a stale consumer, so the replaced password must "
            "be gone before it runs",
        )
        self.assertLess(
            e2e,
            verify,
            "the refused-authentication log is read last, so every client had the "
            "whole test run to authenticate again",
        )

    def test_the_verify_after_the_tests_keeps_the_cluster_mode(self) -> None:
        tasks = load_yaml_any(_STAGE)
        verify = next(
            (
                task
                for task in tasks
                if (task.get("ansible.builtin.include_role") or {}).get("tasks_from")
                == _VERIFY_REF
            ),
            None,
        )
        self.assertIsNotNone(verify, f"{_STAGE.name} no longer includes the verify")
        self.assertEqual(
            (verify.get("vars") or {}).get("compose_mode_force"),
            "",
            f"{_E2E} include_vars every tested app's vars/main.yml for the rest of "
            "the play, and web-app-matrix's compose_mode_force then makes "
            "container_address return the compose name, so the log read finds no "
            "container on a swarm host",
        )

    def test_nothing_of_the_rotation_is_deferred_to_the_destructor(self) -> None:
        destructor = read_text(str(_DESTRUCTOR))
        for ref in (_RETIRE_REF, _VERIFY_REF):
            self.assertNotIn(
                ref,
                destructor,
                "the destructor runs after the end-to-end tests, and "
                "any_errors_fatal skips it entirely once one of them is red",
            )

    def test_the_retire_makes_every_client_authenticate_again(self) -> None:
        lines = read_text(str(_RETIRE)).splitlines()
        reset = _line_of(lines, "resetpass")
        log_reset = _line_of(lines, "ACL LOG RESET")
        kill = _line_of(lines, "CLIENT KILL USER default")
        self.assertIsNotNone(reset, f"{_RETIRE.name} no longer drops the passwords")
        self.assertIsNotNone(
            kill, "removing a password leaves the connections it opened usable"
        )
        self.assertIsNotNone(log_reset, f"{_RETIRE.name} no longer resets the log")
        self.assertLess(
            log_reset,
            kill,
            "the log has to be empty before the kill, or it either keeps the "
            "refusals from before the carry or misses the stale reconnects",
        )


if __name__ == "__main__":
    unittest.main()
