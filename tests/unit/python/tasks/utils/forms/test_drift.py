from __future__ import annotations

import importlib
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

collector = importlib.import_module(
    "tests.unit.python.roles.sys-svc-log-collector.templates.test_collector_alloy"
)
loki = importlib.import_module("tests.unit.python.roles.web-svc-loki.test_loki_rules")

TASKS = PROJECT_ROOT / "tasks/utils/forms/drift.yml"
REPORT = PROJECT_ROOT / "tasks/utils/forms/drift_report.yml"
LOGGING = PROJECT_ROOT / "group_vars/all/22_logging.yml"
COLLECTOR = PROJECT_ROOT / "roles/sys-svc-log-collector/templates/collector.alloy.j2"
APPLICATION = "web-app-demo"
LINE = f"{APPLICATION}: general.relay (services.mail.relay): 'old' -> 'new'"
STREAM = re.compile(r"count_over_time\(\{(?P<matchers>[^}]*)\}")
MATCHER = re.compile(r'(?P<label>\w+)="(?P<value>[^"]*)"')
GROUPING = re.compile(r"^sum by \((?P<labels>[^)]*)\)")


def _tasks(path=TASKS) -> list[dict]:
    return load_yaml_any(str(path), default_if_missing=[])


def _render(expression: str, **variables):
    logging = DataLoader().load_from_file(str(LOGGING), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**logging, **variables})
    return templar.template(_trust_as_template(expression))


def _event_labels() -> dict[str, str]:
    """
    Returns:
        The ``__journal_<field>`` labels Alloy's journal source reads from the
        event the drift report raises.
    """
    stdin = _tasks(REPORT)[1]["ansible.builtin.command"]["stdin"]
    rendered = _render(stdin, item=LINE, application_id=APPLICATION)
    return {
        f"__journal_{field.lower()}": value
        for field, _, value in (line.partition("=") for line in rendered.splitlines())
    }


def _collected(source: str | None = None) -> dict | None:
    """
    Args:
        source: the collector template, the role's own when None.

    Returns:
        The labels the rendered collector pipeline gives the drift event, None
        when a drop rule discards it.
    """
    rules = collector._rules(collector._render(source))
    return collector._relabel(rules, _event_labels())


def _drift_query() -> tuple[dict[str, str], list[str]]:
    """
    Returns:
        The stream matchers and the grouping labels of the rendered Loki drift
        rule.
    """
    expr = loki._rules()[loki.VARS["LOKI_DRIFT_RULE_NAME"]]["expr"]
    matchers = STREAM.search(expr).group("matchers")
    grouping = GROUPING.match(expr).group("labels")
    return (
        {
            match.group("label"): match.group("value")
            for match in MATCHER.finditer(matchers)
        },
        [label.strip() for label in grouping.split(",")],
    )


def _unread(labels: dict | None) -> list[str]:
    """
    Args:
        labels: the labels the collector gives the drift event, None when it
            drops the event.

    Returns:
        Each matcher and grouping label of the Loki drift rule the event lacks.
    """
    matchers, grouping = _drift_query()
    held = labels or {}
    return [
        *(
            f"{label}={value}"
            for label, value in matchers.items()
            if held.get(label) != value
        ),
        *(label for label in grouping if not held.get(label)),
    ]


class TestDriftReport(unittest.TestCase):
    def test_the_lines_come_from_the_drift_lookup(self):
        self.assertEqual(
            _tasks()[0]["ansible.builtin.set_fact"]["forms_drift_lines"],
            "{{ lookup('form_drift', application_id, forms_drift_current) }}",
        )

    def test_the_lines_go_to_the_shared_report(self):
        self.assertEqual(
            _tasks()[1]["ansible.builtin.include_tasks"],
            "{{ lookup('path_absolute', 'tasks/utils/forms/drift_report.yml') }}",
        )

    def test_the_lines_reach_the_deploy_log_only_when_there_are_some(self):
        report = _tasks(REPORT)[0]
        self.assertEqual(
            report["ansible.builtin.debug"]["msg"], "{{ forms_drift_lines }}"
        )
        self.assertEqual(report["when"], "forms_drift_lines | length > 0")

    def test_each_line_raises_one_journal_event(self):
        event = _tasks(REPORT)[1]
        self.assertEqual(event["ansible.builtin.command"]["cmd"], "logger --journald")
        self.assertEqual(event["loop"], "{{ forms_drift_lines }}")
        self.assertIs(event["changed_when"], False)

    def test_the_event_carries_the_line_the_identifier_and_the_application(self):
        stdin = _tasks(REPORT)[1]["ansible.builtin.command"]["stdin"]
        rendered = _render(stdin, item=LINE, application_id=APPLICATION)
        self.assertEqual(
            [
                f"MESSAGE={LINE}",
                "SYSLOG_IDENTIFIER=infinito-forms-drift",
                "PRIORITY=4",
                f"INFINITO_APPLICATION={APPLICATION}",
            ],
            rendered.splitlines(),
        )

    def test_the_collector_gives_the_event_every_label_the_rule_reads(self):
        labels = _collected()
        self.assertNotEqual(_drift_query()[0], {})
        self.assertEqual(_unread(labels), [])
        self.assertEqual(labels["application"], APPLICATION)

    def test_negative_control_a_collector_without_a_label_fails_the_rule(self):
        source = read_text(str(COLLECTOR))
        for label in ("identifier", "application"):
            with self.subTest(label=label):
                renamed = source.replace(
                    f'target_label  = "{label}"', f'target_label  = "{label}_x"'
                )
                self.assertNotEqual(source, renamed)
                self.assertNotEqual(_unread(_collected(renamed)), [])


if __name__ == "__main__":
    unittest.main()
