from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, iter_project_files
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

from .templates.test_realm_import_json import render

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
UPDATE = ROLE_DIR / "tasks/update"
ROUTINES = ROLE_DIR / "tasks/03_manager_ops/update_routines.yml"
ENABLED = UPDATE / "18_usage_client/enabled.yml"
DISABLED = UPDATE / "18_usage_client/disabled.yml"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
ROLES = ROLE_VARS["KEYCLOAK_USAGE_CLIENT_ROLES"]
REALM = "example.com"
CLIENT_ID = "usage"
SERVICE_ACCOUNT = f"service-account-{CLIENT_ID}"
KCADM = "kcadm.sh"
VIEW_USERS = "view-users"
COMMAND_MODULES = {
    "ansible.builtin.shell",
    "shell",
    "ansible.builtin.command",
    "command",
    "ansible.builtin.raw",
    "raw",
    "ansible.builtin.script",
    "script",
}
MODULE_COMMAND_PARAMS = {
    "keycloak_kcadm_update": ("kcadm_exec", "cid_resolve_cmd", "current_cid")
}
STDIN_PARAMS = {"stdin", "stdin_add_newline"}
CREDENTIAL = (
    r"\bKEYCLOAK_USAGE_CLIENT(?:_SECRET)?\b",
    r"\busage_client_secret\b",
)
PLANTED = [
    {
        "name": "secret on the command line",
        "ansible.builtin.shell": "{{ KEYCLOAK_EXEC_KCADM }} update clients/x -s secret={{ KEYCLOAK_USAGE_CLIENT_SECRET }}",
    },
    {
        "name": "credential in the environment",
        "ansible.builtin.shell": f"{KCADM} config credentials",
        "environment": {"KC_CLIENT_SECRET": "{{ KEYCLOAK_USAGE_CLIENT_SECRET }}"},
    },
    {
        "name": "client on stdin",
        "ansible.builtin.shell": {
            "cmd": "{{ KEYCLOAK_EXEC_KCADM }} create clients -f -",
            "stdin": "{{ KEYCLOAK_USAGE_CLIENT | to_json }}",
        },
    },
]
PLANTED_ON_A_COMMAND_LINE = [
    "secret on the command line",
    "credential in the environment",
]


def kcadm_filters() -> dict:
    spec = importlib.util.spec_from_file_location(
        "keycloak_kcadm_filters", ROLE_DIR / "filter_plugins/kcadm.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


ENV = Environment(
    undefined=StrictUndefined, autoescape=select_autoescape(default_for_string=False)
)
ENV.filters["bool"] = bool
ENV.filters["quote"] = shlex.quote
ENV.filters["difference"] = lambda left, right: [x for x in left if x not in right]
ENV.filters.update(kcadm_filters())


def evaluate(expression: str, **context):
    """Evaluate one ``{{ ... }}`` expression or bare condition.

    Args:
        expression: the expression, with or without its braces.
        context: the variables it reads.
    """
    bare = str(expression).strip().removeprefix("{{").removesuffix("}}")
    return ENV.compile_expression(bare)(**context)


def holds(when, **context) -> bool:
    """Evaluate a task's ``when``, a list of conditions joined by ``and``.

    Args:
        when: one condition or a list of them.
        context: the variables the conditions read.
    """
    conditions = when if isinstance(when, list) else [when]
    return all(evaluate(condition, **context) for condition in conditions)


def argv(command: str, **context) -> list[str]:
    """Render a shell task's command and split it the way the shell does.

    Args:
        command: the task's command template.
        context: the variables it reads.
    """
    return shlex.split(ENV.from_string(command).render(**context))


def command_texts(task: dict) -> list[str]:
    """Return every text of ``task`` that ends up on a command line or in its environment.

    Args:
        task: one task of a task file.
    """
    texts = []
    for module, params in task.items():
        if module in COMMAND_MODULES:
            if isinstance(params, dict):
                texts += [
                    json.dumps(v, default=str)
                    for k, v in params.items()
                    if k not in STDIN_PARAMS
                ]
            elif params is not None:
                texts.append(str(params))
        if isinstance(params, dict):
            texts += [
                str(params[k])
                for k in MODULE_COMMAND_PARAMS.get(module, ())
                if k in params
            ]
    if task.get("environment"):
        texts.append(json.dumps(task["environment"], default=str))
    return texts


def credential_findings(root: Path, files: list[Path]) -> list[str]:
    """
    Args:
        root: a tree of task files, such as ``tasks/update``.
        files: the task files below ``root`` to scan.

    Returns:
        ``<file>: <task name>`` of every task whose command text carries the
        usage client credential.
    """
    return [
        f"{path.relative_to(root).as_posix()}: {inner.get('name')}"
        for path in sorted(files)
        for task in load_yaml_any(str(path)) or []
        for inner in [task, *(task.get("block") or [])]
        if any(
            re.search(pattern, text)
            for text in command_texts(inner)
            for pattern in CREDENTIAL
        )
    ]


def update_files(root: Path) -> list[Path]:
    """
    Args:
        root: where the files of ``tasks/update`` sit, the role's own or a copy.

    Returns:
        Every task file of ``tasks/update``, below ``root``.
    """
    update = f"{UPDATE}{os.sep}"
    return [
        root / Path(path).relative_to(UPDATE)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(update)
    ]


def include(tasks: list[dict], file_name: str) -> dict:
    """
    Args:
        tasks: the update routines.
        file_name: the routine's file name below ``18_usage_client``.

    Returns:
        The include task of ``tasks`` that loads that usage client routine.
    """
    return next(
        task
        for task in tasks
        if str(task.get("include_tasks", "")).endswith(f"18_usage_client/{file_name}")
    )


def role_findings(roles: list[str], realm: dict) -> list[str]:
    """
    Args:
        roles: the realm-management roles the role grants the usage client.
        realm: the rendered realm import with the switch on.

    Returns:
        Every grant beside ``view-users``, in the role's list and on the
        imported service account.
    """
    findings = [f"the role grants {name}" for name in roles if name != VIEW_USERS]
    if VIEW_USERS not in roles:
        findings.append(f"the role does not grant {VIEW_USERS}")
    (account,) = [
        user
        for user in realm["users"]
        if user.get("serviceAccountClientId") == CLIENT_ID
    ]
    imported = account.get("clientRoles", {})
    if imported != {"realm-management": [VIEW_USERS]}:
        findings.append(f"the import grants {imported}")
    return findings


def rendered_realm(enabled: bool, roles: list[str]) -> dict:
    """
    Args:
        enabled: the usage client switch.
        roles: ``KEYCLOAK_USAGE_CLIENT_ROLES`` the import renders.

    Returns:
        The parsed realm import.
    """
    return json.loads(
        render(
            [],
            overrides={
                "KEYCLOAK_USAGE_CLIENT_ENABLED": enabled,
                "KEYCLOAK_USAGE_CLIENT_ROLES": roles,
            },
        )
    )


class TestUsageClientRealmImport(unittest.TestCase):
    def test_the_usage_client_holds_view_users_only(self) -> None:
        realm = rendered_realm(True, ROLES)
        self.assertEqual(role_findings(ROLES, realm), [])
        (client,) = [c for c in realm["clients"] if c["clientId"] == CLIENT_ID]
        self.assertEqual(
            (
                client["publicClient"],
                client["serviceAccountsEnabled"],
                client["standardFlowEnabled"],
                client["directAccessGrantsEnabled"],
                client["implicitFlowEnabled"],
            ),
            (False, True, False, False, False),
        )

    def test_negative_control_a_usage_client_that_manages_users_fails(self) -> None:
        roles = [*ROLES, "manage-users"]
        self.assertEqual(
            role_findings(roles, rendered_realm(True, roles)),
            [
                "the role grants manage-users",
                "the import grants {'realm-management': ['view-users', 'manage-users']}",
            ],
        )

    def test_the_switch_off_imports_neither_client_nor_service_account(self) -> None:
        realm = rendered_realm(False, ROLES)
        self.assertEqual(
            [c for c in realm["clients"] if c["clientId"] == CLIENT_ID], []
        )
        self.assertEqual(
            [u for u in realm["users"] if u.get("serviceAccountClientId") == CLIENT_ID],
            [],
        )

    def test_services_ship_the_switch_off(self) -> None:
        services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        self.assertIs(services["keycloak"]["usage_client"]["enabled"], False)


class TestUsageClientCredentialStaysOffTheCommandLine(unittest.TestCase):
    def test_no_update_task_puts_the_credential_on_a_command_line(self) -> None:
        self.assertEqual(credential_findings(UPDATE, update_files(UPDATE)), [])

    def test_the_scan_catches_every_planted_command_line_and_only_those(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "update"
            shutil.copytree(UPDATE, root)
            planted = root / "99_planted.yml"
            dump_yaml(planted, PLANTED)
            self.assertEqual(
                credential_findings(root, [*update_files(root), planted]),
                [f"99_planted.yml: {name}" for name in PLANTED_ON_A_COMMAND_LINE],
            )


class TestUsageClientRoutines(unittest.TestCase):
    def setUp(self) -> None:
        self.routines = load_yaml_any(str(ROUTINES))

    def test_exactly_one_usage_routine_runs_per_switch_state(self) -> None:
        for enabled, expected in ((True, ["enabled.yml"]), (False, ["disabled.yml"])):
            with self.subTest(enabled=enabled):
                ran = [
                    name
                    for name in ("enabled.yml", "disabled.yml")
                    if holds(
                        include(self.routines, name)["when"],
                        KEYCLOAK_USAGE_CLIENT_ENABLED=enabled,
                    )
                ]
                self.assertEqual(ran, expected)

    def test_both_routines_resolve_to_their_files(self) -> None:
        for name, path in (("enabled.yml", ENABLED), ("disabled.yml", DISABLED)):
            with self.subTest(routine=name):
                target = include(self.routines, name)["include_tasks"]
                self.assertEqual(
                    Path(target.replace("{{ role_path }}", str(ROLE_DIR))), path
                )
                self.assertTrue(path.is_file())


class TestUsageClientEnabled(unittest.TestCase):
    def setUp(self) -> None:
        self.upsert, self.read, self.converge = load_yaml_any(str(ENABLED))
        self.grant, self.revoke = self.converge["block"]
        self.context = {
            "KEYCLOAK_EXEC_KCADM": KCADM,
            "KEYCLOAK_REALM": REALM,
            "KEYCLOAK_USAGE_SERVICE_ACCOUNT": SERVICE_ACCOUNT,
            "KEYCLOAK_CONSOLE_ROLE_CLIENT": ROLE_VARS["KEYCLOAK_CONSOLE_ROLE_CLIENT"],
            "KEYCLOAK_USAGE_CLIENT_ROLES": ROLES,
        }

    def plan(self, held: list[str]) -> dict:
        """
        Args:
            held: realm-management roles the live service account holds.

        Returns:
            The context with the block vars resolved for that account.
        """
        stdout = "Logging into the server\n" + json.dumps(
            [{"name": name} for name in held]
        )
        context = {**self.context, "kc_usage_roles": {"stdout": stdout}}
        block_vars = self.converge["vars"]
        context["kc_usage_held"] = evaluate(block_vars["kc_usage_held"], **context)
        for name in ("kc_usage_grant", "kc_usage_revoke"):
            context[name] = evaluate(block_vars[name], **context)
        return context

    def test_the_client_reaches_kcadm_only_through_the_stdin_module(self) -> None:
        params = self.upsert["keycloak_kcadm_update"]
        self.assertEqual(params["object_kind"], "client")
        self.assertEqual(params["lookup_value"], "{{ KEYCLOAK_USAGE_CLIENT_ID }}")
        self.assertEqual(params["desired"], "{{ KEYCLOAK_USAGE_CLIENT }}")
        self.assertEqual(self.upsert["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")

    def test_the_upserted_client_is_the_one_of_the_realm_import(self) -> None:
        usage = {"clientId": CLIENT_ID, "secret": "s"}
        realm = {"clients": [{"clientId": REALM}, usage]}
        self.assertEqual(
            evaluate(
                ROLE_VARS["KEYCLOAK_USAGE_CLIENT"],
                KEYCLOAK_DICTIONARY_REALM=realm,
                KEYCLOAK_USAGE_CLIENT_ID=CLIENT_ID,
            ),
            usage,
        )

    def test_only_a_created_client_reports_a_change(self) -> None:
        for exists, changed in ((False, True), (True, False)):
            with self.subTest(exists=exists):
                self.assertIs(
                    evaluate(
                        self.upsert["changed_when"],
                        kc_usage_client={"object_exists": exists},
                    ),
                    changed,
                )

    def test_a_fresh_service_account_gets_view_users_only(self) -> None:
        context = self.plan([])
        self.assertTrue(holds(self.grant["when"], **context))
        self.assertFalse(holds(self.revoke["when"], **context))
        self.assertEqual(
            argv(self.grant["ansible.builtin.shell"], **context),
            [
                KCADM,
                "add-roles",
                "-r",
                REALM,
                "--uusername",
                SERVICE_ACCOUNT,
                "--cclientid",
                "realm-management",
                "--rolename",
                VIEW_USERS,
            ],
        )

    def test_a_second_deploy_changes_nothing(self) -> None:
        context = self.plan(list(ROLES))
        self.assertFalse(holds(self.grant["when"], **context))
        self.assertFalse(holds(self.revoke["when"], **context))

    def test_a_service_account_that_manages_users_loses_it(self) -> None:
        context = self.plan([VIEW_USERS, "manage-users", "query-users"])
        self.assertEqual(context["kc_usage_grant"], [])
        self.assertEqual(context["kc_usage_revoke"], ["manage-users", "query-users"])
        self.assertEqual(
            argv(self.revoke["ansible.builtin.shell"], **context)[-4:],
            ["--rolename", "manage-users", "--rolename", "query-users"],
        )


class TestUsageClientDisabled(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup, self.delete = load_yaml_any(str(DISABLED))
        self.context = {
            "KEYCLOAK_EXEC_KCADM": KCADM,
            "KEYCLOAK_REALM": REALM,
            "KEYCLOAK_USAGE_CLIENT_ID": CLIENT_ID,
        }

    def test_the_lookup_asks_for_the_usage_client_only(self) -> None:
        self.assertEqual(
            argv(self.lookup["ansible.builtin.shell"], **self.context),
            [
                KCADM,
                "get",
                "clients",
                "-r",
                REALM,
                "-q",
                f"clientId={CLIENT_ID}",
                "--fields",
                "id",
                "--format",
                "json",
            ],
        )
        self.assertIs(self.lookup["changed_when"], False)

    def test_the_switch_off_deletes_every_client_the_lookup_found(self) -> None:
        for stdout, ids in (("[]", []), ('[{"id": "c1"}]', ["c1"])):
            with self.subTest(stdout=stdout):
                found = evaluate(
                    self.delete["loop"], kc_usage_client_found={"stdout": stdout}
                )
                self.assertEqual([item["id"] for item in found], ids)
        self.assertEqual(
            argv(
                self.delete["ansible.builtin.shell"], **self.context, item={"id": "c1"}
            ),
            [KCADM, "delete", "clients/c1", "-r", REALM],
        )


class TestUsageClientVariants(unittest.TestCase):
    def test_only_variant_zero_turns_the_switch_on(self) -> None:
        variants = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_VARIANTS))
        switches = [
            variant["services"]["keycloak"].get("usage_client", {}).get("enabled")
            for variant in variants
        ]
        self.assertEqual(switches, [True] + [None] * (len(variants) - 1))


if __name__ == "__main__":
    unittest.main()
