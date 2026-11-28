from __future__ import annotations

import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.pool_runner import FilterModule
from utils.runner.semaphore import pool_runner_token


class TestPoolRunnerFilters(unittest.TestCase):
    def setUp(self) -> None:
        self.filters = FilterModule().filters()

    def test_the_filter_derives_what_the_semaphore_role_seeds(self) -> None:
        self.assertEqual(
            self.filters["pool_runner_token"]("secret", "runner-2"),
            pool_runner_token("secret", "runner-2"),
        )

    def test_negative_control_an_empty_secret_fails_the_template(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            self.filters["pool_runner_token"]("", "runner-1")


if __name__ == "__main__":
    unittest.main()
