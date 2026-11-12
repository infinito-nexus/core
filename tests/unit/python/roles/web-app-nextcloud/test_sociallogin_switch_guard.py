from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/web-app-nextcloud"
PLUGIN = ROLE / "tasks/02_manager_ops/06_plugin.yml"
PROBE = ROLE / "files/php/utils/sociallogin_accounts.php"
PROBE_TASK = "Read the accounts sociallogin created or connected before user_oidc"
GUARD_TASK = "Refuse a switch to user_oidc that would give a sociallogin account"
SUB = "3f2a9c4e-0b1d-4e5f-8a6b-7c8d9e0f1a2b"


def _load_filters():
    path = ROLE / "filter_plugins/nextcloud_sociallogin.py"
    spec = importlib.util.spec_from_file_location(
        "nextcloud_sociallogin_guard", str(path)
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_sociallogin_guard"] = module
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


ENVIRONMENT = Environment(autoescape=True)
ENVIRONMENT.filters.update(_load_filters())
TASKS = load_yaml_any(str(PLUGIN), default_if_missing=[])


def _index(fragment: str) -> int:
    found = [i for i, task in enumerate(TASKS) if fragment in task.get("name", "")]
    if not found:
        raise AssertionError(f"06_plugin.yml has no task {fragment!r}")
    return found[0]


def _probe(created=(), connected=()) -> dict:
    state = {"created": list(created), "connected": list(connected)}
    return {"stdout": "SOCIALLOGIN_ACCOUNTS " + json.dumps(state)}


def _app_list(*enabled: str) -> dict:
    return {
        "stdout": json.dumps(
            {
                "enabled": dict.fromkeys(enabled, "1.0.0"),
                "disabled": {"sociallogin": "6.6.3"},
            }
        )
    }


class TestSocialloginSwitchGuard(unittest.TestCase):
    def test_the_guard_runs_after_the_plan_and_before_any_plugin_changes(self):
        order = [
            _index("Plan which plugins need an install"),
            _index(PROBE_TASK),
            _index(GUARD_TASK),
            _index("Disable the plugins that end up disabled"),
            _index("Install the plugins Nextcloud lacks"),
        ]
        self.assertEqual(order, sorted(order))

    def test_the_probe_runs_only_while_a_switch_to_user_oidc_is_pending(self):
        when = TASKS[_index(PROBE_TASK)]["when"]
        self.assertEqual(when[0], "lookup('sso_oidc_plugin') == 'user_oidc'")
        for enabled, runs in ((("files",), True), (("files", "user_oidc"), False)):
            with self.subTest(enabled=enabled):
                templar = Templar(
                    loader=DataLoader(),
                    variables={"nextcloud_app_list": _app_list(*enabled)},
                )
                self.assertEqual(
                    templar.evaluate_conditional(_trust_as_template(when[1])), runs
                )

    def test_the_probe_reads_both_kinds_of_sociallogin_account(self):
        command = TASKS[_index(PROBE_TASK)]["ansible.builtin.command"]
        self.assertEqual(
            command["stdin"],
            "{{ lookup('file', 'php/utils/sociallogin_accounts.php') }}",
        )
        source = read_text(str(PROBE))
        for fragment in (
            '"disable_password_confirmation"',
            '"sociallogin_connect"',
            'echo "SOCIALLOGIN_ACCOUNTS "',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_the_switch_is_refused_while_sociallogin_holds_an_account(self):
        guard = TASKS[_index(GUARD_TASK)]
        self.assertEqual(guard["when"], "nextcloud_sociallogin_probe is not skipped")
        check = ENVIRONMENT.compile_expression(
            guard["ansible.builtin.assert"]["that"][0]
        )
        for probe, passes in (
            (_probe(), True),
            (_probe(created=[f"keycloak-{SUB}"]), False),
            (
                _probe(
                    connected=[
                        {"uid": "administrator", "identifier": f"keycloak-{SUB}"}
                    ]
                ),
                False,
            ),
        ):
            with self.subTest(probe=probe["stdout"]):
                self.assertEqual(bool(check(nextcloud_sociallogin_probe=probe)), passes)

    def test_the_refusal_names_every_account_and_the_migration_step(self):
        message = ENVIRONMENT.from_string(
            TASKS[_index(GUARD_TASK)]["ansible.builtin.assert"]["fail_msg"]
        ).render(
            application_id="web-app-nextcloud",
            OIDC={"ATTRIBUTES": {"USERNAME": "preferred_username"}},
            nextcloud_sociallogin_probe=_probe(
                created=[f"keycloak-{SUB}"],
                connected=[{"uid": "administrator", "identifier": "keycloak-other"}],
            ),
        )
        for fragment in (
            f"keycloak-{SUB} (created by sociallogin)",
            "administrator (connected to keycloak-other)",
            "Migration step before the switch",
            "preferred_username",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, message)


if __name__ == "__main__":
    unittest.main()
