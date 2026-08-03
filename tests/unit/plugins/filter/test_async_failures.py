import unittest

from plugins.filter.async_failures import async_failures


class TestAsyncFailures(unittest.TestCase):
    def test_finished_command_and_module_are_no_failure(self):
        self.assertEqual([], async_failures([{"finished": 1, "rc": 0}], []))
        self.assertEqual([], async_failures([{"finished": 1, "changed": True}], []))

    def test_non_zero_rc_is_a_failure(self):
        self.assertEqual(
            ["j1: boom"],
            async_failures(
                [{"finished": 1, "rc": 7, "stderr": "boom", "ansible_job_id": "j1"}], []
            ),
        )

    def test_module_failure_is_reported_with_its_msg(self):
        self.assertEqual(
            ["j2: invalid token"],
            async_failures(
                [
                    {
                        "finished": 1,
                        "failed": True,
                        "msg": "invalid token",
                        "ansible_job_id": "j2",
                    }
                ],
                [],
            ),
        )

    def test_unfinished_job_is_a_failure(self):
        self.assertEqual(
            ["j3: job did not finish"],
            async_failures([{"finished": 0, "ansible_job_id": "j3"}], []),
        )

    def test_tolerated_module_msg_is_skipped(self):
        result = {
            "finished": 1,
            "failed": True,
            "msg": "An identical record already exists",
        }
        self.assertEqual(
            [], async_failures([result], ["An identical record already exists"])
        )

    def test_tolerated_phrase_is_found_in_stdout_not_only_msg(self):
        """A command puts its no-op wording in stdout while msg stays generic."""
        result = {
            "finished": 1,
            "rc": 3,
            "msg": "non-zero return code",
            "stdout": "up to date",
        }
        self.assertEqual([], async_failures([result], ["up to date"]))
        self.assertEqual(1, len(async_failures([result], [])))

    def test_reports_every_broken_job_not_just_the_first(self):
        results = [
            {"finished": 1, "rc": 0},
            {"finished": 1, "rc": 1, "stderr": "first", "item": {"item": "llama3"}},
            {
                "finished": 1,
                "failed": True,
                "msg": "second",
                "item": {"item": {"key": "mistral"}},
            },
            {"finished": 0, "ansible_job_id": "j9"},
        ]
        self.assertEqual(
            ["llama3: first", "mistral: second", "j9: job did not finish"],
            async_failures(results, []),
        )

    def test_a_renamed_loop_var_is_still_named_in_the_report(self):
        """loop_control.loop_var moves the loop value off the `item` key."""
        renamed = {
            "finished": 1,
            "rc": 1,
            "stderr": "pull failed",
            "ansible_job_id": "j5",
            "item": {
                "ansible_loop_var": "model",
                "model": "smollm2:135m",
            },
        }
        self.assertEqual(["smollm2:135m: pull failed"], async_failures([renamed], []))

    def test_unreadable_job_is_a_failure_not_a_silent_pass(self):
        """async_status on a job started elsewhere returns finished:true with no outcome.

        Ansible marks the suppressed error; without that check the reaper would
        report every job green whenever it cannot reach them at all.
        """
        phantom = {
            "finished": True,
            "changed": False,
            "failed_when_result": False,
            "failed_when_suppressed_exception": "(traceback unavailable)",
            "ansible_job_id": "j4",
        }
        self.assertEqual(
            ["j4: async job result unavailable (was it started on another host?)"],
            async_failures([phantom], []),
        )

    def test_a_tolerated_phrase_never_hides_an_unreadable_job(self):
        phantom = {"finished": True, "failed_when_suppressed_exception": "x"}
        self.assertEqual(1, len(async_failures([phantom], ["up to date"])))

    def test_empty_and_malformed_input_is_tolerated(self):
        self.assertEqual([], async_failures([], []))
        self.assertEqual([], async_failures(None, None))
        self.assertEqual([], async_failures(["not a dict"], []))


if __name__ == "__main__":
    unittest.main()
