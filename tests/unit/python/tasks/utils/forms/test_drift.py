"""The shared drift report logs each overwritten managed field and raises its journal event.

``tasks/utils/forms/drift.yml`` turns ``forms_drift_current`` into the lines
of ``lookup('form_drift', ...)``, prints them into the deploy log and writes
one journal entry per line whose ``SYSLOG_IDENTIFIER`` the Loki ruler rule of
``roles/web-svc-loki/templates/rules.yaml.j2`` counts, labelled with the
application the way the log collector labels a container line.
"""

from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

TASKS = PROJECT_ROOT / "tasks/utils/forms/drift.yml"
LOGGING = PROJECT_ROOT / "group_vars/all/22_logging.yml"
RULES = PROJECT_ROOT / "roles/web-svc-loki/templates/rules.yaml.j2"
COLLECTOR = PROJECT_ROOT / "roles/sys-svc-log-collector/templates/collector.alloy.j2"
LINE = "web-app-demo: general.relay (services.mail.relay): 'old' -> 'new'"


def _tasks() -> list[dict]:
    return load_yaml_any(str(TASKS), default_if_missing=[])


def _render(expression: str, **variables):
    logging = DataLoader().load_from_file(str(LOGGING), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**logging, **variables})
    return templar.template(_trust_as_template(expression))


class TestDriftReport(unittest.TestCase):
    def test_the_lines_come_from_the_drift_lookup(self):
        self.assertEqual(
            _tasks()[0]["ansible.builtin.set_fact"]["forms_drift_lines"],
            "{{ lookup('form_drift', application_id, forms_drift_current) }}",
        )

    def test_the_lines_reach_the_deploy_log_only_when_there_are_some(self):
        report = _tasks()[1]
        self.assertEqual(
            report["ansible.builtin.debug"]["msg"], "{{ forms_drift_lines }}"
        )
        self.assertEqual(report["when"], "forms_drift_lines | length > 0")

    def test_each_line_raises_one_journal_event(self):
        event = _tasks()[2]
        self.assertEqual(event["ansible.builtin.command"]["cmd"], "logger --journald")
        self.assertEqual(event["loop"], "{{ forms_drift_lines }}")
        self.assertIs(event["changed_when"], False)

    def test_the_event_carries_the_line_the_identifier_and_the_application(self):
        stdin = _tasks()[2]["ansible.builtin.command"]["stdin"]
        rendered = _render(stdin, item=LINE, application_id="web-app-demo")
        self.assertEqual(
            [
                f"MESSAGE={LINE}",
                "SYSLOG_IDENTIFIER=infinito-forms-drift",
                "PRIORITY=4",
                "INFINITO_APPLICATION=web-app-demo",
            ],
            rendered.splitlines(),
        )

    def test_the_collector_turns_the_fields_into_the_labels_the_rule_reads(self):
        collector = read_text(str(COLLECTOR))
        self.assertIn('source_labels = ["__journal_syslog_identifier"]', collector)
        self.assertIn('target_label  = "identifier"', collector)
        self.assertIn("'__journal_' ~ (DOCKER_LOG_JOURNAL_FIELD | lower)", collector)
        self.assertIn(
            "{identifier={{ FORMS_DRIFT_IDENTIFIER | to_json }}}", read_text(str(RULES))
        )


if __name__ == "__main__":
    unittest.main()
