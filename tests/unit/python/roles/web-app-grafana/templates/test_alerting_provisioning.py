import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.dotenv import dotenv_quote, dotenv_unquote
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-grafana"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def _render(prometheus: bool, loki: bool) -> dict:
    env = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    variables = {
        "GRAFANA_PROMETHEUS_ENABLED": prometheus,
        "GRAFANA_LOKI_ENABLED": loki,
        "GRAFANA_ALERTMANAGER_RECEIVER": ROLE_VARS["GRAFANA_ALERTMANAGER_RECEIVER"],
        "GRAFANA_ALERTING": {
            "alertmanager_url": "http://prometheus-alertmanager:9093",
            "log_alert_expr": 'sum by (application, host) (count_over_time({log_class="application"} |~ "x" [5m]))',
        },
        "GRAFANA_DASHBOARDS": {"folder": "Infinito.Nexus"},
        "GRAFANA_LOG_ALERT_TITLE": ROLE_VARS["GRAFANA_LOG_ALERT_TITLE"],
        "GRAFANA_LOKI_DATASOURCE_UID": ROLE_VARS["GRAFANA_LOKI_DATASOURCE_UID"],
    }
    return load_yaml_str(
        env.get_template("provisioning/alerting.yml.j2").render(**variables)
    )


def _env_template_line(key: str) -> str:
    text = read_text(str(ROLE_DIR / "templates" / "playwright.env.j2"))
    match = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"playwright.env.j2 renders no {key}")
    return match.group(1)


def _env_value(key: str) -> str:
    """
    Args:
        key: a variable playwright.env.j2 sets.

    Returns:
        Its rendered value as the spec reads it back from the env file.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["dotenv_quote"] = dotenv_quote
    return dotenv_unquote(env.from_string(_env_template_line(key)).render(**ROLE_VARS))


class TestAlertingProvisioning(unittest.TestCase):
    def test_the_policy_routes_to_the_alertmanager_contact_point(self) -> None:
        rendered = _render(prometheus=True, loki=True)
        receiver = ROLE_VARS["GRAFANA_ALERTMANAGER_RECEIVER"]
        self.assertEqual(
            [receiver], [point["name"] for point in rendered["contactPoints"]]
        )
        self.assertEqual(
            [receiver], [policy["receiver"] for policy in rendered["policies"]]
        )

    def test_the_contact_point_posts_to_the_alertmanager(self) -> None:
        rendered = _render(prometheus=True, loki=True)
        (integration,) = rendered["contactPoints"][0]["receivers"]
        self.assertEqual("prometheus-alertmanager", integration["type"])
        self.assertEqual(
            "http://prometheus-alertmanager:9093", integration["settings"]["url"]
        )

    def test_the_log_rule_carries_the_shared_title(self) -> None:
        rendered = _render(prometheus=True, loki=True)
        titles = [
            rule["title"] for group in rendered["groups"] for rule in group["rules"]
        ]
        self.assertEqual([ROLE_VARS["GRAFANA_LOG_ALERT_TITLE"]], titles)

    def test_without_prometheus_no_contact_point_is_provisioned(self) -> None:
        rendered = _render(prometheus=False, loki=True)
        self.assertNotIn("contactPoints", rendered)
        self.assertNotIn("policies", rendered)

    def test_without_loki_no_log_rule_is_provisioned(self) -> None:
        self.assertNotIn("groups", _render(prometheus=True, loki=False))


class TestAlertingSpecEnvironment(unittest.TestCase):
    def test_the_spec_reads_the_provisioned_title(self) -> None:
        rendered = _render(prometheus=True, loki=True)
        self.assertEqual(
            [rule["title"] for group in rendered["groups"] for rule in group["rules"]],
            [_env_value("LOG_ALERT_TITLE")],
        )

    def test_the_spec_reads_the_provisioned_contact_point(self) -> None:
        rendered = _render(prometheus=True, loki=True)
        self.assertEqual(
            [point["name"] for point in rendered["contactPoints"]],
            [_env_value("LOG_ALERT_RECEIVER")],
        )


if __name__ == "__main__":
    unittest.main()
