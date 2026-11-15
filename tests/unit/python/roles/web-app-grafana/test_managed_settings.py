from __future__ import annotations

import base64
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from typing import TYPE_CHECKING

from ansible.parsing.dataloader import DataLoader
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from plugins.filter.dotenv import FilterModule as DotenvFilters
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.converge import values
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "web-app-grafana"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
CORE = ROLE / "tasks" / "00_core.yml"
TEMPLATES = ROLE / "templates"
FILTER = ROLE / "filter_plugins" / "grafana_provisioned.py"
ENV_DRIFT = "tasks/utils/forms/env.yml"
DRIFT = "tasks/utils/forms/drift.yml"
SETTINGS = [
    "gf_users_allow_sign_up",
    "gf_users_allow_org_create",
    "gf_auth_disable_login_form",
    "gf_auth_anonymous_enabled",
    "gf_auth_basic_enabled",
]
PROVISIONING = {
    "datasources": {
        "loki_url": "http://web-svc-loki:3100",
        "loki_tenant": "infinito",
        "prometheus_url": "http://web-app-prometheus:9090",
    },
    "dashboards": {"folder": "Infinito.Nexus"},
    "alerting": {
        "alertmanager_url": "http://prometheus-alertmanager:9093",
        "log_alert_expr": 'sum by (application, host) (count_over_time({log_class="application"} |~ "x" [5m]))',
    },
}


def _legacy_env(registration: bool, native: bool) -> dict[str, str]:
    return {
        "gf_users_allow_sign_up": str(registration).lower(),
        "gf_users_allow_org_create": "false",
        "gf_auth_disable_login_form": str(not native).lower(),
        "gf_auth_anonymous_enabled": "false",
        "gf_auth_basic_enabled": "true",
    }


def _grafana_filter():
    spec = spec_from_file_location("grafana_provisioned", FILTER)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.grafana_provisioned


def _environment(templates: Path) -> Environment:
    sources = {
        "env.j2": read_text(str(templates / "env.j2")),
        "roles/sys-svc-container/templates/env.j2": "",
    }
    for name in ("datasources", "dashboards", "alerting"):
        sources[name] = read_text(str(templates / "provisioning" / f"{name}.yml.j2"))
    env = Environment(
        loader=DictLoader(sources),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(DotenvFilters().filters())
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    return env


def _application(registration: bool, native: bool) -> dict:
    services = load_yaml_any(str(SERVICES))
    services["grafana"]["login"]["method"]["registration"]["enabled"] = registration
    services["grafana"]["login"]["method"]["native"]["enabled"] = native
    return {"services": services}


def _env(templates: Path, **variables) -> str:
    return (
        _environment(templates)
        .get_template("env.j2")
        .render(
            GRAFANA_INTERNAL_PORT=3000,
            GRAFANA_BREAKGLASS_USERNAME="admin",
            GRAFANA_BREAKGLASS_PASSWORD="unused",
            GRAFANA_OIDC_ENABLED=False,
            DEPLOYMENT_MODE="compose",
            **variables,
        )
    )


def _held(content: str) -> dict:
    template = _environment(TEMPLATES).from_string(
        "{{ content | dotenv_fields(fields) | tojson }}"
    )
    return json.loads(
        template.render(content=content, fields=SETTINGS, DEPLOYMENT_MODE="compose")
    )


class TestTheSettingsFormWritesWhatTheEnvWrote(unittest.TestCase):
    def test_every_login_switch_renders_the_values_the_old_env_rendered(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for registration in (True, False):
            for native in (True, False):
                with self.subTest(registration=registration, native=native):
                    settings = values(
                        "settings", forms, _application(registration, native), {}
                    )
                    self.assertEqual(
                        _legacy_env(registration, native),
                        _held(_env(TEMPLATES, GRAFANA_SETTINGS=settings)),
                    )

    def test_the_drift_read_takes_back_exactly_what_the_env_writes(self) -> None:
        forms = load_yaml_any(str(FORMS))
        settings = values("settings", forms, _application(False, True), {})
        self.assertEqual(settings, _held(_env(TEMPLATES, GRAFANA_SETTINGS=settings)))

    def test_every_settings_value_is_the_string_the_env_file_holds(self) -> None:
        forms = load_yaml_any(str(FORMS))
        for value in values("settings", forms, _application(True, True), {}).values():
            self.assertIsInstance(value, str)


class TestTheProvisioningDriftReadsWhatTheTemplatesRender(unittest.TestCase):
    def _slurped(self) -> list[dict]:
        env = _environment(TEMPLATES)
        results = []
        for form in ("datasources", "dashboards", "alerting"):
            rendered = env.get_template(form).render(
                GRAFANA_LOKI_ENABLED=True,
                GRAFANA_PROMETHEUS_ENABLED=True,
                GRAFANA_LOKI_DATASOURCE_UID="loki",
                GRAFANA_PROMETHEUS_DATASOURCE_UID="prometheus",
                GRAFANA_ALERTMANAGER_RECEIVER="alertmanager",
                GRAFANA_LOG_ALERT_TITLE="title",
                GRAFANA_DATASOURCES=PROVISIONING["datasources"],
                GRAFANA_DASHBOARDS=PROVISIONING["dashboards"],
                GRAFANA_ALERTING=PROVISIONING["alerting"],
                GRAFANA_DASHBOARDS_DOCKER_DIR="/var/lib/grafana/dashboards",
            )
            load_yaml_str(rendered)
            results.append(
                {"item": form, "content": base64.b64encode(rendered.encode()).decode()}
            )
        return results

    def test_each_form_reads_back_the_values_its_sink_rendered(self) -> None:
        self.assertEqual(PROVISIONING, _grafana_filter()(self._slurped()))

    def test_a_file_the_slurp_did_not_read_is_skipped(self) -> None:
        slurped = self._slurped()
        slurped[0] = {"item": "datasources", "failed": True}
        held = _grafana_filter()(slurped)
        self.assertNotIn("datasources", held)
        self.assertEqual(PROVISIONING["alerting"], held["alerting"])


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def _tasks(self) -> list[dict]:
        return DataLoader().load_from_file(str(CORE), trusted_as_template=True)

    def _index(self, predicate) -> int:
        return next(
            index for index, task in enumerate(self._tasks()) if predicate(task)
        )

    def test_the_env_drift_runs_before_the_stack_renders_the_env_file(self) -> None:
        drift = self._index(lambda task: ENV_DRIFT in str(task))
        stack = self._index(
            lambda task: (
                task.get("include_role", {}).get("tasks_from") == "consumer/back.yml"
            )
        )
        self.assertLess(drift, stack)
        self.assertEqual("settings", self._tasks()[drift]["vars"]["forms_env_form"])

    def test_the_provisioning_drift_runs_before_the_render(self) -> None:
        read = self._index(lambda task: "ansible.builtin.slurp" in task)
        report = self._index(
            lambda task: DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        render = self._index(lambda task: "render_replicated_templates" in str(task))
        self.assertLess(read, report)
        self.assertLess(report, render)


class TestTheFormsAreLockedByGrafana(unittest.TestCase):
    def test_every_settings_form_is_native(self) -> None:
        forms = load_yaml_any(str(FORMS))
        self.assertEqual(
            {
                "settings": True,
                "datasources": True,
                "dashboards": True,
                "alerting": True,
            },
            {
                form: block.get("native")
                for form, block in forms.items()
                if form != "profile"
            },
        )

    def test_the_provisioned_datasources_stay_read_only(self) -> None:
        text = read_text(str(TEMPLATES / "provisioning" / "datasources.yml.j2"))
        self.assertEqual(2, text.count("editable: false"))
        dashboards = read_text(str(TEMPLATES / "provisioning" / "dashboards.yml.j2"))
        self.assertIn("allowUiUpdates: false", dashboards)


if __name__ == "__main__":
    unittest.main()
