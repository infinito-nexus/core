"""Unit test: the log scanner finds the failing line, tells a run from a skip on
a recorded CI job log, lists the failures a run did not get past, cuts the
failing Ansible task's block out of real-format output, and tells whether a red
run reached the changed code before its last fatal."""

from __future__ import annotations

import unittest

from agents.routines.tools.log_scan import (
    change_ran,
    failing_block,
    failing_line,
    failure_lines,
    last_task,
    last_task_block,
    log_lines,
    mentions,
    reached,
    run_exited,
    run_status,
)
from tests.unit.python.agents.routines import tools as ansible

_JOB_LOG = """Running 3 tests using 1 worker
  ✓  design.spec.js:4:1 › tokens applied (1.2s)
  -  design.spec.js:9:1 › dark mode [skipped]
  ✗  login.spec.js:2:1 › admin signs in
      AssertionError: expected 200, got 500
make: *** [Makefile:9: e2e] Error 2
"""


class TestLogScan(unittest.TestCase):
    def test_failing_line_found(self) -> None:
        line = failing_line(_JOB_LOG)
        self.assertIsNotNone(line)
        self.assertIn("login.spec.js", line)

    def test_failing_line_absent(self) -> None:
        self.assertIsNone(failing_line("  ✓ all good\nok 1 - fine\n"))

    def test_change_ran_true_on_check(self) -> None:
        self.assertIsNotNone(change_ran(_JOB_LOG, "tokens applied"))

    def test_change_ran_none_when_skipped(self) -> None:
        self.assertIsNone(change_ran(_JOB_LOG, "dark mode"))

    def test_change_ran_none_when_absent(self) -> None:
        self.assertIsNone(change_ran(_JOB_LOG, "nonexistent spec"))


_DEPLOY_LOG = """TASK [svc-db-postgres : Start the database] ****
ok: [localhost]
TASK [web-app-gitea : Render app.ini] ****
fatal: [localhost]: FAILED! => {"msg": "template error"}
"""


class TestReached(unittest.TestCase):
    def test_marker_before_the_failure_is_reached(self) -> None:
        self.assertTrue(reached(_DEPLOY_LOG, "TASK [web-app-gitea"))

    def test_failure_before_the_marker_is_not_reached(self) -> None:
        self.assertFalse(reached(_DEPLOY_LOG, "TASK [web-app-mig"))

    def test_marker_on_the_failing_line_is_reached(self) -> None:
        self.assertTrue(reached(_JOB_LOG, "admin signs in"))

    def test_marker_after_the_last_failure_is_not_reached(self) -> None:
        self.assertFalse(reached(_JOB_LOG, "Error 2"))

    def test_a_skipped_marker_is_not_reached(self) -> None:
        self.assertFalse(reached(_JOB_LOG, "dark mode"))

    def test_marker_anywhere_in_a_green_log_is_reached(self) -> None:
        self.assertTrue(
            reached("ok 1\nTASK [web-app-gitea : x]\nok 2\n", "web-app-gitea")
        )

    def test_a_retry_before_the_marker_is_no_failure(self) -> None:
        self.assertTrue(reached(_RETRY + _DEPLOY_LOG, "TASK [web-app-gitea"))

    def test_an_ignored_failure_before_the_marker_is_no_failure(self) -> None:
        self.assertTrue(reached(_IGNORED + _DEPLOY_LOG, "TASK [web-app-gitea"))

    def test_an_earlier_failing_spec_before_the_marker_is_no_verdict(self) -> None:
        log = "  ✘  a.spec.js:1:1 › other\n  ✘  b.spec.js:1:1 › changed test\n"
        self.assertTrue(reached(log, "changed test"))


_RETRY = (
    "TASK [sys-svc-docker : Wait for docker daemon] ****\n"
    "FAILED - RETRYING: [localhost]: Wait for docker daemon (60 retries left).\n"
    "ok: [localhost]\n"
)
_IGNORED = (
    "TASK [sys-svc-docker : Probe] ****\n"
    'fatal: [localhost]: FAILED! => {"msg": "probe"}\n'
    "...ignoring\n"
)


class TestFailureLines(unittest.TestCase):
    def test_retries_and_ignored_failures_are_left_out(self) -> None:
        self.assertEqual(
            failure_lines(_RETRY + _IGNORED + _DEPLOY_LOG),
            ['fatal: [localhost]: FAILED! => {"msg": "template error"}'],
        )

    def test_every_failure_is_kept_in_order(self) -> None:
        self.assertEqual(
            failure_lines(_JOB_LOG),
            [
                "✗  login.spec.js:2:1 › admin signs in",
                "AssertionError: expected 200, got 500",
            ],
        )


_CAUSE = "Unable to start service hlth-runtime"
_RED_RUN = ansible.red_run(ansible.CHANGED, _CAUSE, 2, 3)
_RESCUED_ONLY = (
    ansible.rescued("svc-db-postgres : Migrate", "lock held")
    + ansible.banner(ansible.CHANGED, 30)
    + ansible.rescued_recap()
    + ansible.exit_line()
)


class TestRealFormat(unittest.TestCase):
    def test_the_failing_block_is_banner_cause_and_fatal(self) -> None:
        self.assertEqual(
            failing_block(_RED_RUN),
            [
                f"TASK [{ansible.CHANGED}]",
                f"[ERROR]: Task failed: Module failed: {_CAUSE}",
                "fatal: [localhost]: FAILED! =>",
            ],
        )

    def test_an_ignored_task_with_ansi_and_a_yaml_body_is_left_out(self) -> None:
        log = ansible.ignored("svc-db-postgres : Probe", "socket missing")
        self.assertEqual(failure_lines(log), [])
        self.assertEqual(failing_block(log), [])

    def test_a_hang_inside_the_changed_task_is_reached(self) -> None:
        log = ansible.hung_run(ansible.CHANGED, "Pulling layer 4 of 9", 3)
        self.assertTrue(reached(log, ansible.MARKER))

    def test_an_ignored_cause_before_the_marker_does_not_end_the_reach(self) -> None:
        log = ansible.ignored(
            "svc-db-postgres : Probe", "socket missing"
        ) + ansible.hung_run(ansible.CHANGED, "Pulling layer 4 of 9", 0)
        self.assertTrue(reached(log, ansible.MARKER))

    def test_a_marker_the_run_never_printed_is_not_reached(self) -> None:
        self.assertFalse(reached(_RED_RUN, "TASK [web-app-mig :"))

    def test_a_rescued_fatal_does_not_anchor_the_reach(self) -> None:
        self.assertTrue(reached(_RESCUED_ONLY, ansible.MARKER))

    def test_a_rescued_fatal_is_no_failing_block(self) -> None:
        self.assertEqual(failing_block(_RESCUED_ONLY), [])
        self.assertEqual(
            failure_lines(_RESCUED_ONLY),
            ["[ERROR] ansible-playbook exited with status 2"],
        )

    def test_a_real_fatal_after_a_rescued_one_decides(self) -> None:
        log = (
            ansible.rescued("svc-db-postgres : Migrate", "lock held")
            + ansible.banner(ansible.CHANGED, 30)
            + ansible.failure(_CAUSE, 1)
            + ansible.recap()
            + ansible.exit_line()
        )
        self.assertEqual(
            failing_block(log),
            [
                f"TASK [{ansible.CHANGED}]",
                f"[ERROR]: Task failed: Module failed: {_CAUSE}",
                "fatal: [localhost]: FAILED! =>",
            ],
        )

    def test_mentions_reads_the_whole_log(self) -> None:
        log = "AssertionError: boom\nchanged test started\n"
        self.assertFalse(reached(log, "changed test"))
        self.assertTrue(mentions(log, "changed test"))

    def test_the_end_of_a_run_and_its_status(self) -> None:
        between_plays = (
            ansible.passed(ansible.EARLIER, 1)
            + ansible.rescued_recap()
            + "\nPLAY [Deploy the applications] ****\n"
        )
        cases = {
            "wrapper exit line": (_RED_RUN, "2"),
            "make error line": ("make: *** [Makefile:40: test] Error 2\n", "2"),
            "deploy closing line": (ansible.green_run(), "0"),
            "failed recap": (
                ansible.banner(ansible.CHANGED, 9) + ansible.recap(),
                "failed recap",
            ),
            "act prefix": (ansible.act(_RED_RUN), "2"),
            "recap between plays": (between_plays, None),
            "hung": (ansible.hung_run(ansible.CHANGED, "x", 1), None),
        }
        for name, (log, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(run_status(log), status)
                self.assertEqual(run_exited(log), status is not None)

    def test_a_fatal_before_always_tasks_decides_a_red_run(self) -> None:
        self.assertEqual(
            failing_block(ansible.always_run(_CAUSE)),
            [
                f"TASK [{ansible.CHANGED}]",
                f"[ERROR]: Task failed: Module failed: {_CAUSE}",
                "fatal: [localhost]: FAILED! =>",
            ],
        )
        log = ansible.always_run(_CAUSE) + ansible.banner("web-app-mig : Seed", 9)
        self.assertFalse(reached(log, "TASK [web-app-mig :"))

    def test_the_act_prefix_is_stripped(self) -> None:
        self.assertEqual(failing_block(ansible.act(_RED_RUN)), failing_block(_RED_RUN))
        self.assertEqual(
            failure_lines(ansible.act(_RESCUED_ONLY)), failure_lines(_RESCUED_ONLY)
        )

    def test_fatal_lines_of_several_hosts_are_sorted(self) -> None:
        def nodes(order: tuple[str, str]) -> str:
            return (
                ansible.banner(ansible.CHANGED, 9)
                + "".join(f"fatal: [{node}]: FAILED! =>\n" for node in order)
                + ansible.recap()
            )

        self.assertEqual(
            failing_block(nodes(("wrk-01", "mgr-01"))),
            failing_block(nodes(("mgr-01", "wrk-01"))),
        )

    def test_a_stopped_task_keeps_its_cause(self) -> None:
        log = ansible.banner(ansible.CHANGED, 9) + ansible.failure(_CAUSE, 1)
        self.assertIn(
            f"[ERROR]: Task failed: Module failed: {_CAUSE}", last_task_block(log)
        )

    def test_log_lines_strip_ansi_and_blank_lines(self) -> None:
        self.assertEqual(
            log_lines("\x1b[0;31m  fatal: [localhost]: FAILED! => \x1b[0m\n\n  ok\n"),
            ["fatal: [localhost]: FAILED! =>", "ok"],
        )

    def test_the_last_task_names_where_a_run_hangs(self) -> None:
        log = ansible.hung_run(ansible.CHANGED, "Pulling layer 4 of 9", 1)
        self.assertEqual(last_task(log), f"TASK [{ansible.CHANGED}]")
        self.assertEqual(last_task("no banner"), "")


if __name__ == "__main__":
    unittest.main()
