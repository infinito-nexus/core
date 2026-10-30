"""Negative controls for the journald logging-driver lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.jinja import test_compose_logging_driver as lint

JOURNALD_BLOCK = """  app:
    logging:
      driver: journald
      options:
        tag: "web-app-fixture"
"""

JSON_FILE_BLOCK = """  app:
    logging:
      driver: json-file
      options:
        max-size: 10m
"""


class TestComposeLoggingDriverFixtures(unittest.TestCase):
    def test_a_journald_block_passes(self) -> None:
        self.assertEqual([], lint.findings_in(JOURNALD_BLOCK))

    def test_a_json_file_block_fails(self) -> None:
        self.assertEqual([(3, "json-file")], lint.findings_in(JSON_FILE_BLOCK))

    def test_a_flow_style_block_fails(self) -> None:
        text = "    logging: {driver: local, options: {max-size: 10m}}\n"
        self.assertEqual([(1, "local")], lint.findings_in(text))

    def test_a_quoted_daemon_setting_fails(self) -> None:
        text = '{\n  "log-driver": "json-file",\n  "log-opts": {}\n}\n'
        self.assertEqual([(2, "json-file")], lint.findings_in(text))

    def test_a_yaml_daemon_setting_fails(self) -> None:
        text = "MATRIX_MDAD_DAEMON_JSON:\n  log-driver: json-file\n"
        self.assertEqual([(2, "json-file")], lint.findings_in(text))

    def test_a_journald_daemon_setting_passes(self) -> None:
        text = '{\n  "log-driver": "journald"\n}\n'
        self.assertEqual([], lint.findings_in(text))

    def test_a_cli_flag_fails(self) -> None:
        text = "docker_args:\n  - --log-driver=syslog\n"
        self.assertEqual([(2, "syslog")], lint.findings_in(text))

    def test_a_spaced_cli_flag_fails(self) -> None:
        text = "exec docker run --log-driver none busybox\n"
        self.assertEqual([(1, "none")], lint.findings_in(text))

    def test_a_jinja_rendered_driver_fails(self) -> None:
        text = "    logging:\n      driver: {{ LOG_DRIVER }}\n"
        self.assertEqual([(2, "{{ LOG_DRIVER }}")], lint.findings_in(text))

    def test_a_block_ends_at_the_next_sibling_key(self) -> None:
        text = (
            "    logging:\n      driver: journald\n    volumes:\n      driver: local\n"
        )
        self.assertEqual([], lint.findings_in(text))

    def test_a_reasoned_marker_on_the_driver_line_suppresses(self) -> None:
        text = JSON_FILE_BLOCK.replace(
            "driver: json-file",
            f"driver: json-file  # nocheck: {lint.RULE}  upstream launcher rotates its own files",
        )
        self.assertEqual([], lint.findings_in(text))

    def test_a_reasoned_marker_above_the_logging_key_suppresses(self) -> None:
        text = JSON_FILE_BLOCK.replace(
            "    logging:",
            f"    # nocheck: {lint.RULE}  vendor support requires json-file\n    logging:",
        )
        self.assertEqual([], lint.findings_in(text))

    def test_a_reasoned_jinja_marker_suppresses(self) -> None:
        text = (
            f"{{# nocheck: {lint.RULE}  the vendor agent reads its own files #}}\n"
            '  "log-driver": "local"\n'
        )
        self.assertEqual([], lint.findings_in(text))

    def test_a_bare_marker_grants_nothing(self) -> None:
        text = JSON_FILE_BLOCK.replace(
            "driver: json-file", f"driver: json-file  # nocheck: {lint.RULE}"
        )
        self.assertEqual([(3, "json-file")], lint.findings_in(text))

    def test_a_marker_for_another_rule_grants_nothing(self) -> None:
        text = JSON_FILE_BLOCK.replace(
            "driver: json-file", "driver: json-file  # nocheck: url  some reason"
        )
        self.assertEqual([(3, "json-file")], lint.findings_in(text))

    def test_the_container_cli_flag_list_is_not_a_driver(self) -> None:
        text = 'FLAGS = {\n    "--log-driver",\n    "--log-opt",\n}\n'
        self.assertEqual([], lint.findings_in(text))


if __name__ == "__main__":
    unittest.main()
