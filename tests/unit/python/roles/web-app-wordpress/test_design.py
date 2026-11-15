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


class TestDesignEnforced(unittest.TestCase):
    WRITER = ROLE / "files/php/design.php"

    def _between(self, start: str, end: str) -> str:
        source = read_text(str(self.WRITER))
        return source[source.index(start) : source.index(end)]

    def test_every_run_writes_the_configured_logos(self):
        loop = self._between(
            "foreach (array_unique(array_merge(array_keys($applied['logos'])",
            "$kept = ",
        )
        self.assertNotIn("continue;", loop)
        self.assertIn(
            "} elseif ($present !== 0 && ($present === $ours"
            " || get_post($present) === null)) {",
            loop,
        )

    def test_every_run_writes_the_configured_global_styles(self):
        loop = self._between(
            "foreach (array_unique(array_merge(array_keys($applied['global_styles'])",
            "wp_clean_theme_json_cache();",
        )
        self.assertIn("if ($wanted === null && !$untouched) {", loop)
        self.assertNotIn("if (!$untouched) {", loop)

    def test_the_writer_marks_itself_before_it_reads_its_configuration(self):
        source = read_text(str(self.WRITER))
        self.assertLess(
            source.index("const NEXUS_DESIGN_WRITER = true;"),
            source.index("$config = json_decode("),
        )


class TestDesignGuard(unittest.TestCase):
    GUARD = ROLE / "files/mu-plugins/infinito-design.php"

    def _guard(self) -> str:
        source = read_text(str(self.GUARD))
        return source[source.index("if (!is_array($design)) {") :]

    def test_the_logos_the_deploy_wrote_stay_for_every_other_writer(self):
        self.assertIn(
            "    foreach ($design['logos'] as $option => $id) {\n"
            "        add_filter('pre_update_option_' . $option,"
            " static function ($value) use ($id) {\n"
            "            return defined('NEXUS_DESIGN_WRITER') ? $value : $id;\n"
            "        }, PHP_INT_MAX);\n"
            "    }\n",
            self._guard(),
        )

    def test_the_global_styles_the_deploy_wrote_stay_for_every_other_writer(self):
        guard = self._guard()
        styles = guard[guard.index("add_filter('wp_insert_post_data',") :]
        self.assertIn(
            "if (defined('NEXUS_DESIGN_WRITER')"
            " || $data['post_type'] !== 'wp_global_styles') {",
            styles,
        )
        self.assertIn(
            "if ($data['post_name'] === 'wp-global-styles-'"
            " . urlencode((string) $theme)) {\n"
            "                $data['post_content'] = wp_slash(wp_json_encode($styles));",
            styles,
        )
        self.assertIn("        return $data;\n    }, PHP_INT_MAX);\n})();", styles)


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
