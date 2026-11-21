"""The sweep publishes a status for exactly the applications with a card."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

TASKS = PROJECT_ROOT / "roles" / "sys-ctl-hlth-webserver" / "tasks" / "00_core.yml"
LOOKUPS = PROJECT_ROOT / "plugins" / "lookup"
DASHBOARD_TASK_NAMES = ("02_manager_ops.yml", "_instance_config.yml")
DASHBOARD_TASKS = tuple(
    PROJECT_ROOT / "roles" / "web-app-dashboard" / "tasks" / name
    for name in DASHBOARD_TASK_NAMES
)


def _plugin(name: str):
    """Load a lookup plugin of ``plugins/lookup`` by file.

    Args:
        name: the plugin's file name without ``.py``.
    """
    spec = importlib.util.spec_from_file_location(
        f"status_applications_{name}", LOOKUPS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LookupModule


def _rendered(templar: Templar, value):
    """Render every string of a role file value, as the merged view does.

    Args:
        templar: holds ``group_names`` and ``DOMAIN_PRIMARY``.
        value: a value loaded from a role file.
    """
    if isinstance(value, dict):
        return {key: _rendered(templar, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rendered(templar, item) for item in value]
    if isinstance(value, str):
        return templar.template(trust_as_template(value))
    return value


def _role_set(templar: Templar) -> dict:
    """Return the applications of every role, with the keys both lookups read.

    The domains stay unrendered: both lookups only ask whether a role has one.

    Args:
        templar: renders the ``group_names`` conditions of the bindings.
    """
    applications = {}
    for role in sorted((PROJECT_ROOT / "roles").iterdir()):
        role_vars = load_yaml_any(
            str(role / ROLE_FILE_VARS_MAIN), default_if_missing={}
        )
        if not isinstance(role_vars, dict) or not role_vars.get("application_id"):
            continue
        services = load_yaml_any(
            str(role / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        domains = load_yaml_any(
            str(role / ROLE_FILE_META_DOMAINS), default_if_missing={}
        )
        binding = (services or {}).get("dashboard")
        applications[role_vars["application_id"]] = {
            "services": {}
            if binding is None
            else {"dashboard": _rendered(templar, binding)},
            "domains": domains or {},
        }
    return applications


def _expression(path: Path, pattern: str) -> str:
    """Return the one Jinja expression ``pattern`` captures in a task file.

    Args:
        path: the task file.
        pattern: a regular expression whose first group is the expression.
    """
    found = re.findall(pattern, read_text(str(path)))
    if len(found) != 1:
        raise AssertionError(f"expected one match of {pattern!r} in {path}: {found}")
    return found[0]


class TestStatusApplications(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cwd = Path.cwd()
        os.chdir(PROJECT_ROOT)
        cls.addClassCleanup(os.chdir, cwd)
        ids = [
            load_yaml_any(str(role / ROLE_FILE_VARS_MAIN), default_if_missing={}).get(
                "application_id"
            )
            for role in (PROJECT_ROOT / "roles").iterdir()
            if (role / ROLE_FILE_VARS_MAIN).is_file()
        ]
        cls.application_ids = sorted(i for i in ids if i)
        cls.docker_cards = _plugin("docker_cards")
        cls.roles_with_service = _plugin("roles_with_service")
        cls.sweep = _expression(TASKS, r"--status-applications '(\{\{.*?\}\})'")
        cls.dashboard = {
            path.name: _expression(path, r'portfolio_cards: "(\{\{.*?\}\})"')
            for path in DASHBOARD_TASKS
        }

    def _get(self, applications, name, *_, **kwargs):
        plugins = {
            "docker_cards": self.docker_cards,
            "roles_with_service": self.roles_with_service,
        }
        if name in plugins:
            return plugins[name](loader=kwargs["loader"], templar=kwargs["templar"])
        stub = mock.Mock()
        if name == "applications":
            stub.run.return_value = [applications]
        elif name == "domains":
            stub.run.return_value = [
                {
                    app: (config["domains"].get("canonical") or "")
                    for app, config in applications.items()
                }
            ]
        elif name in ("tls", "canonical_url"):
            stub.run.side_effect = lambda terms, **_: [
                f"https://{terms[0]}.example.org"
            ]
        else:
            raise AssertionError(f"unexpected lookup {name!r}")
        return stub

    def _host(self, group_names: list[str]):
        """Render the sweep argument and the dashboard's cards on one host.

        Args:
            group_names: the roles deployed on the host.

        Returns:
            ``(published, cards)``: the ids the sweep publishes and, per
            dashboard task file, the ids of the cards it renders.
        """
        templar = Templar(
            loader=DataLoader(),
            variables={"group_names": group_names, "DOMAIN_PRIMARY": "example.org"},
        )
        applications = _role_set(templar)

        def get(name, *args, **kwargs):
            return self._get(applications, name, *args, **kwargs)

        with mock.patch.object(lookup_loader, "get", side_effect=get):
            published = json.loads(templar.template(trust_as_template(self.sweep)))
            cards = {
                name: [
                    card["id"]
                    for card in templar.template(trust_as_template(expression))
                ]
                for name, expression in self.dashboard.items()
            }
        return published, cards

    def _assert_published_equals_cards(self, published, cards):
        self.assertEqual(sorted(cards), sorted(DASHBOARD_TASK_NAMES))
        for name, ids in cards.items():
            self.assertEqual(sorted(published), sorted(ids), name)

    def test_the_sweep_publishes_exactly_the_cards_the_dashboard_renders(self):
        published, cards = self._host(self.application_ids)

        self.assertIn("web-app-dashboard", published)
        self._assert_published_equals_cards(published, cards)

    def test_a_host_without_the_dashboard_publishes_what_its_cards_would_show(self):
        group_names = [i for i in self.application_ids if i != "web-app-dashboard"]
        published, cards = self._host(group_names)

        self.assertNotIn("web-app-dashboard", published)
        self._assert_published_equals_cards(published, cards)


if __name__ == "__main__":
    unittest.main()
