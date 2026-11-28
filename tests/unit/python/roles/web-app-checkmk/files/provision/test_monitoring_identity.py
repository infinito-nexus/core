from __future__ import annotations

import ast
import io
import unittest
import unittest.mock
import urllib.error
from functools import partial
from importlib.util import module_from_spec, spec_from_file_location

from tests.utils.redirecting_site import REDIRECT_TARGET, redirecting_site
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-checkmk"
SCRIPT = ROLE / "files" / "python" / "provision" / "monitoring_identity.py"
PROGRAM = "/omd/sites/cmk/local/bin/infinito_agent_ssh"
ENV = {
    "MONITORING_USER": "monitoring",
    "MONITORING_SECRET": "s" * 48,
    "MONITORING_FOLDER": "workspaces",
    "MONITORING_GROUP": "workspaces",
    "MONITORING_ROLE": "workspaces",
    "AGENT_PROGRAM": PROGRAM,
    "CHECKMK_SITE": "cmk",
}
INHERITED = ("general.see_all", "general.edit_profile", "action.reschedule", "wato.use")
FULL_MAP = {
    "action.reschedule": "no",
    "general.edit_profile": "no",
    "general.see_all": "no",
    "wato.activate": "yes",
    "wato.activateforeign": "no",
    "wato.add_or_modify_executables": "no",
    "wato.all_folders": "no",
    "wato.analyze_config": "no",
    "wato.auditlog": "no",
    "wato.automation": "no",
    "wato.backups": "no",
    "wato.check_plugins": "no",
    "wato.clear_auditlog": "no",
    "wato.clone_hosts": "no",
    "wato.custom_attributes": "no",
    "wato.diag_host": "no",
    "wato.diagnostics": "no",
    "wato.discard": "no",
    "wato.discardforeign": "no",
    "wato.download_agent_output": "no",
    "wato.download_agents": "no",
    "wato.edit": "yes",
    "wato.edit_all_passwords": "no",
    "wato.edit_all_predefined_conditions": "no",
    "wato.edit_folders": "yes",
    "wato.edit_hosts": "yes",
    "wato.global": "no",
    "wato.groups": "no",
    "wato.hosts": "yes",
    "wato.hosttags": "no",
    "wato.icons": "no",
    "wato.manage_folders": "yes",
    "wato.manage_hosts": "yes",
    "wato.move_hosts": "no",
    "wato.notifications": "no",
    "wato.parentscan": "no",
    "wato.passwords": "no",
    "wato.pattern_editor": "no",
    "wato.random_hosts": "no",
    "wato.rename_hosts": "no",
    "wato.rulesets": "yes",
    "wato.see_all_folders": "no",
    "wato.seeall": "no",
    "wato.service_discovery_to_ignored": "no",
    "wato.service_discovery_to_monitored": "yes",
    "wato.service_discovery_to_removed": "yes",
    "wato.service_discovery_to_undecided": "yes",
    "wato.services": "yes",
    "wato.set_read_only": "no",
    "wato.show_last_user_activity": "no",
    "wato.sites": "no",
    "wato.snapshots": "no",
    "wato.timeperiods": "no",
    "wato.update_dns_cache": "no",
    "wato.use": "yes",
    "wato.user_migrate": "no",
    "wato.users": "no",
}


def _load():
    spec = spec_from_file_location("monitoring_identity", SCRIPT)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


identity = _load()


class FakeSite:
    def __init__(self):
        self.groups = set()
        self.roles = {"user": dict.fromkeys(INHERITED, "yes")}
        self.folders = {}
        self.users = {}
        self.rules = {}
        self.writes = []

    def __call__(self, method, path, payload=None, headers=None):
        if method != "GET":
            self.writes.append((method, path))
        if path == "/domain-types/contact_group_config/collections/all":
            if method == "POST":
                self.groups.add(payload["name"])
                return 200, {}
            return 200, {"value": [{"id": g} for g in self.groups]}
        if path == "/domain-types/user_role/collections/all":
            if method == "POST":
                self.roles[payload["new_role_id"]] = dict(
                    self.roles[payload["role_id"]]
                )
                return 200, {}
            return 200, {"value": [{"id": r} for r in self.roles]}
        if path.startswith("/objects/user_role/"):
            role = self.roles[path.rsplit("/", 1)[1]]
            if method == "GET":
                return 200, {
                    "extensions": {
                        "permissions": [p for p, v in role.items() if v == "yes"]
                    }
                }
            role.update(payload["new_permissions"])
            return 200, {}
        if path == "/domain-types/folder_config/collections/all":
            self.folders[payload["name"]] = dict(payload["attributes"])
            return 200, {}
        if path.startswith("/objects/folder_config/~"):
            name = path.rsplit("~", 1)[1]
            if method == "PUT":
                self.folders[name].update(payload["update_attributes"])
                return 200, {}
            if name not in self.folders:
                return 404, {}
            return 200, {"extensions": {"attributes": self.folders[name]}}
        if path == "/domain-types/user_config/collections/all":
            if method == "POST":
                self.users[payload["username"]] = payload
                return 200, {}
            return 200, {"value": [{"id": u} for u in self.users]}
        if path.startswith("/objects/user_config/"):
            self.users[path.rsplit("/", 1)[1]].update(payload)
            return 200, {}
        if path.startswith("/domain-types/rule/collections/all"):
            if method == "POST":
                rule_id = f"r{len(self.rules)}"
                self.rules[rule_id] = {"id": rule_id, "extensions": dict(payload)}
                return 200, {}
            ruleset = path.split("ruleset_name=")[1]
            return 200, {
                "value": [
                    r
                    for r in self.rules.values()
                    if r["extensions"]["ruleset"] == ruleset
                ]
            }
        if path.startswith("/objects/rule/"):
            rule_id = path.rsplit("/", 1)[1]
            if method == "DELETE":
                del self.rules[rule_id]
                return 204, {}
            self.rules[rule_id]["extensions"].update(payload)
            return 200, {}
        if path.endswith("/activate-changes/invoke"):
            return 200, {}
        raise AssertionError(f"unexpected call {method} {path}")


class TestTheConfinement(unittest.TestCase):
    def test_the_full_permission_map_is_pinned(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        self.assertEqual(dict(site.roles["workspaces"]), FULL_MAP)

    def test_executables_and_every_inherited_permission_are_denied(self) -> None:
        mapping = identity.permissions(INHERITED)
        self.assertEqual(mapping["wato.add_or_modify_executables"], "no")
        for name in INHERITED:
            with self.subTest(permission=name):
                self.assertEqual(
                    mapping[name], "yes" if name in identity.GRANTED else "no"
                )

    def test_negative_control_a_granted_executable_permission_is_caught(self) -> None:
        self.assertNotIn("wato.add_or_modify_executables", identity.GRANTED)
        widened = {
            **identity.permissions(INHERITED),
            "wato.add_or_modify_executables": "yes",
        }
        self.assertNotEqual(widened, FULL_MAP)

    def test_every_known_wato_permission_is_explicit(self) -> None:
        mapping = identity.permissions(())
        self.assertEqual(set(mapping), set(identity.WATO_PERMISSIONS))
        self.assertEqual(len(identity.WATO_PERMISSIONS), 54)

    def test_only_the_workspaces_folder_names_the_group(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        self.assertEqual(
            site.folders["workspaces"]["contactgroups"],
            {
                "groups": ["workspaces"],
                "use": False,
                "use_for_services": False,
                "recurse_use": False,
                "recurse_perms": True,
            },
        )
        self.assertEqual(list(site.folders), ["workspaces"])

    def test_the_user_is_an_automation_user_of_the_role_and_group(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        user = site.users["monitoring"]
        self.assertEqual(user["roles"], ["workspaces"])
        self.assertEqual(user["contactgroups"], ["workspaces"])
        self.assertEqual(user["auth_option"]["auth_type"], "automation")
        self.assertFalse(user["auth_option"]["store_automation_secret"])
        self.assertEqual(list(site.users), ["monitoring"])


class TestTheAgentRule(unittest.TestCase):
    def test_one_datasource_rule_on_the_folder_calls_the_fixed_program(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        (rule,) = site.rules.values()
        extensions = rule["extensions"]
        self.assertEqual(extensions["ruleset"], "datasource_programs")
        self.assertEqual(extensions["folder"], "/workspaces")
        self.assertEqual(
            ast.literal_eval(extensions["value_raw"]),
            f"{PROGRAM} $HOSTNAME$ $HOSTADDRESS$",
        )

    def test_a_tampered_rule_is_rewritten_and_a_duplicate_dropped(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        (rule_id,) = site.rules
        site.rules[rule_id]["extensions"]["value_raw"] = repr("sh -c 'id'")
        site.rules["dup"] = {
            "id": "dup",
            "extensions": dict(site.rules[rule_id]["extensions"]),
        }
        self.assertTrue(identity.provision(site, ENV))
        self.assertEqual(list(site.rules), [rule_id])
        self.assertEqual(
            ast.literal_eval(site.rules[rule_id]["extensions"]["value_raw"]),
            f"{PROGRAM} $HOSTNAME$ $HOSTADDRESS$",
        )


class TestTheConvergence(unittest.TestCase):
    def test_a_fresh_site_reports_a_change_and_a_second_run_none(self) -> None:
        site = FakeSite()
        self.assertTrue(identity.provision(site, ENV))
        self.assertFalse(identity.provision(site, ENV))

    def test_a_widened_folder_grant_is_rewritten(self) -> None:
        site = FakeSite()
        identity.provision(site, ENV)
        site.folders["workspaces"]["contactgroups"]["groups"].append("all")
        self.assertTrue(identity.provision(site, ENV))
        self.assertEqual(
            site.folders["workspaces"]["contactgroups"]["groups"], ["workspaces"]
        )

    def test_a_refused_call_raises_with_its_status(self) -> None:
        with self.assertRaises(identity.CheckmkError) as raised:
            identity.provision(lambda *_a, **_k: (401, {}), ENV)
        self.assertEqual(raised.exception.status, 401)

    def test_an_answer_echoing_the_request_never_carries_the_password(self) -> None:
        password = "adm1n-pa55word-of-the-site"
        for echoed in (b'{"detail": "denied %s"}', b"denied %s"):

            def refuse(request, timeout, echoed=echoed):
                body = echoed % request.get_header("Authorization").encode()
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", {}, io.BytesIO(body)
                )

            with self.subTest(echoed=echoed):
                with unittest.mock.patch.object(
                    identity, "OPENER", unittest.mock.Mock(open=refuse)
                ):
                    status, body = identity.call(
                        "http://127.0.0.1/check_mk/api/1.0",
                        "cmkadmin",
                        password,
                        "GET",
                        "/version",
                    )
                self.assertEqual(status, 401)
                self.assertIn("<secret>", str(body))
                self.assertNotIn(password, str(body))

    def test_a_redirect_is_an_answer_and_the_password_never_follows_it(self) -> None:
        with redirecting_site() as (base, seen):
            status, _ = identity.call(
                base, "cmkadmin", "adm1n-pa55word", "GET", "/version"
            )
        self.assertEqual(status, 302)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(REDIRECT_TARGET, [path for path, _ in seen])

    def test_the_activation_redirect_still_counts_as_started(self) -> None:
        with redirecting_site() as (base, seen):
            identity.activate(partial(identity.call, base, "cmkadmin", "pw"), "cmk")
        self.assertEqual(len(seen), 1)


class TestTheRuleValue(unittest.TestCase):
    def tampered(self, value_raw):
        site = FakeSite()
        identity.provision(site, ENV)
        (rule_id,) = site.rules
        site.rules[rule_id]["extensions"]["value_raw"] = value_raw
        return site, rule_id

    def test_an_oversized_value_is_rewritten_even_when_it_parses(self) -> None:
        wanted = repr(f"{PROGRAM} $HOSTNAME$ $HOSTADDRESS$")
        site, rule_id = self.tampered(wanted + " " * identity.VALUE_RAW_LIMIT)
        self.assertTrue(identity.provision(site, ENV))
        self.assertEqual(site.rules[rule_id]["extensions"]["value_raw"], wanted)

    def test_a_value_the_parser_chokes_on_is_rewritten(self) -> None:
        for error in (TypeError, MemoryError, RecursionError):
            with self.subTest(error=error.__name__):
                site, _ = self.tampered(repr(f"{PROGRAM} $HOSTNAME$ $HOSTADDRESS$"))
                with unittest.mock.patch.object(
                    identity.ast, "literal_eval", side_effect=error
                ):
                    self.assertTrue(identity.provision(site, ENV))
        site, _ = self.tampered(7)
        self.assertTrue(identity.provision(site, ENV))


class TestTheWiring(unittest.TestCase):
    def test_the_tls_levels_live_in_the_role_config(self) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        levels = services["checkmk"]["monitoring"]["tls_expiry"]
        self.assertGreater(levels["warn_days"], levels["crit_days"])

    def test_the_login_and_the_public_key_go_to_the_monitoring_paths_only(self) -> None:
        values = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        login = values["CHECKMK_MONITORING_LOGIN"]
        self.assertEqual(
            (login["mount"], login["path"]), ("platform", "monitoring/checkmk")
        )
        self.assertEqual(sorted(login["data"]), ["secret", "username"])
        record = values["CHECKMK_AGENT_KEY_RECORD"]
        self.assertEqual(
            (record["mount"], record["path"]), ("platform", "monitoring/agent-key")
        )

    def test_no_registration_path_and_no_public_agent_port_remain(self) -> None:
        services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
        ports = services["checkmk"]["ports"]
        self.assertNotIn("public", ports)
        self.assertIn("agent", ports["local"])
        self.assertEqual(
            services["sso"]["oauth2"]["acl"]["whitelist"], ["/cmk/check_mk/api/"]
        )
        secrets = load_yaml_any(str(ROLE / ROLE_FILE_META_SECRETS))
        self.assertNotIn("agent_registration_secret", secrets["credentials"])

    def test_the_private_key_never_leaves_the_site(self) -> None:
        tasks = read_text(str(ROLE / "tasks" / "utils" / "monitoring.yml"))
        script = read_text(str(ROLE / "files" / "shell" / "monitoring_agent.sh"))
        self.assertIn("cut -d ' ' -f 1,2 \"${key}.pub\"", script)
        self.assertNotIn('cat "${key}"', script)
        self.assertIn("checkmk_monitoring_agent.stdout_lines[0]", tasks)


if __name__ == "__main__":
    unittest.main()
