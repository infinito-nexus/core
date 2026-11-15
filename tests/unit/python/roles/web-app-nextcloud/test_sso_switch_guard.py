from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles/web-app-nextcloud"
PLUGIN = ROLE / "tasks/02_manager_ops/06_plugin.yml"
PROBE = ROLE / "files/php/utils/sso_accounts.php"
WRITER = PROJECT_ROOT / "roles/web-app-keycloak/tasks/utils/user_attributes.yml"
PROBE_TASK = "Read the accounts each OIDC plugin keyed before another one takes over"
WRITE_TASK = "Give the Keycloak user of each sociallogin account its user id"
GUARD_TASK = "Refuse an OIDC plugin switch that gives an existing account a new user id"
SWITCH_TASK = "Guard the accounts an OIDC plugin switch rekeys"
PROVIDER = "web-app-keycloak"
SUB = "3f2a9c4e-0b1d-4e5f-8a6b-7c8d9e0f1a2b"
CREATED = f"{PROVIDER}-{SUB}"
NEXTCLOUD_UID = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/11_oidc.yml"))[
    "defaults_oidc"
]["ATTRIBUTES"]["NEXTCLOUD_UID"]


def _load_filters():
    path = ROLE / "filter_plugins/nextcloud_sso_accounts.py"
    spec = importlib.util.spec_from_file_location("nextcloud_sso_guard", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["nextcloud_sso_guard"] = module
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


ENVIRONMENT = Environment(autoescape=True)
ENVIRONMENT.filters.update(_load_filters())
ENVIRONMENT.filters["bool"] = to_bool
ENVIRONMENT.filters["from_json"] = json.loads
TASKS = load_yaml_any(str(PLUGIN), default_if_missing=[])


def _index(fragment: str) -> int:
    found = [i for i, task in enumerate(TASKS) if fragment in task.get("name", "")]
    if not found:
        raise AssertionError(f"06_plugin.yml has no task {fragment!r}")
    return found[0]


def _switch() -> dict:
    return TASKS[_index(SWITCH_TASK)]


def _switch_step(fragment: str) -> dict:
    (step,) = [task for task in _switch()["block"] if fragment in task["name"]]
    return step


def _lookup(target: str):
    def lookup(name: str) -> str:
        if name != "sso_oidc_plugin":
            raise AssertionError(f"06_plugin.yml asks an unexpected lookup {name!r}")
        return target

    return lookup


def _probe(created=(), connected=(), user_oidc=(), ldap=()) -> dict:
    state = {
        "sociallogin": {
            "providers": [PROVIDER],
            "created": list(created),
            "connected": list(connected),
        },
        "user_oidc": list(user_oidc),
        "ldap": list(ldap),
    }
    return {"stdout": "SSO_ACCOUNTS " + json.dumps(state)}


def _app_list(*enabled: str) -> dict:
    return {"stdout": json.dumps({"enabled": dict.fromkeys(enabled, "1.0.0")})}


def _expression(template: str):
    return ENVIRONMENT.compile_expression(
        template.strip().removeprefix("{{").removesuffix("}}")
    )


def _rekeyed(target: str, probe: dict, ldap: str, results: list) -> list[str]:
    return _expression(
        _switch_step(GUARD_TASK)["vars"]["nextcloud_sso_rekeyed_accounts"]
    )(
        lookup=_lookup(target),
        nextcloud_sso_accounts_probe=probe,
        NEXTCLOUD_USER_LDAP_ENABLED=ldap,
        keycloak_user_attribute_results=results,
    )


def _result(outcome: str, held=()) -> dict:
    return {"id": SUB, "value": CREATED, "outcome": outcome, "held": list(held)}


class TestSsoSwitchGuard(unittest.TestCase):
    def test_the_guard_runs_after_the_plan_and_before_any_plugin_changes(self):
        order = [
            _index("Plan which plugins need an install"),
            _index(PROBE_TASK),
            _index(SWITCH_TASK),
            _index("Disable the plugins that end up disabled"),
            _index("Install the plugins Nextcloud lacks"),
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(
            [_switch_step(WRITE_TASK), _switch_step(GUARD_TASK)], _switch()["block"]
        )

    def test_the_probe_runs_while_any_oidc_plugin_switch_is_pending(self):
        when = TASKS[_index(PROBE_TASK)]["when"]
        for target, enabled, runs in (
            ("user_oidc", ("files", "sociallogin"), True),
            ("oidc_login", ("files", "sociallogin", "user_ldap"), True),
            ("sociallogin", ("files", "oidc_login"), True),
            ("oidc_login", ("files",), True),
            ("user_oidc", ("files", "user_oidc"), False),
            ("oidc_login", ("files", "oidc_login", "user_ldap"), False),
            ("sociallogin", ("files", "sociallogin"), False),
            ("", ("files", "sociallogin"), False),
        ):
            with self.subTest(target=target, enabled=enabled):
                checks = [
                    ENVIRONMENT.compile_expression(condition)(
                        lookup=_lookup(target), nextcloud_app_list=_app_list(*enabled)
                    )
                    for condition in when
                ]
                self.assertEqual(all(checks), runs)

    def test_the_probe_reads_every_account_an_oidc_plugin_keys(self):
        command = TASKS[_index(PROBE_TASK)]["ansible.builtin.command"]
        self.assertEqual(
            command["stdin"], "{{ lookup('file', 'php/utils/sso_accounts.php') }}"
        )
        source = read_text(str(PROBE))
        for fragment in (
            '"disable_password_confirmation"',
            '"custom_providers"',
            '$rows("sociallogin_connect", ["uid", "identifier"])',
            '$rows("user_oidc", ["user_id"])',
            '$rows("ldap_user_mapping", ["owncloud_name"])',
            'echo "SSO_ACCOUNTS "',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_the_guard_asks_the_filter_with_the_target_and_the_ldap_flag(self):
        guard = _switch_step(GUARD_TASK)
        self.assertEqual(
            _switch()["when"], "nextcloud_sso_accounts_probe is not skipped"
        )
        self.assertEqual(
            guard["ansible.builtin.assert"]["that"],
            ["nextcloud_sso_rekeyed_accounts | length == 0"],
        )
        for target, probe, ldap, rekeyed in (
            ("user_oidc", _probe(), "True", []),
            (
                "oidc_login",
                _probe(created=[CREATED]),
                "True",
                [f"{CREATED} (created by sociallogin)"],
            ),
            ("user_oidc", _probe(ldap=["alice"]), "True", []),
            ("user_oidc", _probe(ldap=["alice"]), "False", ["alice (LDAP account)"]),
        ):
            with self.subTest(target=target, ldap=ldap, probe=probe["stdout"]):
                self.assertEqual(_rekeyed(target, probe, ldap, []), rekeyed)

    def test_the_switch_to_user_oidc_hands_keycloak_every_sociallogin_user_id(self):
        task = _switch_step(WRITE_TASK)
        self.assertEqual(
            task["ansible.builtin.include_role"],
            {"name": "web-app-keycloak", "tasks_from": "utils/user_attributes.yml"},
        )
        self.assertEqual(
            _switch()["when"], "nextcloud_sso_accounts_probe is not skipped"
        )
        self.assertEqual(task["vars"]["application_id"], "web-app-keycloak")
        self.assertEqual(
            task["vars"]["keycloak_user_attribute"],
            "{{ OIDC.ATTRIBUTES.NEXTCLOUD_UID }}",
        )
        header = read_text(str(WRITER))
        for name in (
            "# Param: keycloak_user_attribute ",
            "# Param: keycloak_user_attribute_values ",
            "# Output: keycloak_user_attribute_results ",
        ):
            with self.subTest(name=name):
                self.assertIn(name, header)
        values = _expression(task["vars"]["keycloak_user_attribute_values"])
        probe = _probe(created=[CREATED])
        for target, written in (
            ("user_oidc", [{"id": SUB, "value": CREATED}]),
            ("oidc_login", []),
            ("sociallogin", []),
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    values(lookup=_lookup(target), nextcloud_sso_accounts_probe=probe),
                    written,
                )

    def test_the_guard_keeps_a_mapped_account_and_names_a_conflicting_user(self):
        probe = _probe(created=[CREATED])
        self.assertEqual(_rekeyed("user_oidc", probe, "True", [_result("updated")]), [])
        self.assertEqual(
            _rekeyed("user_oidc", probe, "True", [_result("conflict", ["alice"])]),
            [
                (
                    f"{CREATED} (created by sociallogin, Keycloak user {SUB}"
                    " holds the user id alice already)"
                )
            ],
        )

    def test_the_refusal_names_the_switch_every_account_and_the_way_out(self):
        message = ENVIRONMENT.from_string(
            _switch_step(GUARD_TASK)["ansible.builtin.assert"]["fail_msg"]
        ).render(
            application_id="web-app-nextcloud",
            lookup=_lookup("oidc_login"),
            OIDC={"ATTRIBUTES": {"NEXTCLOUD_UID": NEXTCLOUD_UID}},
            nextcloud_sso_rekeyed_accounts=[
                f"{CREATED} (created by sociallogin)",
                "bob (user_oidc account)",
            ],
        )
        for fragment in (
            "the switch to oidc_login",
            f"{CREATED} (created by sociallogin), bob (user_oidc account)",
            "user_oidc keeps its own accounts",
            f"holds its user id in {NEXTCLOUD_UID}",
            "services.sso.oidc.plugin",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, message)


if __name__ == "__main__":
    unittest.main()
