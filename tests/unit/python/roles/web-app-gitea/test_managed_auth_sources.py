from __future__ import annotations

import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from ansible.errors import AnsibleFilterError
from ansible.parsing.dataloader import DataLoader

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.forms import iter_fields, locks
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-gitea"
FORMS = ROLE / ROLE_FILE_META_FORMS
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
SETUP = ROLE / "tasks" / "02_setup.yml"
OAUTH_SETUP = ROLE / "tasks" / "setup" / "oauth_source.yml"
LDAP_SETUP = ROLE / "tasks" / "setup" / "ldap.yml"
SQL = ROLE / "files" / "sql" / "login-source-settings.sql"
FINGERPRINT_SQL = ROLE / "files" / "sql" / "oauth-source-fingerprint.sql"
RESTART = "tasks/utils/restart.yml"
FILTER = ROLE / "filter_plugins" / "gitea_auth_source_held.py"
LOADER = ROLE / "templates" / "javascript.js.j2"
RENDERER = "roles/sys-front-inj-javascript/templates/profile_lock.js.j2"
ARGS = {
    "ldap_source": ("GITEA_LDAP_AUTH_ARGS", "GITEA_LDAP_SOURCE"),
    "oauth_source": ("GITEA_OIDC_AUTH_ARGS", "GITEA_OAUTH_SOURCE"),
}
NAMES = {
    "ldap_source": "GITEA_LDAP_SOURCE_NAME",
    "oauth_source": "GITEA_OIDC_SOURCE_NAME",
}
LDAP_ROW = [
    "3",
    "2",
    "LDAP",
    "1",
    "ldap",
    "389",
    "0",
    "cn=admin,dc=example,dc=org",
    "ou=users,dc=example,dc=org",
    "(&(objectClass=inetOrgPerson)(uid=%s))",
    "(memberOf=cn=web-app-gitea-administrator,ou=roles,dc=example,dc=org)",
    "(memberOf=cn=web-app-gitea-restricted,ou=roles,dc=example,dc=org)",
    "uid",
    "givenName",
    "sn",
    "mail",
    "sshPublicKey",
    "jpegPhoto",
    "NULL",
    "NULL",
    "NULL",
    "NULL",
    "NULL",
    "NULL",
    "NULL",
]
OAUTH_ROW = [
    "4",
    "6",
    "SSO Login",
    "0",
    *["NULL"] * 14,
    "openidConnect",
    "gitea",
    "https://auth.example.org/realms/main/.well-known/openid-configuration",
    '["openid profile email groups"]',
    "groups",
    "/roles/web-app-gitea/administrator",
    "/roles/web-app-gitea/restricted",
]


def _filter():
    spec = spec_from_file_location("gitea_auth_source_held", FILTER)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gitea_auth_source_held


def _tasks(path) -> list[dict]:
    return DataLoader().load_from_file(str(path), trusted_as_template=True)


def _index(tasks: list[dict], predicate) -> int:
    return next(index for index, task in enumerate(tasks) if predicate(task))


class TestEveryWrittenSettingComesFromItsForm(unittest.TestCase):
    def test_the_cli_arguments_write_exactly_the_declared_fields(self) -> None:
        forms = load_yaml_any(str(FORMS))
        role_vars = load_yaml_str(read_text(str(VARS)))
        for form, (args, sink) in ARGS.items():
            with self.subTest(form=form):
                written = {
                    field
                    for arg in role_vars[args]
                    for field in re.findall(rf"\b{sink}\.(\w+)", arg)
                }
                declared = {
                    field for name, field, _ in iter_fields(forms) if name == form
                }
                self.assertEqual(declared, written)

    def test_no_cli_argument_reads_the_inventory_around_its_form(self) -> None:
        role_vars = load_yaml_str(read_text(str(VARS)))
        for args, _sink in ARGS.values():
            with self.subTest(args=args):
                self.assertEqual(
                    [],
                    [
                        arg
                        for arg in role_vars[args]
                        if re.search(r"LDAP\.|OIDC\.|RBAC\.|lookup\(", arg)
                    ],
                )

    def test_the_record_names_the_source_the_deploy_creates(self) -> None:
        auth = load_yaml_any(str(SERVICES))["gitea"]["auth"]
        role_vars = load_yaml_str(read_text(str(VARS)))
        self.assertEqual([role_vars[NAMES["ldap_source"]]], auth["ldap"]["names"])
        self.assertEqual([role_vars[NAMES["oauth_source"]]], auth["oauth"]["names"])


class TestTheRendererLocksOnlyTheDeploymentsSources(unittest.TestCase):
    def test_each_form_locks_its_fields_on_the_source_the_deploy_created(self) -> None:
        forms = load_yaml_any(str(FORMS))
        services = load_yaml_any(str(SERVICES))
        services["ldap"]["enabled"] = True
        services["gitea"]["login"]["method"]["sso"]["enabled"] = True
        entries = locks("web-app-gitea", forms, {"services": services}, {}, {})
        records = {tuple(entry["record"]["values"]) for entry in entries}
        self.assertEqual({("LDAP",), ("SSO Login",)}, records)
        self.assertEqual(
            sum(1 for _ in iter_fields(forms)),
            len(entries),
        )

    def test_the_loader_includes_the_shared_renderer(self) -> None:
        self.assertIn(RENDERER, read_text(str(LOADER)))
        self.assertIs(True, load_yaml_any(str(SERVICES))["javascript"]["enabled"])


class TestTheDriftReadsWhatGiteaStores(unittest.TestCase):
    def test_the_ldap_source_reads_back_in_the_form_the_deploy_writes(self) -> None:
        held = _filter()([OAUTH_ROW, LDAP_ROW], "ldap_source", "3")
        self.assertEqual(389, held["port"])
        self.assertEqual("unencrypted", held["security_protocol"])
        self.assertIs(True, held["is_sync_enabled"])
        self.assertEqual("ldap", held["host"])
        self.assertEqual(15, len(held))

    def test_only_the_ldap_source_the_deploy_keeps_is_read(self) -> None:
        self.assertEqual({}, _filter()([LDAP_ROW], "ldap_source", "5"))

    def test_the_first_oauth2_source_reads_its_scopes_as_one_string(self) -> None:
        held = _filter()([LDAP_ROW, OAUTH_ROW], "oauth_source", "")
        self.assertEqual("openid profile email groups", held["oauth2_scopes"])
        self.assertEqual("openidConnect", held["oauth2_provider"])
        self.assertEqual(7, len(held))

    def test_a_null_column_is_not_read(self) -> None:
        row = list(LDAP_ROW)
        row[17] = "NULL"
        self.assertNotIn("attribute_avatar", _filter()([row], "ldap_source", "3"))

    def test_an_unknown_form_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            _filter()([LDAP_ROW], "profile", "3")

    def test_the_query_selects_one_column_per_filter_column(self) -> None:
        spec = spec_from_file_location("gitea_auth_source_held", FILTER)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        select = read_text(str(SQL)).split("FROM", 1)[0]
        self.assertEqual(
            len(module.COLUMNS),
            len([line for line in select.splitlines() if line.strip()]),
        )
        self.assertNotRegex(read_text(str(SQL)), r"BindPassword|ClientSecret")


class TestTheDeployReportsBeforeItWrites(unittest.TestCase):
    def test_the_oauth_drift_runs_before_the_oidc_setup(self) -> None:
        oauth = next(
            task for task in _tasks(SETUP) if "setup/oauth_source.yml" in str(task)
        )
        self.assertEqual("GITEA_OIDC_ENABLED | bool", oauth["when"])
        tasks = _tasks(OAUTH_SETUP)
        drift = _index(tasks, lambda task: "setup/drift.yml" in str(task))
        oidc = _index(tasks, lambda task: "setup/oidc.yml" in str(task))
        self.assertLess(drift, oidc)
        self.assertEqual("oauth_source", tasks[drift]["vars"]["gitea_auth_drift_form"])

    def test_the_ldap_drift_reads_the_kept_source_before_the_write(self) -> None:
        tasks = _tasks(LDAP_SETUP)
        plan = _index(tasks, lambda task: "gitea_ldap_source_plan" in str(task))
        drift = _index(tasks, lambda task: "setup/drift.yml" in str(task))
        writes = [
            index
            for index, task in enumerate(tasks)
            if "add-ldap" in str(task) or "update-ldap" in str(task)
        ]
        self.assertLess(plan, drift)
        self.assertLess(drift, min(writes))
        self.assertEqual(
            "{{ ldap_source_plan.keep }}", tasks[drift]["vars"]["gitea_auth_drift_id"]
        )


def _fingerprint(tasks: list[dict], register: str) -> int:
    return _index(
        tasks,
        lambda task: (
            task.get("register") == register
            and FINGERPRINT_SQL.name in str(task.get("database_query", {}))
        ),
    )


def _reloads_after_write(tasks: list[dict]) -> bool:
    loaded = _fingerprint(tasks, "gitea_oauth_source_loaded")
    oidc = _index(tasks, lambda task: "setup/oidc.yml" in str(task))
    stored = _fingerprint(tasks, "gitea_oauth_source_stored")
    restarts = [
        index
        for index, task in enumerate(tasks)
        if RESTART in str(task.get("include_tasks", ""))
    ]
    if not restarts or not loaded < oidc < stored < restarts[0]:
        return False
    gate = " ".join(tasks[restarts[0]].get("when", []))
    return (
        "gitea_oauth_source_stored.rows != gitea_oauth_source_loaded.rows" in gate
        and "gitea_oauth_source_loaded.rows | length > 0" in gate
    )


class TestTheRunningGiteaLoadsTheStoredOAuthSource(unittest.TestCase):
    def test_a_changed_oauth_source_restarts_gitea_after_the_write(self) -> None:
        self.assertTrue(_reloads_after_write(_tasks(OAUTH_SETUP)))

    def test_negative_control_a_write_without_restart_is_caught(self) -> None:
        tasks = [
            task
            for task in _tasks(OAUTH_SETUP)
            if RESTART not in str(task.get("include_tasks", ""))
        ]
        self.assertFalse(_reloads_after_write(tasks))

    def test_the_fingerprint_covers_the_whole_oauth_source_config(self) -> None:
        sql = read_text(str(FINGERPRINT_SQL))
        self.assertIn("SHA2(s.cfg, 256)", sql)
        self.assertRegex(sql, r"WHERE s\.type = 6\b")


if __name__ == "__main__":
    unittest.main()
