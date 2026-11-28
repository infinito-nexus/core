from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TASKS = PROJECT_ROOT / "roles/web-app-nextcloud/tasks/addons/onlyoffice.yml"
FUTURE = 4102444800


class TestOnlyofficeCheckDeadline(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = load_yaml_str(read_text(str(TASKS)))

    def _stops(self, rc: int, deadline: int) -> bool:
        """
        Args:
            rc: the exit code of the registered check.
            deadline: the timestamp the deadline fact holds.

        Returns:
            Whether the ``until`` of the check ends the retries.
        """
        templar = Templar(
            loader=DataLoader(),
            variables={
                "nextcloud_onlyoffice_check": {"rc": rc},
                "nextcloud_onlyoffice_check_deadline": deadline,
            },
        )
        until = self.tasks[1]["until"]
        return templar.template(trust_as_template("{{ (" + until + ") | bool }}"))

    def test_the_deadline_is_set_before_the_check(self) -> None:
        deadline, check = self.tasks
        self.assertIn("nextcloud_onlyoffice_check_deadline", deadline["set_fact"])
        self.assertIn(
            "lookup('timeout'",
            deadline["set_fact"]["nextcloud_onlyoffice_check_deadline"],
        )
        self.assertEqual(check["register"], "nextcloud_onlyoffice_check")

    def test_the_retries_stop_at_the_deadline(self) -> None:
        for rc, deadline, stops in (
            (0, FUTURE, True),
            (1, FUTURE, False),
            (1, 0, True),
        ):
            with self.subTest(rc=rc, deadline=deadline):
                self.assertIs(stops, self._stops(rc, deadline))


if __name__ == "__main__":
    unittest.main()
