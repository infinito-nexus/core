from __future__ import annotations

import json
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-svc-loki"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
LOGGING = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/22_logging.yml"))
WINDOW = "5m"


def _rules() -> dict[str, dict]:
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["to_json"] = json.dumps
    rendered = env.get_template("rules.yaml.j2").render(
        LOKI_ALERTING_RULE_NAME=VARS["LOKI_ALERTING_RULE_NAME"],
        LOKI_ALERTING_PATTERN="(?i)critical",
        LOKI_ALERTING_WINDOW=WINDOW,
        LOKI_DRIFT_RULE_NAME=VARS["LOKI_DRIFT_RULE_NAME"],
        FORMS_DRIFT_IDENTIFIER=LOGGING["FORMS_DRIFT_IDENTIFIER"],
    )
    return {
        rule["alert"]: rule
        for group in load_yaml_str(rendered)["groups"]
        for rule in group["rules"]
    }


class TestLokiRules(unittest.TestCase):
    def test_the_critical_line_rule_stays(self):
        self.assertIn(VARS["LOKI_ALERTING_RULE_NAME"], _rules())

    def test_every_drift_event_fires_per_application_and_host(self):
        rule = _rules()[VARS["LOKI_DRIFT_RULE_NAME"]]
        self.assertEqual(
            "sum by (application, host) (count_over_time("
            f'{{identifier="{LOGGING["FORMS_DRIFT_IDENTIFIER"]}"}} [{WINDOW}])) > 0',
            rule["expr"],
        )
        self.assertEqual("0m", rule["for"])
        self.assertEqual(
            {"severity": "warning", "source": "loki-ruler"}, rule["labels"]
        )

    def test_the_summary_keeps_the_alert_labels_for_the_ruler(self):
        summary = _rules()[VARS["LOKI_DRIFT_RULE_NAME"]]["annotations"]["summary"]
        self.assertIn("{{ $labels.application }}", summary)
        self.assertIn("{{ $labels.host }}", summary)


if __name__ == "__main__":
    unittest.main()
