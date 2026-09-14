"""Lint check: the task profiler must not truncate its summary to the default.

``ansible.cfg`` enables ``profile_tasks``, whose ``output_limit`` defaults to
20. A deploy round of this size then reports only the twenty slowest tasks and
prints nothing below them, so any role whose cost is spread over many cheap
tasks cannot be attributed at all: in run 33828309745 the recap cut off at
66.07s, leaving 22.7 of ``sys-svc-compose``'s 51.9 minutes unaccounted.

The limit stays bounded rather than ``all`` because the recap prints one line
per task execution and the Actions worker dies silently on ENOSPC while writing
its own logs, which is the same reason ``utils/tests/swarm/matrix.py`` aborts a
step at ``DISK_FLOOR_MB``.
"""

from __future__ import annotations

import configparser
import unittest

from utils import PROJECT_ROOT

CONFIG = PROJECT_ROOT / "ansible.cfg"
SECTION = "callback_profile_tasks"
KEY = "task_output_limit"
DEFAULT_LIMIT = 20


class TestProfileTasksOutputLimit(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = configparser.ConfigParser()
        self.parser.read(CONFIG)

    def test_the_profiler_is_enabled(self) -> None:
        enabled = self.parser.get("defaults", "callbacks_enabled", fallback="")
        self.assertIn("profile_tasks", enabled)

    def test_the_summary_is_not_left_at_the_default_limit(self) -> None:
        self.assertTrue(
            self.parser.has_option(SECTION, KEY),
            f"ansible.cfg must set [{SECTION}] {KEY}; without it the recap "
            f"stops after {DEFAULT_LIMIT} tasks and the cost of a role spread "
            "over many cheap tasks cannot be attributed",
        )
        value = self.parser.get(SECTION, KEY).strip()
        if value == "all":
            return
        self.assertGreater(int(value), DEFAULT_LIMIT)


if __name__ == "__main__":
    unittest.main()
