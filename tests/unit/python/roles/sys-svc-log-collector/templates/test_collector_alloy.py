"""Pin the self-exclusion of the collector pipeline against the journal fields.

Alloy anchors every relabel regex, so a drop rule matches a label value only
as a whole; ``re.fullmatch`` reproduces that here.
"""

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "sys-svc-log-collector"
LOGGING = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "22_logging.yml"))
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
EXCLUDED_ROLES = {"sys-svc-log-collector", "web-svc-loki", "web-app-grafana"}

_RULE = re.compile(r"^  rule \{\n(?P<body>.*?)\n  \}$", re.MULTILINE | re.DOTALL)
_ATTRIBUTE = re.compile(r"^\s*(?P<key>\w+)\s*=\s*(?P<value>.+?)\s*$", re.MULTILINE)


def _docker_journald_field(label_key: str) -> str:
    """The journal field name the Docker journald driver writes for a label.

    Mirrors ``sanitizeKeyMod`` of moby's ``daemon/logger/journald``: letters
    are upper-cased, every other character but a digit becomes ``_``, and
    leading underscores are dropped.

    Args:
        label_key: the container label key listed in the ``labels`` log option.
    """
    field = ""
    for char in label_key:
        if "a" <= char <= "z":
            sanitized = char.upper()
        elif "A" <= char <= "Z" or "0" <= char <= "9":
            sanitized = char
        else:
            sanitized = "_"
        if not (field == "" and sanitized == "_"):
            field += sanitized
    return field


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )
    return env


def _resolve(env: Environment, value: str, scope: dict) -> str:
    return env.from_string(value).render(**scope)


def _excluded(env: Environment) -> list[str]:
    literals = {
        key: value
        for key, value in ROLE_VARS.items()
        if isinstance(value, str) and "{{" not in value
    }
    return [
        _resolve(env, item, literals)
        for item in ROLE_VARS["LOG_COLLECTOR_SELF_EXCLUDED"]
    ]


def _render() -> str:
    env = _environment()
    variables = {
        "DOCKER_LOG_JOURNAL_FIELD": _resolve(
            env, LOGGING["DOCKER_LOG_JOURNAL_FIELD"], LOGGING
        ),
        "LOG_COLLECTOR_SELF_EXCLUDED": _excluded(env),
        "LOG_REDACTION_RULES": LOGGING["LOG_REDACTION_RULES"],
        "LOG_REDACTION_REPLACEMENT": LOGGING["LOG_REDACTION_REPLACEMENT"],
        "LOG_COLLECTOR_JOURNAL_PATH": ROLE_VARS["LOG_COLLECTOR_JOURNAL_PATH"],
        "LOG_COLLECTOR_JOURNAL_MAX_AGE": "12h",
        "LOG_COLLECTOR_PUSH_URL": "https://loki.example.org/loki/api/v1/push",
        "LOG_COLLECTOR_TENANT": "infinito",
        "LOG_COLLECTOR_MAX_BACKOFF_PERIOD": "5m",
        "LOG_COLLECTOR_MAX_BACKOFF_RETRIES": "100",
        "LOG_COLLECTOR_CA_ENABLED": False,
        "inventory_hostname": "node-1",
    }
    template = env.get_template(
        "roles/sys-svc-log-collector/templates/collector.alloy.j2"
    )
    return template.render(**variables)


def _drop_rules(rendered: str) -> list[dict]:
    rules = []
    for match in _RULE.finditer(rendered):
        attributes = {
            attribute.group("key"): json.loads(attribute.group("value"))
            for attribute in _ATTRIBUTE.finditer(match.group("body"))
        }
        if attributes.get("action") == "drop":
            rules.append(attributes)
    return rules


class TestCollectorSelfExclusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = _drop_rules(_render())

    def test_the_excluded_ids_are_the_collector_loki_and_grafana(self) -> None:
        self.assertEqual(EXCLUDED_ROLES, set(_excluded(_environment())))

    def test_every_excluded_id_is_a_role(self) -> None:
        for role in sorted(EXCLUDED_ROLES):
            with self.subTest(role=role):
                self.assertTrue((PROJECT_ROOT / "roles" / role).is_dir())

    def test_lines_are_dropped_by_application_field_and_by_tag(self) -> None:
        application_field = (
            "__journal_" + _docker_journald_field(LOGGING["DOCKER_LOG_LABEL"]).lower()
        )
        self.assertEqual(
            {(application_field,), ("__journal_syslog_identifier",)},
            {tuple(rule["source_labels"]) for rule in self.rules},
        )

    def test_every_drop_rule_matches_each_excluded_id(self) -> None:
        for rule in self.rules:
            for role in sorted(EXCLUDED_ROLES):
                with self.subTest(source=rule["source_labels"], role=role):
                    self.assertIsNotNone(re.fullmatch(rule["regex"], role))

    def test_no_drop_rule_matches_another_application(self) -> None:
        others = ("svc-prx-openresty", "loki-canary", "web-app-grafana-x", "web-svc")
        for rule in self.rules:
            for other in others:
                with self.subTest(source=rule["source_labels"], other=other):
                    self.assertIsNone(re.fullmatch(rule["regex"], other))


if __name__ == "__main__":
    unittest.main()
