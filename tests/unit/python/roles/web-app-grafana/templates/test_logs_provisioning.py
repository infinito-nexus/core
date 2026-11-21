"""Grafana provisions Loki and Prometheus and one log view per application."""

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles" / "web-app-grafana"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
DASHBOARD = json.loads(read_text(str(ROLE_DIR / "files" / "dashboards" / "logs.json")))
COLLECTOR = read_text(
    str(
        PROJECT_ROOT
        / "roles"
        / "sys-svc-log-collector"
        / "templates"
        / "collector.alloy.j2"
    )
)
LOKI_URL = "http://web-svc-loki:3100"
PROMETHEUS_URL = "http://web-app-prometheus:9090"
TENANT = "infinito"


def _datasources(loki: bool, prometheus: bool) -> list[dict]:
    env = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    rendered = env.get_template("provisioning/datasources.yml.j2").render(
        GRAFANA_LOKI_ENABLED=loki,
        GRAFANA_PROMETHEUS_ENABLED=prometheus,
        GRAFANA_LOKI_DATASOURCE_UID=ROLE_VARS["GRAFANA_LOKI_DATASOURCE_UID"],
        GRAFANA_PROMETHEUS_DATASOURCE_UID=ROLE_VARS[
            "GRAFANA_PROMETHEUS_DATASOURCE_UID"
        ],
        GRAFANA_DATASOURCES={
            "loki_url": LOKI_URL,
            "loki_tenant": TENANT,
            "prometheus_url": PROMETHEUS_URL,
        },
    )
    return load_yaml_str(rendered)["datasources"]


def _variable(name: str) -> dict:
    matches = [
        entry for entry in DASHBOARD["templating"]["list"] if entry["name"] == name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"logs.json declares {len(matches)} variables named {name}"
        )
    return matches[0]


class TestDatasourceProvisioning(unittest.TestCase):
    def test_loki_and_prometheus_are_provisioned_side_by_side(self) -> None:
        sources = {source["type"]: source for source in _datasources(True, True)}
        self.assertEqual({"loki", "prometheus"}, set(sources))
        loki = sources["loki"]
        self.assertEqual(ROLE_VARS["GRAFANA_LOKI_DATASOURCE_UID"], loki["uid"])
        self.assertEqual(LOKI_URL, loki["url"])
        self.assertEqual("X-Scope-OrgID", loki["jsonData"]["httpHeaderName1"])
        self.assertEqual(TENANT, loki["secureJsonData"]["httpHeaderValue1"])
        self.assertIs(True, loki["isDefault"])
        prometheus = sources["prometheus"]
        self.assertEqual(
            ROLE_VARS["GRAFANA_PROMETHEUS_DATASOURCE_UID"], prometheus["uid"]
        )
        self.assertEqual(PROMETHEUS_URL, prometheus["url"])
        self.assertEqual("false", str(prometheus["isDefault"]).lower())

    def test_no_provisioned_datasource_is_editable(self) -> None:
        self.assertEqual(
            [False, False], [source["editable"] for source in _datasources(True, True)]
        )

    def test_without_loki_prometheus_becomes_the_default(self) -> None:
        sources = _datasources(False, True)
        self.assertEqual(["prometheus"], [source["type"] for source in sources])
        self.assertEqual("true", str(sources[0]["isDefault"]).lower())

    def test_without_both_no_datasource_is_provisioned(self) -> None:
        self.assertEqual([], _datasources(False, False))


class TestLogsDashboard(unittest.TestCase):
    def test_the_application_variable_lists_every_application_loki_knows(
        self,
    ) -> None:
        variable = _variable("application")
        self.assertEqual("label_values(application)", variable["definition"])
        self.assertEqual(
            ROLE_VARS["GRAFANA_LOKI_DATASOURCE_UID"], variable["datasource"]["uid"]
        )
        self.assertIs(True, variable["includeAll"])
        self.assertIs(True, variable["multi"])

    def test_one_log_panel_repeats_per_application(self) -> None:
        panels = [panel for panel in DASHBOARD["panels"] if panel["type"] == "logs"]
        self.assertEqual(1, len(panels))
        panel = panels[0]
        self.assertEqual("application", panel["repeat"])
        self.assertEqual(
            ROLE_VARS["GRAFANA_LOKI_DATASOURCE_UID"], panel["datasource"]["uid"]
        )
        self.assertEqual(
            ['{application="$application"} |= "$search"'],
            [target["expr"] for target in panel["targets"]],
        )

    def test_the_collector_writes_the_label_the_dashboard_reads(self) -> None:
        self.assertIn('target_label  = "application"', COLLECTOR)
        self.assertEqual(
            {"application"},
            set(re.findall(r"label_values\((\w+)\)", json.dumps(DASHBOARD))),
        )


if __name__ == "__main__":
    unittest.main()
