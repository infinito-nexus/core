"""Unit test: the failure signature is stable across the volatile parts of two
runs of one failure and across the earlier tasks of real-format Ansible output,
differs between failures even behind one Ansible retry line and between tasks
with one cause, never keeps the raw line, a hung run signs the task it hangs in,
and the stop rule fires only on the same signature twice in a row, two
text-less reds included."""

from __future__ import annotations

import unittest

from agents.routines.tools.signature import (
    failure_signature,
    hung_signature,
    playwright_failures,
    repeated,
)
from tests.unit.python.agents.routines import tools as ansible

_FIRST = (
    "2026-11-06T01:02:03.123Z TASK [web-app-gitea : Wait for the port]\n"
    'fatal: [localhost]: FAILED! => {"msg": "container 3f2a9c81d0e4b7a6 not healthy after 30s"}\n'
)
_SECOND = (
    "2026-11-06T02:14:59.987Z TASK [web-app-gitea : Wait for the port]\n"
    'fatal: [localhost]: FAILED! => {"msg": "container 9b1e77c02f3da5e8 not healthy after 31.5s"}\n'
)
_OTHER = (
    'fatal: [localhost]: FAILED! => {"msg": "role web-app-gitea: template missing"}\n'
)
_JUNIT = (
    '<testsuite><testcase name="admin signs in">'
    '<failure message="expected 200, got 500">trace</failure>'
    "</testcase></testsuite>"
)
_RETRY_HEAD = (
    "TASK [sys-svc-docker : Wait] ****\n"
    "FAILED - RETRYING: [localhost]: Wait for docker daemon (60 retries left).\n"
    "ok: [localhost]\n"
)
_COMMAND = (
    'fatal: [localhost]: FAILED! => {{"changed": true, "cmd": "x", '
    '"delta": "0:00:0{d}.{f}", "rc": 1, "start": "2026-11-06 00:41:12.{f}"}}'
)
_TMP_PATH = (
    'fatal: [localhost]: FAILED! => {{"msg": "/root/.ansible/tmp/'
    'ansible-tmp-{n}-1234-98765/x.py failed"}}'
)
_UUID = 'fatal: [localhost]: FAILED! => {{"msg": "request {u} failed"}}'


class TestFailureSignature(unittest.TestCase):
    def test_two_fatals_behind_one_retry_line_differ(self) -> None:
        one = _RETRY_HEAD + 'fatal: [localhost]: FAILED! => {"msg": "template error"}\n'
        two = _RETRY_HEAD + 'fatal: [localhost]: FAILED! => {"msg": "port 3000"}\n'
        self.assertNotEqual(failure_signature(one, ""), failure_signature(two, ""))

    def test_a_retry_line_alone_is_no_failure_to_sign(self) -> None:
        self.assertEqual(
            failure_signature(_RETRY_HEAD, ""), failure_signature("ok: [localhost]", "")
        )

    def test_ansible_command_deltas_are_masked(self) -> None:
        self.assertEqual(
            failure_signature(_COMMAND.format(d=1, f="234567"), ""),
            failure_signature(_COMMAND.format(d=2, f="345678"), ""),
        )

    def test_ansible_temp_paths_are_masked(self) -> None:
        self.assertEqual(
            failure_signature(_TMP_PATH.format(n="1730812345.67"), ""),
            failure_signature(_TMP_PATH.format(n="1730899999.12"), ""),
        )

    def test_uuids_are_masked(self) -> None:
        self.assertEqual(
            failure_signature(
                _UUID.format(u="550e8400-e29b-41d4-a716-446655440000"), ""
            ),
            failure_signature(
                _UUID.format(u="6ba7b810-9dad-11d1-80b4-00c04fd430c8"), ""
            ),
        )

    def test_every_failing_junit_case_is_signed(self) -> None:
        second = _JUNIT.replace(
            "</testsuite>",
            '<testcase name="logout"><failure message="z"/></testcase></testsuite>',
        )
        self.assertNotEqual(
            failure_signature("", _JUNIT), failure_signature("", second)
        )

    def test_volatile_parts_do_not_change_the_signature(self) -> None:
        self.assertEqual(failure_signature(_FIRST, ""), failure_signature(_SECOND, ""))

    def test_a_different_failure_has_a_different_signature(self) -> None:
        self.assertNotEqual(
            failure_signature(_FIRST, ""), failure_signature(_OTHER, "")
        )

    def test_the_signature_is_a_digest_not_the_line(self) -> None:
        signature = failure_signature(_FIRST, "")
        self.assertRegex(signature, r"^[0-9a-f]{16}$")
        self.assertNotIn("container", signature)

    def test_a_junit_failure_wins_over_the_log(self) -> None:
        self.assertEqual(
            failure_signature(_FIRST, _JUNIT), failure_signature(_OTHER, _JUNIT)
        )

    def test_a_hung_run_signs_its_last_line(self) -> None:
        hung = "TASK [web-app-gitea : Pull images]\nPulling layer 4 of 9\n"
        self.assertEqual(
            failure_signature(hung, ""), failure_signature("Pulling layer 4 of 9", "")
        )

    def test_an_empty_run_has_no_signature(self) -> None:
        self.assertEqual(failure_signature("\n \n", ""), "")


_CAUSE = "Unable to start service hlth-runtime"


class TestRealFormat(unittest.TestCase):
    def test_the_same_failure_after_different_earlier_tasks_repeats(self) -> None:
        self.assertEqual(
            failure_signature(ansible.red_run(ansible.CHANGED, _CAUSE, 1, 2), ""),
            failure_signature(ansible.red_run(ansible.CHANGED, _CAUSE, 3, 7), ""),
        )

    def test_the_same_cause_in_another_task_differs(self) -> None:
        self.assertNotEqual(
            failure_signature(ansible.red_run(ansible.CHANGED, _CAUSE, 1, 2), ""),
            failure_signature(ansible.red_run(ansible.EARLIER, _CAUSE, 1, 2), ""),
        )

    def test_another_cause_in_the_same_task_differs(self) -> None:
        self.assertNotEqual(
            failure_signature(ansible.red_run(ansible.CHANGED, _CAUSE, 1, 2), ""),
            failure_signature(
                ansible.red_run(ansible.CHANGED, "port closed", 1, 2), ""
            ),
        )

    def test_an_ignored_failure_before_does_not_change_it(self) -> None:
        tail = ansible.banner(ansible.CHANGED, 30) + ansible.failure(_CAUSE, 1)
        ignored = ansible.ignored("svc-db-postgres : Probe", "socket missing")
        self.assertEqual(
            failure_signature(ignored + tail, ""), failure_signature(tail, "")
        )

    def test_a_rescued_fatal_never_enters_the_signature(self) -> None:
        def rescued_run(cause: str) -> str:
            return (
                ansible.rescued("svc-db-postgres : Migrate", cause)
                + ansible.banner(ansible.CHANGED, 30)
                + ansible.rescued_recap()
                + ansible.exit_line()
            )

        self.assertEqual(
            failure_signature(rescued_run("lock held"), ""),
            failure_signature(rescued_run("disk full"), ""),
        )

    def test_a_fatal_before_always_tasks_is_signed(self) -> None:
        self.assertNotEqual(
            failure_signature(ansible.always_run("duplicate client"), ""),
            failure_signature(ansible.always_run("HTTP 401 from the admin API"), ""),
        )

    def test_specs_inside_an_escaped_deploy_msg_are_signed(self) -> None:
        self.assertNotEqual(
            failure_signature(ansible.deploy_playwright("login works"), ""),
            failure_signature(ansible.deploy_playwright("logout works"), ""),
        )
        self.assertEqual(
            playwright_failures(ansible.deploy_playwright("login works")),
            ["playwright.spec.js › login works"],
        )

    def test_a_flaky_neighbour_does_not_change_the_signature(self) -> None:
        failing = (
            "  ✘  2 [chromium] › a.spec.js:50:1 › login works (3.0s)\n"
            "  ✘  3 [chromium] › a.spec.js:50:1 › login works (retry #1) (3.1s)\n"
        )
        flaky = (
            "  ✘  1 [chromium] › a.spec.js:10:1 › setup (1.0s)\n"
            "  ✓  2 [chromium] › a.spec.js:10:1 › setup (retry #1) (1.2s)\n"
        )
        self.assertEqual(
            failure_signature(flaky + failing, ""), failure_signature(failing, "")
        )

    def test_hosts_ports_and_temp_names_are_masked(self) -> None:
        def cause(ip: str, port: int, onion: str, tmp: str, epoch: int) -> str:
            text = (
                f"waiting for {ip}:{port} via {onion}.onion, socket {tmp}, at {epoch}"
            )
            return (
                ansible.banner(ansible.CHANGED, 9)
                + ansible.failure(text, 1)
                + ansible.recap()
            )

        first = cause("172.18.0.5", 41234, "a" * 56, "/tmp/tmpa1b2c3d4", 1730812345)
        second = cause("172.19.0.7", 38211, "q" * 56, "/tmp/tmpzz9y8x7w", 1730899999)
        self.assertEqual(failure_signature(first, ""), failure_signature(second, ""))

    def test_the_act_prefix_does_not_change_the_signature(self) -> None:
        run = ansible.red_run(ansible.CHANGED, _CAUSE, 1, 2)
        self.assertEqual(
            failure_signature(ansible.act(run), ""), failure_signature(run, "")
        )

    def test_the_real_fatal_after_a_rescued_one_is_signed(self) -> None:
        tail = (
            ansible.banner(ansible.CHANGED, 30)
            + ansible.failure(_CAUSE, 1)
            + ansible.recap()
            + ansible.exit_line()
        )
        self.assertEqual(
            failure_signature(
                ansible.rescued("svc-db-postgres : Migrate", "a") + tail, ""
            ),
            failure_signature(tail, ""),
        )

    def test_failed_playwright_cases_stay_in_the_signature(self) -> None:
        run = ansible.red_run("test-e2e-playwright : Fail on failures", _CAUSE, 1, 0)
        self.assertNotEqual(
            failure_signature("✘  3 tests/a.js:4:1 › login\n" + run, ""),
            failure_signature("✘  4 tests/b.js:9:1 › logout\n" + run, ""),
        )


class TestHungSignature(unittest.TestCase):
    def test_a_hang_in_the_same_task_repeats(self) -> None:
        self.assertEqual(
            hung_signature(ansible.hung_run(ansible.CHANGED, "Pulling layer 4", 2)),
            hung_signature(ansible.hung_run(ansible.CHANGED, "Pulling layer 7", 9)),
        )

    def test_a_hang_in_another_task_differs(self) -> None:
        self.assertNotEqual(
            hung_signature(ansible.hung_run(ansible.CHANGED, "x", 2)),
            hung_signature(ansible.hung_run(ansible.EARLIER, "x", 2)),
        )

    def test_a_log_without_a_banner_signs_its_last_line(self) -> None:
        self.assertEqual(hung_signature("a\nb\n"), hung_signature("b"))
        self.assertEqual(hung_signature(""), "")


class TestRepeated(unittest.TestCase):
    def test_same_signature_twice_in_a_row_repeats(self) -> None:
        self.assertTrue(repeated(["a", "b"], "b"))

    def test_an_older_match_does_not_repeat(self) -> None:
        self.assertFalse(repeated(["b", "a"], "b"))

    def test_the_first_red_does_not_repeat(self) -> None:
        self.assertFalse(repeated([], "b"))

    def test_two_reds_without_failure_text_repeat(self) -> None:
        self.assertTrue(repeated([""], ""))


if __name__ == "__main__":
    unittest.main()
