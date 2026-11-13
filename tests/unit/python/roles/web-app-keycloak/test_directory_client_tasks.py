from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS, ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
UPDATE = ROLE_DIR / "tasks/update"
ROUTINES = ROLE_DIR / "tasks/03_manager_ops/update_routines.yml"
ENABLED = UPDATE / "17_directory_client/enabled.yml"
DISABLED = UPDATE / "17_directory_client/disabled.yml"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
ROLES = ROLE_VARS["KEYCLOAK_DIRECTORY_CLIENT_ROLES"]
REALM = "example.com"
CLIENT_ID = f"{REALM}-directory"
SERVICE_ACCOUNT = f"service-account-{CLIENT_ID}"
KCADM = "kcadm.sh"
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
    r"\bKEYCLOAK_DIRECTORY_CLIENT(?:_SECRET)?\b",
    r"\bdirectory_client_secret\b",
)
PLANTED = [
    {
        "name": "secret on the command line",
        "ansible.builtin.shell": "{{ KEYCLOAK_EXEC_KCADM }} update clients/x -s secret={{ KEYCLOAK_DIRECTORY_CLIENT_SECRET }}",
    },
    {
        "name": "client on argv",
        "ansible.builtin.command": {
            "argv": [
                KCADM,
                "create",
                "clients",
                "-b",
                "{{ KEYCLOAK_DIRECTORY_CLIENT | to_json }}",
            ]
        },
    },
    {
        "name": "credential through task vars",
        "vars": {
            "kc_planted_secret": "{{ lookup('config', application_id, 'secrets.credentials.directory_client_secret') }}"
        },
        "ansible.builtin.shell": f"{KCADM} update clients/x -s secret={{{{ kc_planted_secret }}}}",
    },
    {
        "name": "plant a fact",
        "ansible.builtin.set_fact": {
            "kc_planted_fact": "{{ KEYCLOAK_DIRECTORY_CLIENT.secret }}"
        },
    },
    {
        "name": "credential through a fact",
        "ansible.builtin.shell": f"{KCADM} update clients/x -s secret={{{{ kc_planted_fact }}}}",
    },
    {
        "name": "plant a result",
        "keycloak_kcadm_update": {
            "object_kind": "client",
            "lookup_value": "x",
            "desired": "{{ KEYCLOAK_DIRECTORY_CLIENT }}",
            "kcadm_exec": KCADM,
            "realm": REALM,
        },
        "register": "kc_planted_result",
    },
    {
        "name": "credential through a result",
        "block": [
            {
                "name": "nested credential through a result",
                "ansible.builtin.shell": f"{KCADM} update clients/x -s secret={{{{ kc_planted_result.result.secret }}}}",
            }
        ],
    },
    {
        "name": "credential in the environment",
        "ansible.builtin.shell": f"{KCADM} config credentials",
        "environment": {"KC_CLIENT_SECRET": "{{ KEYCLOAK_DIRECTORY_CLIENT_SECRET }}"},
    },
    {
        "name": "client on stdin",
        "ansible.builtin.shell": {
            "cmd": "{{ KEYCLOAK_EXEC_KCADM }} create clients -f -",
            "stdin": "{{ KEYCLOAK_DIRECTORY_CLIENT | to_json }}",
        },
    },
    {
        "name": "client on stdin through args",
        "ansible.builtin.shell": "{{ KEYCLOAK_EXEC_KCADM }} create clients -f -",
        "args": {"stdin": "{{ KEYCLOAK_DIRECTORY_CLIENT | to_json }}"},
    },
    {
        "name": "client in a payload file",
        "ansible.builtin.copy": {
            "content": "{{ KEYCLOAK_DIRECTORY_CLIENT | to_json }}",
            "dest": "/tmp/directory-client.json",
            "mode": "0600",
        },
    },
    {
        "name": "payload file to kcadm",
        "ansible.builtin.shell": "{{ KEYCLOAK_EXEC_KCADM }} create clients -f /tmp/directory-client.json",
    },
]
PLANTED_ON_A_COMMAND_LINE = [
    "secret on the command line",
    "client on argv",
    "credential through task vars",
    "credential through a fact",
    "nested credential through a result",
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


def carries(text: str, tainted: set[str]) -> bool:
    """Whether ``text`` names the credential or a variable that holds it.

    Args:
        text: command text of a task.
        tainted: variables known to hold the credential.
    """
    names = (rf"\b{re.escape(name)}\b" for name in tainted)
    return any(re.search(pattern, text) for pattern in (*CREDENTIAL, *names))


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
            texts += [
                json.dumps(v, default=str)
                for k, v in (task.get("args") or {}).items()
                if k not in STDIN_PARAMS
            ]
        if isinstance(params, dict):
            texts += [
                str(params[k])
                for k in MODULE_COMMAND_PARAMS.get(module, ())
                if k in params
            ]
    if task.get("environment"):
        texts.append(json.dumps(task["environment"], default=str))
    return texts


def walk(
    tasks, scoped: set[str], facts: set[str], where: str, findings: list[str]
) -> None:
    """Collect the tasks whose command text carries the credential.

    Args:
        tasks: a task list.
        scoped: tainted variables of the enclosing ``vars``.
        facts: tainted facts and registered results, shared by the whole file.
        where: the task file the list belongs to.
        findings: receives ``<file>: <task name>`` per finding.
    """
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        local = scoped | {
            name
            for name, value in (task.get("vars") or {}).items()
            if carries(json.dumps(value, default=str), scoped | facts)
        }
        loop = task.get("loop", task.get("with_items"))
        if loop is not None and carries(json.dumps(loop, default=str), local | facts):
            local = local | {(task.get("loop_control") or {}).get("loop_var", "item")}
        if any(carries(text, local | facts) for text in command_texts(task)):
            findings.append(f"{where}: {task.get('name')}")
        for section in ("block", "rescue", "always"):
            walk(task.get(section), local, facts, where, findings)
        fact_params = task.get("ansible.builtin.set_fact", task.get("set_fact"))
        if isinstance(fact_params, dict):
            facts |= {
                name
                for name, value in fact_params.items()
                if carries(json.dumps(value, default=str), local | facts)
            }
        if task.get("register") and carries(
            json.dumps(task, default=str), local | facts
        ):
            facts.add(task["register"])


def credential_findings(root: Path) -> list[str]:
    """Return the tasks below ``root`` whose command text carries the directory client credential.

    Args:
        root: a tree of task files, such as ``tasks/update``.
    """
    findings: list[str] = []
    for path in sorted(root.rglob("*.yml")):
        walk(
            load_yaml_any(str(path)),
            set(),
            set(),
            path.relative_to(root).as_posix(),
            findings,
        )
    return findings


def include(tasks: list[dict], file_name: str) -> dict:
    """Return the include task of ``tasks`` that loads a directory client routine.

    Args:
        tasks: the update routines.
        file_name: the routine's file name below ``17_directory_client``.
    """
    return next(
        task
        for task in tasks
        if str(task.get("include_tasks", "")).endswith(
            f"17_directory_client/{file_name}"
        )
    )


class TestDirectoryClientCredentialStaysOffTheCommandLine(unittest.TestCase):
    def test_no_update_task_puts_the_credential_on_a_command_line(self) -> None:
        self.assertEqual(credential_findings(UPDATE), [])

    def test_the_scan_catches_every_planted_command_line_and_only_those(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "update"
            shutil.copytree(UPDATE, root)
            dump_yaml(root / "99_planted.yml", PLANTED)
            self.assertEqual(
                credential_findings(root),
                [f"99_planted.yml: {name}" for name in PLANTED_ON_A_COMMAND_LINE],
            )


class TestDirectoryClientRoutines(unittest.TestCase):
    def setUp(self) -> None:
        self.routines = load_yaml_any(str(ROUTINES))

    def test_exactly_one_directory_routine_runs_per_switch_state(self) -> None:
        for enabled, expected in ((True, ["enabled.yml"]), (False, ["disabled.yml"])):
            with self.subTest(enabled=enabled):
                ran = [
                    name
                    for name in ("enabled.yml", "disabled.yml")
                    if holds(
                        include(self.routines, name)["when"],
                        KEYCLOAK_DIRECTORY_CLIENT_ENABLED=enabled,
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


class TestDirectoryClientEnabled(unittest.TestCase):
    def setUp(self) -> None:
        self.upsert, self.read, self.converge = load_yaml_any(str(ENABLED))
        self.grant, self.revoke = self.converge["block"]
        self.context = {
            "KEYCLOAK_EXEC_KCADM": KCADM,
            "KEYCLOAK_REALM": REALM,
            "KEYCLOAK_DIRECTORY_SERVICE_ACCOUNT": SERVICE_ACCOUNT,
            "KEYCLOAK_CONSOLE_ROLE_CLIENT": ROLE_VARS["KEYCLOAK_CONSOLE_ROLE_CLIENT"],
            "KEYCLOAK_DIRECTORY_CLIENT_ROLES": ROLES,
        }

    def plan(self, held: list[str]) -> dict:
        """Resolve the block vars for a service account that holds ``held``.

        Args:
            held: realm-management roles the live service account holds.
        """
        stdout = "Logging into the server\n" + json.dumps(
            [{"name": name} for name in held]
        )
        context = {**self.context, "kc_directory_roles": {"stdout": stdout}}
        block_vars = self.converge["vars"]
        context["kc_directory_held"] = evaluate(
            block_vars["kc_directory_held"], **context
        )
        for name in ("kc_directory_grant", "kc_directory_revoke"):
            context[name] = evaluate(block_vars[name], **context)
        return context

    def test_the_client_reaches_kcadm_only_through_the_stdin_module(self) -> None:
        params = self.upsert["keycloak_kcadm_update"]
        self.assertEqual(params["object_kind"], "client")
        self.assertEqual(params["lookup_value"], "{{ KEYCLOAK_DIRECTORY_CLIENT_ID }}")
        self.assertEqual(params["desired"], "{{ KEYCLOAK_DIRECTORY_CLIENT }}")
        self.assertEqual(params["kcadm_exec"], "{{ KEYCLOAK_EXEC_KCADM }}")
        self.assertEqual(self.upsert["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")

    def test_the_upserted_client_is_the_one_of_the_realm_import(self) -> None:
        directory = {"clientId": CLIENT_ID, "secret": "s"}
        realm = {"clients": [{"clientId": REALM}, directory]}
        self.assertEqual(
            evaluate(
                ROLE_VARS["KEYCLOAK_DIRECTORY_CLIENT"],
                KEYCLOAK_DICTIONARY_REALM=realm,
                KEYCLOAK_DIRECTORY_CLIENT_ID=CLIENT_ID,
            ),
            directory,
        )

    def test_only_a_created_client_reports_a_change(self) -> None:
        for exists, changed in ((False, True), (True, False)):
            with self.subTest(exists=exists):
                self.assertIs(
                    evaluate(
                        self.upsert["changed_when"],
                        kc_directory_client={"object_exists": exists},
                    ),
                    changed,
                )

    def test_the_read_lists_the_direct_realm_management_roles_of_the_service_account(
        self,
    ) -> None:
        self.assertEqual(
            argv(self.read["ansible.builtin.shell"], **self.context),
            [
                KCADM,
                "get-roles",
                "-r",
                REALM,
                "--uusername",
                SERVICE_ACCOUNT,
                "--cclientid",
                "realm-management",
            ],
        )
        self.assertIs(self.read["changed_when"], False)

    def test_a_fresh_service_account_gets_all_three_roles(self) -> None:
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
                "view-users",
                "--rolename",
                "query-users",
                "--rolename",
                "manage-users",
            ],
        )

    def test_a_converged_service_account_is_left_alone(self) -> None:
        context = self.plan(list(reversed(ROLES)))
        self.assertFalse(holds(self.grant["when"], **context))
        self.assertFalse(holds(self.revoke["when"], **context))

    def test_a_drifted_service_account_loses_every_other_role(self) -> None:
        context = self.plan(["view-users", "view-realm", "manage-clients"])
        self.assertEqual(context["kc_directory_grant"], ["query-users", "manage-users"])
        self.assertEqual(
            context["kc_directory_revoke"], ["view-realm", "manage-clients"]
        )
        self.assertEqual(
            argv(self.revoke["ansible.builtin.shell"], **context),
            [
                KCADM,
                "remove-roles",
                "-r",
                REALM,
                "--uusername",
                SERVICE_ACCOUNT,
                "--cclientid",
                "realm-management",
                "--rolename",
                "view-realm",
                "--rolename",
                "manage-clients",
            ],
        )


class TestDirectoryClientDisabled(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup, self.delete = load_yaml_any(str(DISABLED))
        self.context = {
            "KEYCLOAK_EXEC_KCADM": KCADM,
            "KEYCLOAK_REALM": REALM,
            "KEYCLOAK_DIRECTORY_CLIENT_ID": CLIENT_ID,
        }

    def test_the_lookup_asks_for_the_directory_client_only(self) -> None:
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

    def test_the_delete_runs_once_per_client_the_lookup_found(self) -> None:
        for stdout, ids in (("[]", []), ('[{"id": "c1"}]', ["c1"])):
            with self.subTest(stdout=stdout):
                found = evaluate(
                    self.delete["loop"], kc_directory_client_found={"stdout": stdout}
                )
                self.assertEqual([item["id"] for item in found], ids)

    def test_the_delete_removes_the_found_client_by_its_internal_id(self) -> None:
        self.assertEqual(
            argv(
                self.delete["ansible.builtin.shell"], **self.context, item={"id": "c1"}
            ),
            [KCADM, "delete", "clients/c1", "-r", REALM],
        )


class TestDirectoryClientVariants(unittest.TestCase):
    def test_only_variant_zero_turns_the_switch_on(self) -> None:
        variants = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_VARIANTS))
        switches = [
            variant["services"]["keycloak"].get("directory_client", {}).get("enabled")
            for variant in variants
        ]
        self.assertEqual(switches, [True] + [None] * (len(variants) - 1))


if __name__ == "__main__":
    unittest.main()
