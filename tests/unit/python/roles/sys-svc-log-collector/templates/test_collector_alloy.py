"""Pin the self-exclusion and the log classes of the collector pipeline.

Alloy anchors every relabel regex, so a rule matches a label value only as a
whole; ``re.fullmatch`` reproduces that here.
"""

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "sys-svc-log-collector"
TEMPLATE = "roles/sys-svc-log-collector/templates/collector.alloy.j2"
LOGGING = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "22_logging.yml"))
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
LOKI_SERVICES = load_yaml_any(
    str(PROJECT_ROOT / "roles" / "web-svc-loki" / ROLE_FILE_META_SERVICES)
)
EXCLUDED_ROLES = {"sys-svc-log-collector", "web-svc-loki", "web-app-grafana"}
PROXY = "svc-prx-openresty"
STDOUT_PRIORITY = "6"
STDERR_PRIORITY = "3"

_RULE = re.compile(r"^  rule \{\n(?P<body>.*?)\n  \}$", re.MULTILINE | re.DOTALL)
_ATTRIBUTE = re.compile(r"^\s*(?P<key>\w+)\s*=\s*(?P<value>.+?)\s*$", re.MULTILINE)
_ACCESS_RULE = re.compile(
    r'\n  rule \{\n(?:(?!\n  \}).)*replacement   = "access"\n  \}\n', re.DOTALL
)


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


APPLICATION_FIELD = (
    "__journal_" + _docker_journald_field(LOGGING["DOCKER_LOG_LABEL"]).lower()
)


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )
    return env


def _resolve(env: Environment, value: str, scope: dict) -> str:
    return env.from_string(value).render(**scope)


def _literals() -> dict:
    return {
        key: value
        for key, value in ROLE_VARS.items()
        if isinstance(value, str) and "{{" not in value
    }


def _excluded(env: Environment) -> list[str]:
    return [
        _resolve(env, item, _literals())
        for item in ROLE_VARS["LOG_COLLECTOR_SELF_EXCLUDED"]
    ]


def _render(source: str | None = None) -> str:
    env = _environment()
    variables = {
        "DOCKER_LOG_JOURNAL_FIELD": _resolve(
            env, LOGGING["DOCKER_LOG_JOURNAL_FIELD"], LOGGING
        ),
        "LOG_COLLECTOR_SELF_EXCLUDED": _excluded(env),
        "LOG_COLLECTOR_ACCESS_LOG_APPLICATIONS": ROLE_VARS[
            "LOG_COLLECTOR_ACCESS_LOG_APPLICATIONS"
        ],
        "LOG_COLLECTOR_STDOUT_PRIORITY": ROLE_VARS["LOG_COLLECTOR_STDOUT_PRIORITY"],
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
    template = env.get_template(TEMPLATE) if source is None else env.from_string(source)
    return template.render(**variables)


def _rules(rendered: str) -> list[dict]:
    return [
        {
            attribute.group("key"): json.loads(attribute.group("value"))
            for attribute in _ATTRIBUTE.finditer(match.group("body"))
        }
        for match in _RULE.finditer(rendered)
    ]


def _drop_rules(rendered: str) -> list[dict]:
    return [rule for rule in _rules(rendered) if rule.get("action") == "drop"]


def _relabel(rules: list[dict], labels: dict) -> dict | None:
    """Apply Alloy relabel rules the way ``loki.relabel`` does.

    Args:
        rules: the parsed rules, in file order; ``action`` defaults to
            ``replace``, ``regex`` to ``(.*)`` and ``replacement`` to ``$1``.
        labels: the journal labels of one entry.

    Returns:
        The resulting labels, or None when a drop rule matched.
    """
    result = dict(labels)
    for rule in rules:
        value = ";".join(result.get(name, "") for name in rule.get("source_labels", []))
        match = re.fullmatch(rule.get("regex", "(.*)"), value)
        if match is None:
            continue
        if rule.get("action", "replace") == "drop":
            return None
        template = re.sub(r"\$(\d+)", r"\\g<\1>", rule.get("replacement", "$1"))
        result[rule["target_label"]] = match.expand(template)
    return result


def _container_line(application: str, priority: str) -> dict:
    return {
        APPLICATION_FIELD: application,
        "__journal_container_name": application.rsplit("-", 1)[-1],
        "__journal_priority": priority,
        "__journal__systemd_unit": "docker.service",
    }


def _log_class(rendered: str, labels: dict) -> str:
    result = _relabel(_rules(rendered), labels)
    if result is None:
        raise AssertionError(f"the pipeline dropped {labels}")
    return result["log_class"]


def _assigned_classes(rendered: str) -> set[str]:
    return {
        rule["replacement"]
        for rule in _rules(rendered)
        if rule.get("target_label") == "log_class"
    }


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
        self.assertEqual(
            {(APPLICATION_FIELD,), ("__journal_syslog_identifier",)},
            {tuple(rule["source_labels"]) for rule in self.rules},
        )

    def test_every_drop_rule_matches_each_excluded_id(self) -> None:
        for rule in self.rules:
            for role in sorted(EXCLUDED_ROLES):
                with self.subTest(source=rule["source_labels"], role=role):
                    self.assertIsNotNone(re.fullmatch(rule["regex"], role))

    def test_no_drop_rule_matches_another_application(self) -> None:
        others = (PROXY, "loki-canary", "web-app-grafana-x", "web-svc")
        for rule in self.rules:
            for other in others:
                with self.subTest(source=rule["source_labels"], other=other):
                    self.assertIsNone(re.fullmatch(rule["regex"], other))


class TestCollectorLogClass(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendered = _render()

    def test_the_proxy_access_log_is_the_access_class(self) -> None:
        self.assertEqual(
            "access", _log_class(self.rendered, _container_line(PROXY, STDOUT_PRIORITY))
        )

    def test_the_proxy_error_log_stays_an_application_line(self) -> None:
        self.assertEqual(
            "application",
            _log_class(self.rendered, _container_line(PROXY, STDERR_PRIORITY)),
        )

    def test_the_stdout_of_another_application_stays_an_application_line(
        self,
    ) -> None:
        for application in ("web-app-nextcloud", "svc-prx-openresty-x", "openresty"):
            with self.subTest(application=application):
                self.assertEqual(
                    "application",
                    _log_class(
                        self.rendered, _container_line(application, STDOUT_PRIORITY)
                    ),
                )

    def test_ssh_and_auth_facility_lines_are_the_security_class(self) -> None:
        for labels in (
            {"__journal__systemd_unit": "sshd.service", "__journal_priority": "6"},
            {
                "__journal__systemd_unit": "cron.service",
                "__journal_syslog_facility": "10",
            },
        ):
            with self.subTest(labels=labels):
                self.assertEqual("security", _log_class(self.rendered, labels))

    def test_other_host_lines_are_the_system_class(self) -> None:
        self.assertEqual(
            "system",
            _log_class(
                self.rendered,
                {
                    "__journal__systemd_unit": "docker.service",
                    "__journal_priority": "6",
                },
            ),
        )

    def test_the_access_log_applications_are_roles(self) -> None:
        for role in ROLE_VARS["LOG_COLLECTOR_ACCESS_LOG_APPLICATIONS"]:
            with self.subTest(role=role):
                self.assertTrue((PROJECT_ROOT / "roles" / role).is_dir())

    def test_negative_control_without_the_access_rule_proxy_stdout_is_application(
        self,
    ) -> None:
        source = read_text(str(PROJECT_ROOT / TEMPLATE))
        stripped = _ACCESS_RULE.sub("\n", source, count=1)
        self.assertNotEqual(source, stripped)
        self.assertEqual(
            "application",
            _log_class(_render(stripped), _container_line(PROXY, STDOUT_PRIORITY)),
        )


class TestCollectorClassesMeetLoki(unittest.TestCase):
    def test_every_class_the_collector_assigns_has_a_retention(self) -> None:
        self.assertEqual(
            _assigned_classes(_render()), set(LOKI_SERVICES["loki"]["retention"])
        )

    def test_negative_control_a_retention_map_without_the_access_class_differs(
        self,
    ) -> None:
        retention = dict(LOKI_SERVICES["loki"]["retention"])
        retention.pop("access")
        self.assertEqual({"access"}, _assigned_classes(_render()) - set(retention))

    def test_the_critical_alerts_read_only_the_application_class(self) -> None:
        selector = '{log_class="application"}'
        sources = {
            "loki ruler": read_text(
                str(
                    PROJECT_ROOT
                    / "roles"
                    / "web-svc-loki"
                    / "templates"
                    / "rules.yaml.j2"
                )
            ),
            "grafana alert": load_yaml_any(
                str(
                    PROJECT_ROOT / "roles" / "web-app-grafana" / ROLE_FILE_META_SERVICES
                )
            )["grafana"]["provisioning"]["log_alert_expr"],
        }
        for name, text in sources.items():
            with self.subTest(source=name):
                self.assertEqual([selector], re.findall(r"\{log_class[^}]*\}", text))


if __name__ == "__main__":
    unittest.main()
