"""Negative controls for the logging-contract rule of the compose structure lint."""

from __future__ import annotations

import unittest

from tests.lint.ansible.jinja import test_compose_template_structure as lint

HEADER = "{% include 'roles/sys-svc-compose/templates/base.yml.j2' %}\n"
FOOTER = "\n{{ lookup('compose_volumes') }}\n"
LOGGING_LOOKUP = (
    "    {{ lookup('template', 'roles/sys-svc-container/templates/logging.yml.j2')"
    " | indent(4) }}\n"
)


def _template(body: str) -> list[str]:
    return (
        HEADER
        + "  {% set service_name = 'app' %}\n  {{ service_name }}:\n"
        + body
        + FOOTER
    ).splitlines()


def _log_tag_findings(body: str) -> list[int]:
    return [
        line
        for line, message in lint.find_structure_violations(_template(body))
        if "application log tag" in message
    ]


class TestComposeLoggingContract(unittest.TestCase):
    def test_the_container_base_carries_the_log_tag(self) -> None:
        body = "    {% include 'roles/sys-svc-container/templates/base.yml.j2' %}\n"
        self.assertEqual([], _log_tag_findings(body))

    def test_the_logging_template_carries_the_log_tag(self) -> None:
        body = "    {{ lookup('compose_restart') }}\n" + LOGGING_LOOKUP
        self.assertEqual([], _log_tag_findings(body))

    def test_a_bare_journald_block_misses_the_log_tag(self) -> None:
        body = (
            "    {{ lookup('compose_restart') }}\n"
            "    logging:\n"
            "      driver: journald\n"
        )
        self.assertEqual([3], _log_tag_findings(body))

    def test_a_body_without_any_logging_misses_the_log_tag(self) -> None:
        self.assertEqual(
            [3], _log_tag_findings("    {{ lookup('compose_restart') }}\n")
        )

    def test_the_rule_reports_each_service_on_its_own_key(self) -> None:
        lines = (
            HEADER
            + "  {% set service_name = 'tagged' %}\n  {{ service_name }}:\n"
            + "    {{ lookup('compose_restart') }}\n"
            + LOGGING_LOOKUP
            + "\n  {% set service_name = 'untagged' %}\n  {{ service_name }}:\n"
            + "    {{ lookup('compose_restart') }}\n"
            + FOOTER
        ).splitlines()
        self.assertEqual(
            [8],
            [
                line
                for line, message in lint.find_structure_violations(lines)
                if "application log tag" in message
            ],
        )


if __name__ == "__main__":
    unittest.main()
