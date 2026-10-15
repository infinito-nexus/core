from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TASKS = PROJECT_ROOT / "roles/web-app-nextcloud/tasks/addons/onlyoffice.yml"


class TestOnlyofficeCheckDeadline(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = load_yaml_str(read_text(str(TASKS)))

    def test_the_deadline_is_set_before_the_check(self) -> None:
        deadline, check = self.tasks
        self.assertIn("nextcloud_onlyoffice_check_deadline", deadline["set_fact"])
        self.assertIn("lookup('timeout'", deadline["set_fact"]["nextcloud_onlyoffice_check_deadline"])
        self.assertEqual(check["register"], "nextcloud_onlyoffice_check")

    def test_the_retries_stop_at_the_deadline(self) -> None:
        until = self.tasks[1]["until"]
        self.assertIn("nextcloud_onlyoffice_check.rc == 0", until)
        self.assertIn("now(utc=true).timestamp() > nextcloud_onlyoffice_check_deadline", until)


if __name__ == "__main__":
    unittest.main()
