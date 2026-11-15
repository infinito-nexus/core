from __future__ import annotations

import copy
import importlib.util
import re
import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

APP = "web-app-gitea"
ROLE_DIR = PROJECT_ROOT / "roles" / APP
PLUGIN = ROLE_DIR / "filter_plugins" / "gitea_workspaces.py"
SERVICES = ROLE_DIR / ROLE_FILE_META_SERVICES
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
SETUP = ROLE_DIR / "tasks" / "02_setup.yml"
MANAGER_OPS = ROLE_DIR / "tasks" / "01_manager_ops.yml"
WORKSPACES_SETUP = ROLE_DIR / "tasks" / "setup" / "workspaces.yml"
CHECK = ROLE_DIR / "tasks" / "utils" / "workspaces" / "check.yml"
STORE_TOKEN_ENTRY = ROLE_DIR / "tasks" / "utils" / "store_token.yml"
STORE_TOKEN = ROLE_DIR / "tasks" / "utils" / "workspaces" / "store_token_rotate.yml"
SNAPSHOT = ROLE_DIR / "tasks" / "utils" / "workspaces" / "snapshot.yml"
SNAPSHOT_SQL = ROLE_DIR / "files" / "sql" / "workspaces-snapshot.sql"

STORE = "store"
ORGANIZATION = "workspaces"
SCOPES = "write:organization,write:repository,read:user"
SWITCH = "GITEA_WORKSPACES_ENABLED | bool"
MASKED = "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"
TOKEN_REFERENCE = re.compile(r"\bgitea_store_token(?:_mint)?\b")

_spec = importlib.util.spec_from_file_location("gitea_workspaces", PLUGIN)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {PLUGIN}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _row(kind, a="", b="", c="", d="", e="", f=""):
    return [kind, a, b, c, d, e, f]


def _healthy_rows():
    return [
        _row("account", STORE, "4", "0", "0", "0", "0"),
        _row("organization", ORGANIZATION, "2"),
        _row("membership", ORGANIZATION),
        _row("team_membership", ORGANIZATION, "owners"),
        _row("team", "owners", "4", "1", "1"),
        _row("team", "ws-a", "1", "0", "0"),
        _row("team_unit", "ws-a", "1", "1"),
        _row("team_unit", "ws-a", "2", "0"),
        _row("team_unit", "ws-a", "3", "0"),
        _row("team_member", "owners", STORE),
        _row("team_member", "ws-a", "viewer"),
        _row("team_member", "ws-a", "owner"),
        _row("repository", "ws-a"),
        _row("deploy_key", "ws-a", "store", "2"),
        _row("deploy_key", "ws-a", "semaphore", "1"),
    ]


def _findings(rows):
    snapshot = _mod.gitea_workspaces_snapshot(rows)
    return _mod.gitea_workspaces_findings(snapshot, STORE, ORGANIZATION)


def _replace(rows, kind, a, b, **cells):
    out = copy.deepcopy(rows)
    index = {"c": 3, "d": 4, "e": 5, "f": 6}
    for row in out:
        if row[0] == kind and row[1] == a and row[2] == b:
            for key, value in cells.items():
                row[index[key]] = value
    return out


def _swap(rows, kind, a, replacement):
    return [replacement if row[:2] == [kind, a] else row for row in rows]


def _tasks(path):
    return load_yaml_str(read_text(str(path))) or []


def _flat(tasks):
    flat = []
    for task in tasks:
        flat.append(task)
        for section in ("block", "always", "rescue"):
            flat.extend(_flat(task.get(section, [])))
    return flat


def _include_gate(tasks, target):
    for task in tasks:
        include = task.get("include_tasks") or task.get("ansible.builtin.include_tasks")
        if include == target:
            return task.get("when")
    return None


def _shell(task):
    return str(task.get("ansible.builtin.shell") or task.get("shell") or "")


def _argv_leaks(tasks):
    return [
        task.get("name")
        for task in tasks
        if TOKEN_REFERENCE.search(_shell(task))
        or TOKEN_REFERENCE.search(str(task.get("args", "")))
    ]


def _mint_is_masked_and_raw(tasks):
    mints = [task for task in tasks if "generate-access-token" in _shell(task)]
    return (
        len(mints) == 1
        and "--raw" in _shell(mints[0])
        and mints[0].get("no_log") == MASKED
    )


def _fact_comes_from_stdout(tasks):
    facts = [
        task["ansible.builtin.set_fact"]
        for task in tasks
        if "ansible.builtin.set_fact" in task
    ]
    token = [
        fact["gitea_store_token"]["token"]
        for fact in facts
        if "gitea_store_token" in fact
    ]
    return token == ["{{ gitea_store_token_mint.stdout_lines | last | trim }}"]


class TestWorkspaceSwitch(unittest.TestCase):
    def test_the_workspace_organization_follows_its_switch(self):
        services = load_yaml_str(read_text(str(SERVICES)))
        workspaces = services["gitea"]["workspaces"]
        self.assertIs(workspaces["enabled"], False)
        self.assertEqual(workspaces["organization"], ORGANIZATION)
        self.assertEqual(workspaces["store"]["username"], STORE)
        self.assertEqual(workspaces["store"]["scopes"], SCOPES)
        variables = load_yaml_str(read_text(str(VARS)))
        self.assertIn(
            "'services.gitea.workspaces.enabled'", variables["GITEA_WORKSPACES_ENABLED"]
        )
        self.assertEqual(_include_gate(_tasks(SETUP), "setup/workspaces.yml"), SWITCH)
        self.assertEqual(
            _include_gate(_tasks(MANAGER_OPS), "utils/workspaces/check.yml"), SWITCH
        )

    def test_negative_control_an_ungated_setup_is_caught(self):
        tasks = copy.deepcopy(_tasks(SETUP))
        for task in tasks:
            if task.get("include_tasks") == "setup/workspaces.yml":
                task.pop("when")
        self.assertNotEqual(_include_gate(tasks, "setup/workspaces.yml"), SWITCH)

    def test_a_fresh_instance_gets_organization_and_store_account(self):
        plan = _mod.gitea_workspaces_plan(_mod.gitea_workspaces_snapshot([]), STORE)
        self.assertTrue(plan["create_account"])
        self.assertTrue(plan["create_organization"])
        self.assertEqual(plan["refuse"], [])

    def test_a_second_deploy_changes_nothing(self):
        plan = _mod.gitea_workspaces_plan(
            _mod.gitea_workspaces_snapshot(_healthy_rows()), STORE
        )
        self.assertEqual(
            plan,
            {
                "create_account": False,
                "refuse": [],
                "align_account": False,
                "create_organization": False,
                "privatize_organization": False,
            },
        )

    def test_a_new_bot_account_is_aligned_to_a_repository_limit_of_zero(self):
        rows = _replace(_healthy_rows(), "account", STORE, "4", d="-1")
        plan = _mod.gitea_workspaces_plan(_mod.gitea_workspaces_snapshot(rows), STORE)
        self.assertTrue(plan["align_account"])

    def test_an_account_the_deploy_did_not_create_is_refused(self):
        rows = _swap(
            _healthy_rows(),
            "account",
            STORE,
            _row("account", STORE, "0", "0", "0", "6", "1"),
        )
        plan = _mod.gitea_workspaces_plan(_mod.gitea_workspaces_snapshot(rows), STORE)
        self.assertEqual(len(plan["refuse"]), 2)

    def test_every_change_of_the_setup_is_gated_by_the_plan(self):
        for task in _tasks(WORKSPACES_SETUP):
            name = task["name"]
            with self.subTest(task=name):
                if (
                    "Read the workspace organization before" in name
                    or "Plan the remaining" in name
                ):
                    continue
                self.assertTrue(task.get("when"), f"{name} runs on every deploy")


class TestStoreToken(unittest.TestCase):
    def test_the_token_never_reaches_an_argv(self):
        tasks = _flat(_tasks(STORE_TOKEN))
        self.assertTrue(_mint_is_masked_and_raw(tasks))
        self.assertTrue(_fact_comes_from_stdout(tasks))
        self.assertEqual(_argv_leaks(tasks), [])
        mint = next(task for task in tasks if "generate-access-token" in _shell(task))
        self.assertIn(
            "--scopes {{ GITEA_WORKSPACES_STORE_SCOPES | quote }}", _shell(mint)
        )
        self.assertNotIn("stdin", mint.get("args", {}))

    def test_the_entry_rotates_on_the_stack_host_only(self):
        self.assertEqual(
            _include_gate(
                _tasks(STORE_TOKEN_ENTRY), "utils/workspaces/store_token_rotate.yml"
            ),
            "IS_STACK_HOST | bool",
        )

    def test_negative_control_a_token_on_an_argv_is_caught(self):
        tasks = copy.deepcopy(_flat(_tasks(STORE_TOKEN)))
        tasks.append(
            {
                "name": "planted",
                "ansible.builtin.shell": "curl -H 'Authorization: token {{ gitea_store_token.token }}' x",
            }
        )
        self.assertEqual(_argv_leaks(tasks), ["planted"])

    def test_negative_control_an_unmasked_mint_is_caught(self):
        tasks = copy.deepcopy(_flat(_tasks(STORE_TOKEN)))
        for task in tasks:
            if "generate-access-token" in _shell(task):
                task.pop("no_log")
        self.assertFalse(_mint_is_masked_and_raw(tasks))

    def test_the_token_is_named_after_its_expires_at(self):
        self.assertEqual(
            _mod.gitea_store_token_name("store-", "2026-11-27T09:00:00+00:00"),
            "store-2026-11-27T09:00:00+00:00",
        )
        for value in (
            "2026-11-27T09:00:00Z",
            "2026-11-27T09:00:00",
            "2026-11-27",
            "soon",
        ):
            with self.subTest(value=value), self.assertRaises(AnsibleFilterError):
                _mod.gitea_store_token_name("store-", value)

    def test_only_store_tokens_past_their_expires_at_are_revoked(self):
        tokens = [
            {"id": 1, "name": "store-2026-11-13T09:00:00+00:00"},
            {"id": 2, "name": "store-2026-11-27T09:00:00+00:00"},
            {"id": 3, "name": "gitea-mcp"},
            {"id": 4, "name": "store-2026-11-01T09:00:00"},
            {"id": 5, "name": "store-manual"},
            {"id": 6, "name": "store-2026-11-14T10:00:00+02:00"},
        ]
        self.assertEqual(
            _mod.gitea_store_tokens_expired(
                tokens, "store-", "2026-11-14T09:00:00+00:00"
            ),
            [1, 6],
        )

    def test_a_run_time_without_an_offset_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            _mod.gitea_store_tokens_expired([], "store-", "2026-11-14T09:00:00")


class TestWorkspaceCheck(unittest.TestCase):
    def test_the_workspace_check_catches_each_widening(self):
        self.assertEqual(_findings(_healthy_rows()), [])
        controls = {
            "store as site admin": (
                _replace(_healthy_rows(), "account", STORE, "4", c="1"),
                "account 'store' is a site admin",
            ),
            "a team with write": (
                _swap(
                    _healthy_rows(), "team", "ws-a", _row("team", "ws-a", "2", "0", "0")
                ),
                "team 'workspaces/ws-a' holds 'write'",
            ),
            "a team with repo.issues": (
                _replace(_healthy_rows(), "team_unit", "ws-a", "2", c="1"),
                "team 'workspaces/ws-a' holds unit 'repo.issues'",
            ),
            "a team with all repositories": (
                _replace(_healthy_rows(), "team", "ws-a", "1", c="1"),
                "team 'workspaces/ws-a' reaches all repositories",
            ),
            "a third deploy key": (
                [*_healthy_rows(), _row("deploy_key", "ws-a", "extra", "1")],
                "repository 'workspaces/ws-a' holds 3 deploy keys",
            ),
            "a second writing key": (
                _replace(_healthy_rows(), "deploy_key", "ws-a", "semaphore", c="2"),
                "repository 'workspaces/ws-a' holds 2 writing deploy keys",
            ),
            "a collaborator": (
                [*_healthy_rows(), _row("collaborator", "ws-a", "mallory", "2")],
                "repository 'workspaces/ws-a' has collaborator 'mallory'",
            ),
        }
        for label, (rows, finding) in controls.items():
            with self.subTest(control=label):
                self.assertEqual(_findings(rows), [finding])

    def test_the_check_names_each_further_widening(self):
        controls = {
            "a team that creates repositories": (
                _replace(_healthy_rows(), "team", "ws-a", "1", d="1"),
                "team 'workspaces/ws-a' may create repositories",
            ),
            "write on the code unit": (
                _replace(_healthy_rows(), "team_unit", "ws-a", "1", c="2"),
                "team 'workspaces/ws-a' holds 'write' on 'repo.code'",
            ),
            "a second owner": (
                [*_healthy_rows(), _row("team_member", "owners", "administrator")],
                "team 'workspaces/owners' holds member 'administrator'",
            ),
            "another organization": (
                [*_healthy_rows(), _row("membership", "other")],
                "account 'store' belongs to organization 'other'",
            ),
            "another team": (
                [*_healthy_rows(), _row("team_membership", ORGANIZATION, "ws-a")],
                "account 'store' belongs to team 'workspaces/ws-a'",
            ),
            "an own repository": (
                [*_healthy_rows(), _row("owned_repository", "mine")],
                "account 'store' owns repository 'store/mine'",
            ),
            "an own repository limit": (
                _replace(_healthy_rows(), "account", STORE, "4", d="-1"),
                "account 'store' may create -1 repositories of its own",
            ),
            "a public organization": (
                _swap(
                    _healthy_rows(),
                    "organization",
                    ORGANIZATION,
                    _row("organization", ORGANIZATION, "0"),
                ),
                "organization 'workspaces' is not private",
            ),
        }
        for label, (rows, finding) in controls.items():
            with self.subTest(control=label):
                self.assertEqual(_findings(rows), [finding])

    def test_an_sso_account_named_store_is_caught(self):
        rows = _swap(
            _healthy_rows(),
            "account",
            STORE,
            _row("account", STORE, "0", "0", "0", "6", "1"),
        )
        self.assertEqual(
            _findings(rows),
            [
                "account 'store' is not the bot account the deploy creates",
                "account 'store' signs in through an external source",
            ],
        )

    def test_a_missing_organization_and_account_are_named(self):
        self.assertEqual(
            _findings([]),
            ["account 'store' is missing", "organization 'workspaces' is missing"],
        )

    def test_an_unknown_row_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            _mod.gitea_workspaces_snapshot([_row("unknown")])

    def test_a_null_grant_is_refused_rather_than_read_as_none(self):
        rows = _swap(
            _healthy_rows(), "team", "ws-a", _row("team", "ws-a", "", "0", "0")
        )
        with self.assertRaises(AnsibleFilterError):
            _mod.gitea_workspaces_snapshot(rows)

    def test_the_query_and_the_snapshot_name_the_same_kinds(self):
        sql = read_text(str(SNAPSHOT_SQL))
        kinds = set(re.findall(r"^\s*'([a-z_]+)'", sql, re.MULTILINE))
        self.assertEqual(kinds, set(_mod.READERS))
        self.assertEqual(sql.count("UNION ALL") + 1, len(_mod.READERS))

    def test_the_snapshot_keeps_the_names_it_filters_by(self):
        query = _tasks(SNAPSHOT)[0]
        self.assertIs(query["database_query"]["mask_values"], False)
        self.assertEqual(query["no_log"], MASKED)

    def test_the_check_fails_the_deploy_on_any_finding(self):
        tasks = _tasks(CHECK)
        assertion = next(task for task in tasks if "ansible.builtin.assert" in task)
        self.assertEqual(
            assertion["ansible.builtin.assert"]["that"],
            ["gitea_workspaces_findings | length == 0"],
        )
        self.assertIn(
            "gitea_workspaces_findings(", assertion["vars"]["gitea_workspaces_findings"]
        )


if __name__ == "__main__":
    unittest.main()
