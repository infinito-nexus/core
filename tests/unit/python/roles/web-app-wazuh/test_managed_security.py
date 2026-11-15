from __future__ import annotations

import base64
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from ansible.parsing.dataloader import DataLoader
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_FORMS

ROLE = PROJECT_ROOT / "roles" / "web-app-wazuh"
FORMS = ROLE / ROLE_FILE_META_FORMS
CORE = ROLE / "tasks" / "00_core.yml"
TEMPLATES = ROLE / "templates"
ROLES = ROLE / "files" / "roles.yml"
FILTER = ROLE / "filter_plugins" / "wazuh_rendered.py"
DRIFT = "tasks/utils/forms/drift.yml"
RENDERED = ("roles_mapping.yml", "opensearch_dashboards.yml", "wazuh.yml")
SINKS = {
    "WAZUH_SECURITY": {
        "admin_group": "/roles/web-app-wazuh/administrator",
        "analyst_group": "/roles/web-app-wazuh/security-analyst",
        "readonly_group": "/roles/web-app-wazuh/readonly-auditor",
    },
    "WAZUH_DASHBOARD": {
        "default_route": "/app/home",
        "api_url": "https://wazuh.manager",
        "api_port": 55000,
        "api_username": "wazuh-wui",
    },
}


def _filter():
    spec = spec_from_file_location("wazuh_rendered", FILTER)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.wazuh_rendered


def _render(name: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.get_template(f"{name}.j2").render(
        **SINKS,
        WAZUH_RBAC_ADMIN_LDAP_CN="web-app-wazuh-administrator",
        WAZUH_RBAC_ANALYST_LDAP_CN="web-app-wazuh-security-analyst",
        WAZUH_RBAC_READONLY_LDAP_CN="web-app-wazuh-readonly-auditor",
        WAZUH_DASHBOARD_SERVICE_USERNAME="dashboard",
        WAZUH_DASHBOARD_INTERNAL_PORT=5601,
        WAZUH_INDEXER_URL="https://wazuh.indexer:9200",
        WAZUH_DESIGN_ENABLED=False,
        WAZUH_OIDC_ENABLED=False,
        WAZUH_API_HOST_ID="default",
        WAZUH_WUI_PASSWORD="unused",
    )


def _slurped() -> list[dict]:
    return [
        {"item": name, "content": base64.b64encode(_render(name).encode()).decode()}
        for name in RENDERED
    ]


class TestTheDriftReadsWhatTheTemplatesRender(unittest.TestCase):
    def test_each_form_reads_back_the_values_its_sink_rendered(self) -> None:
        self.assertEqual(
            {
                "security": SINKS["WAZUH_SECURITY"],
                "dashboard": SINKS["WAZUH_DASHBOARD"],
            },
            _filter()(_slurped()),
        )

    def test_a_form_whose_file_the_slurp_did_not_read_is_skipped(self) -> None:
        slurped = _slurped()
        slurped[2] = {"item": "wazuh.yml", "failed": True}
        held = _filter()(slurped)
        self.assertNotIn("dashboard", held)
        self.assertEqual(SINKS["WAZUH_SECURITY"], held["security"])


class TestOpenSearchLocksTheManagedSecurity(unittest.TestCase):
    def test_every_managed_role_mapping_is_reserved(self) -> None:
        mappings = load_yaml_str(_render("roles_mapping.yml"))
        mappings.pop("_meta")
        self.assertEqual({True}, {entry["reserved"] for entry in mappings.values()})

    def test_every_managed_role_is_reserved(self) -> None:
        roles = load_yaml_any(str(ROLES))
        roles.pop("_meta")
        self.assertEqual({True}, {entry["reserved"] for entry in roles.values()})

    def test_both_forms_are_native(self) -> None:
        forms = load_yaml_any(str(FORMS))
        self.assertEqual(
            {"security": True, "dashboard": True},
            {form: block.get("native") for form, block in forms.items()},
        )


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_read_and_the_report_run_before_the_render(self) -> None:
        tasks = DataLoader().load_from_file(str(CORE), trusted_as_template=True)

        def index(predicate) -> int:
            return next(i for i, task in enumerate(tasks) if predicate(task))

        read = index(lambda task: "ansible.builtin.slurp" in task)
        report = index(
            lambda task: DRIFT in str(task.get("ansible.builtin.include_tasks", ""))
        )
        render = index(
            lambda task: (
                "stack_host_template" in task
                and "roles_mapping.yml" in task.get("loop", [])
            )
        )
        self.assertLess(read, report)
        self.assertLess(report, render)
        self.assertEqual(list(RENDERED), tasks[read]["loop"])


if __name__ == "__main__":
    unittest.main()
