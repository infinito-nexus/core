import unittest
from unittest import mock

from utils.packages.outcome import aggregate, failure_message


class TestFailureMessage(unittest.TestCase):
    def _msg(self, **result):
        return failure_message({"module": "m", **result})

    def test_msg_wins(self):
        self.assertEqual(self._msg(msg="boom", exception="ex"), "m: boom")

    def test_event_msg_carries_a_crash(self):
        event = mock.Mock(msg="unhandled")
        self.assertEqual(self._msg(exception=mock.Mock(event=event)), "m: unhandled")

    def test_bare_exception_is_used_when_no_event(self):
        self.assertEqual(
            self._msg(exception="(traceback unavailable)"),
            "m: (traceback unavailable)",
        )

    def test_module_stderr_is_the_next_rung(self):
        self.assertEqual(self._msg(module_stderr=" oops "), "m: oops")

    def test_stderr_is_the_last_rung(self):
        self.assertEqual(self._msg(stderr="last"), "m: last")

    def test_a_silent_failure_still_names_the_module(self):
        self.assertIn("m", self._msg())


class TestAggregate(unittest.TestCase):
    def test_all_skipped_reports_skip(self):
        result = aggregate([], ["selinux-python-binding"], "debian")
        self.assertTrue(result["skipped"])
        self.assertFalse(result["changed"])

    def test_changed_is_any_changed(self):
        result = aggregate([{"changed": False}, {"changed": True}], [], "debian")
        self.assertTrue(result["changed"])

    def test_failure_propagates_with_its_module(self):
        result = aggregate(
            [
                {"changed": False},
                {"failed": True, "msg": "boom", "module": "ansible.builtin.package"},
            ],
            [],
            "debian",
        )
        self.assertTrue(result["failed"])
        self.assertIn("boom", result["msg"])
        self.assertIn("ansible.builtin.package", result["msg"])

    def test_partial_skips_are_reported(self):
        result = aggregate([{"changed": True}], ["libntirpc"], "debian")
        self.assertEqual(result["skipped_ids"], ["libntirpc"])


if __name__ == "__main__":
    unittest.main()
