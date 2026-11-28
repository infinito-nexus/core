from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
WRITES = re.compile(
    r"\b(update_option|delete_option|wp_insert_post|wp_update_post"
    r"|wp_delete_attachment|update_user_meta|delete_user_meta)\("
)


def _render(expression: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


class TestDesignDrift(unittest.TestCase):
    TASKS = ROLE / "tasks/09_design.yml"
    STAGE = ROLE / "tasks/09_design/stage.yml"
    READER = ROLE / "files/php/design_drift.php"

    def _tasks(self, path=None) -> list[dict]:
        return load_yaml_any(str(path or self.TASKS), default_if_missing=[])

    def test_the_drift_is_read_and_reported_before_anything_is_written(self):
        stage = self._tasks()[0]
        self.assertEqual("09_design/stage.yml", stage["ansible.builtin.include_tasks"])
        self.assertEqual("WORDPRESS_DESIGN_ENABLED | bool", stage["when"])
        read, collect, hand_over = self._tasks(self.STAGE)[:3]
        self.assertEqual(
            "{{ lookup('file', 'php/design_drift.php') }}",
            read["ansible.builtin.shell"]["stdin"],
        )
        self.assertIs(False, read["changed_when"])
        self.assertIn("forms_drift_lines", collect["ansible.builtin.set_fact"])
        self.assertEqual(
            "{{ lookup('path_absolute', 'tasks/utils/forms/drift_report.yml') }}",
            hand_over["ansible.builtin.include_tasks"],
        )

    def test_the_drift_read_takes_the_configuration_the_write_applies(self):
        write = next(t for t in self._tasks() if "Apply or withdraw" in t["name"])
        self.assertEqual(
            write["ansible.builtin.shell"]["cmd"],
            self._tasks(self.STAGE)[0]["ansible.builtin.shell"]["cmd"],
        )

    def test_each_overwritten_part_becomes_one_drift_line(self):
        expression = self._tasks(self.STAGE)[1]["ansible.builtin.set_fact"][
            "forms_drift_lines"
        ]
        held = ["site_icon", "global_styles.twentytwentyfive"]
        self.assertEqual(
            [
                "web-app-wordpress: design.site_icon: changed",
                "web-app-wordpress: design.global_styles.twentytwentyfive: changed",
            ],
            _render(
                expression,
                application_id="web-app-wordpress",
                wordpress_design_held={"stdout_lines": ["Notice", json.dumps(held)]},
            ),
        )
        self.assertEqual(
            [],
            _render(
                expression,
                application_id="web-app-wordpress",
                wordpress_design_held={"stdout_lines": ["[]"]},
            ),
        )

    def test_the_drift_read_writes_nothing(self):
        self.assertIsNone(WRITES.search(read_text(str(self.READER))))


if __name__ == "__main__":
    unittest.main()
