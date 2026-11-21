from __future__ import annotations

import copy
import json
import os
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

from .templates.test_realm_import_json import (
    CLIENT_APPS,
    CONTEXT,
    REALM_MANAGEMENT,
    ROLE_DIR,
    ROLE_VARS,
    organizations_context,
    render,
)
from .test_usage_client_tasks import ENV, KCADM, REALM, argv, evaluate, holds

SCOPE = ROLE_VARS["KEYCLOAK_ADMIN_API_SCOPE"]
UTIL = ROLE_DIR / "tasks/utils/admin_api_scope.yml"
UTIL_REF = "utils/admin_api_scope.yml"
ROUTINES = ROLE_DIR / "tasks/03_manager_ops/update_routines.yml"
OPENTALK = PROJECT_ROOT / "roles/web-app-opentalk/tasks/02_keycloak_client.yml"
ROLES_DIR = f"{PROJECT_ROOT / 'roles'}{os.sep}"
ALL_ON = {**organizations_context(True), "KEYCLOAK_USAGE_CLIENT_ENABLED": True}
ADMIN_API_CLIENTS = {
    CONTEXT["KEYCLOAK_USAGE_CLIENT_ID"],
    ALL_ON["KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID"],
    ALL_ON["KEYCLOAK_EXPORT_CLIENT_ID"],
}
COMMAND_MODULES = (
    "ansible.builtin.shell",
    "shell",
    "ansible.builtin.command",
    "command",
)
INCLUDE_ROLE = ("ansible.builtin.include_role", "include_role")
INCLUDE_TASKS = ("ansible.builtin.include_tasks", "include_tasks")
SCOPE_ID = "s-admin"
CLIENT = {"id": "c1", "clientId": "opentalk-controller"}
OTHER = {"id": "c2", "clientId": "other"}
NOISE = "Logging into http://127.0.0.1:8080 as user admin of realm master\n"


def realm(overrides: dict | None = None) -> dict:
    """
    Args:
        overrides: context values replacing those of CONTEXT.

    Returns:
        The parsed realm import with every client-declaring app.
    """
    return json.loads(render([], client_apps=CLIENT_APPS, overrides=overrides))


def admin_api_clients(realm: dict) -> set[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        The clientIds whose service account holds a realm-management role.
    """
    return {
        user["serviceAccountClientId"]
        for user in realm["users"]
        if "serviceAccountClientId" in user
        and user.get("clientRoles", {}).get(REALM_MANAGEMENT)
    }


def scope_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        One line per client whose service account holds a realm-management
        role while the client lacks the Admin API scope as a default scope.
    """
    clients = {client["clientId"]: client for client in realm["clients"]}
    return sorted(
        f"{client_id} lacks {SCOPE}"
        for client_id in admin_api_clients(realm)
        if SCOPE not in clients.get(client_id, {}).get("defaultClientScopes", [])
    )


def client_of(realm: dict, client_id: str) -> dict:
    """
    Args:
        realm: the parsed realm import.
        client_id: a clientId of the realm.

    Returns:
        The client representation carrying ``client_id``.
    """
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


def role_var(name: str, **context):
    """
    Args:
        name: a variable of ``vars/main.yml``.
        context: the variables its expression reads.

    Returns:
        The variable's value, with Ansible's ``contains`` test.
    """
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.tests["contains"] = lambda seq, value: value in seq
    bare = ROLE_VARS[name].strip().removeprefix("{{").removesuffix("}}")
    return env.compile_expression(bare)(**context)


def every_task(tasks):
    """
    Args:
        tasks: a task list.

    Returns:
        Every task of the list, the tasks of its blocks included.
    """
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for section in ("block", "rescue", "always"):
            yield from every_task(task.get(section))


def command_text(task: dict) -> str:
    """
    Args:
        task: one task.

    Returns:
        The command text of a shell or command task, else an empty string.
    """
    for module in COMMAND_MODULES:
        params = task.get(module)
        if isinstance(params, dict):
            return json.dumps(params)
        if params is not None:
            return str(params)
    return ""


def grants_realm_management(task: dict) -> bool:
    """
    Args:
        task: one task.

    Returns:
        Whether the task maps realm-management roles onto a service account.
    """
    text = command_text(task)
    return all(
        marker in text for marker in ("add-roles", REALM_MANAGEMENT, "service-account-")
    )


def assigns_scope(task: dict) -> bool:
    """
    Args:
        task: one task.

    Returns:
        Whether the task runs the Admin API scope routine of web-app-keycloak.
    """
    for module in INCLUDE_ROLE:
        params = task.get(module)
        if isinstance(params, dict) and params.get("tasks_from") == UTIL_REF:
            return params.get("name") == "web-app-keycloak"
    return any(str(task.get(module, "")).endswith(UTIL_REF) for module in INCLUDE_TASKS)


def guard_findings(files: dict[str, list]) -> list[str]:
    """
    Args:
        files: task lists by file name.

    Returns:
        The files that map realm-management roles onto a service account
        without running the Admin API scope routine.
    """
    findings = []
    for name, tasks in sorted(files.items()):
        flat = list(every_task(tasks))
        if any(map(grants_realm_management, flat)) and not any(
            map(assigns_scope, flat)
        ):
            findings.append(name)
    return findings


def role_task_files() -> dict[str, list]:
    """
    Returns:
        Every role task file that names ``add-roles``, by its path below the project.
    """
    return {
        os.path.relpath(path, PROJECT_ROOT): load_yaml_any(path)
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(ROLES_DIR)
        and f"{os.sep}tasks{os.sep}" in path
        and "add-roles" in read_text(path)
    }


def scopes_stdout(*names: str) -> dict:
    """
    Args:
        names: client scope names the realm holds.

    Returns:
        A registered kcadm read of those client scopes.
    """
    scopes = [
        {"id": SCOPE_ID if name == SCOPE else f"s-{name}", "name": name}
        for name in names
    ]
    return {"stdout": NOISE + json.dumps(scopes)}


class TestAdminApiClientTemplates(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm(ALL_ON)

    def test_every_client_with_realm_management_roles_lists_the_scope(self) -> None:
        self.assertEqual(admin_api_clients(self.realm), ADMIN_API_CLIENTS)
        self.assertEqual(scope_findings(self.realm), [])

    def test_dropping_the_scope_from_a_client_fails_the_check(self) -> None:
        for client_id in sorted(ADMIN_API_CLIENTS):
            with self.subTest(client=client_id):
                changed = copy.deepcopy(self.realm)
                client_of(changed, client_id)["defaultClientScopes"].remove(SCOPE)
                self.assertEqual(
                    scope_findings(changed), [f"{client_id} lacks {SCOPE}"]
                )

    def test_a_new_realm_managing_service_account_without_the_scope_fails(self) -> None:
        planted = copy.deepcopy(self.realm)
        planted["clients"].append(
            {"clientId": "planted", "defaultClientScopes": ["basic", "roles"]}
        )
        planted["users"].append(
            {
                "username": "service-account-planted",
                "serviceAccountClientId": "planted",
                "clientRoles": {REALM_MANAGEMENT: ["view-users"]},
            }
        )
        self.assertEqual(scope_findings(planted), [f"planted lacks {SCOPE}"])

    def test_only_the_admin_api_clients_carry_the_scope(self) -> None:
        carriers = {
            client["clientId"]
            for client in self.realm["clients"]
            if SCOPE in client.get("defaultClientScopes", [])
            or SCOPE in client.get("optionalClientScopes", [])
        }
        self.assertEqual(carriers, ADMIN_API_CLIENTS)

    def test_the_realm_import_defines_no_look_alike_scope(self) -> None:
        self.assertNotIn(SCOPE, {scope["name"] for scope in self.realm["clientScopes"]})
        self.assertNotIn(SCOPE, self.realm["defaultDefaultClientScopes"])
        self.assertNotIn(SCOPE, self.realm["defaultOptionalClientScopes"])

    def test_the_role_derives_its_admin_api_clients_from_the_realm(self) -> None:
        for overrides, expected in ((ALL_ON, ADMIN_API_CLIENTS), (None, set())):
            with self.subTest(switches_on=overrides is not None):
                found = role_var(
                    "KEYCLOAK_ADMIN_API_CLIENT_IDS",
                    KEYCLOAK_DICTIONARY_REALM=realm(overrides),
                    KEYCLOAK_ADMIN_API_SCOPE=SCOPE,
                )
                self.assertEqual(set(found), expected)
                self.assertEqual(len(found), len(expected))


class TestAdminApiScopeRoutine(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.read_scopes,
            self.refuse_scope,
            self.guarded,
        ) = load_yaml_any(str(UTIL))
        self.read_clients, self.assign = self.guarded["block"]
        self.refuse_clients, self.read_held, self.put = self.assign["block"]
        self.context = {
            "keycloak_admin_api_kcadm": KCADM,
            "keycloak_admin_api_realm": REALM,
            "keycloak_admin_api_clients": [CLIENT["clientId"]],
            "KEYCLOAK_ADMIN_API_SCOPE": SCOPE,
        }

    def with_vars(self, task: dict, **context) -> dict:
        """
        Args:
            task: a task or block of the routine.
            context: the variables its vars read.

        Returns:
            ``context`` extended by the task's own vars, resolved.
        """
        resolved = dict(context)
        for name, expression in (task.get("vars") or {}).items():
            resolved[name] = evaluate(expression, **resolved)
        return resolved

    def plan(self, clients: list[dict], held: list[str]) -> dict:
        """
        Args:
            clients: the clients the realm holds.
            held: ids of the default client scopes the wanted client holds.

        Returns:
            The context the assignment block runs with, one held result included.
        """
        context = self.with_vars(
            self.assign,
            **self.context,
            keycloak_admin_api_scope_list=scopes_stdout("basic", "roles", SCOPE),
            keycloak_admin_api_client_list={"stdout": NOISE + json.dumps(clients)},
        )
        found = evaluate(self.read_held["loop"], **context)
        context["held_result"] = {
            "item": found[0] if found else None,
            "stdout": NOISE + json.dumps([{"id": i, "name": i} for i in held]),
        }
        return context

    def test_the_scope_read_lists_the_client_scopes_of_the_realm(self) -> None:
        self.assertEqual(
            argv(self.read_scopes["ansible.builtin.shell"], **self.context),
            [
                KCADM,
                "get",
                "client-scopes",
                "-r",
                REALM,
                "--fields",
                "id,name",
                "--format",
                "json",
            ],
        )
        self.assertIs(self.read_scopes["changed_when"], False)

    def test_a_realm_without_the_scope_is_refused_with_the_version(self) -> None:
        for names, accepted in ((("basic", "roles"), False), (("basic", SCOPE), True)):
            with self.subTest(names=names):
                context = self.with_vars(
                    self.refuse_scope,
                    **self.context,
                    keycloak_admin_api_scope_list=scopes_stdout(*names),
                )
                that = self.refuse_scope["ansible.builtin.assert"]["that"]
                self.assertIs(holds(that, **context), accepted)
        message = ENV.from_string(
            self.refuse_scope["ansible.builtin.assert"]["fail_msg"]
        ).render(**self.context)
        self.assertIn("26.8.2", message)
        self.assertIn(SCOPE, message)

    def test_an_empty_client_list_only_checks_the_scope(self) -> None:
        for clients, runs in (([], False), ([CLIENT["clientId"]], True)):
            with self.subTest(clients=clients):
                context = {**self.context, "keycloak_admin_api_clients": clients}
                self.assertIs(holds(self.guarded["when"], **context), runs)
        self.assertNotIn("when", self.read_clients)
        self.assertNotIn("when", self.assign)
        self.assertNotIn("when", self.refuse_scope)
        self.assertNotIn("when", self.read_scopes)

    def test_the_client_read_lists_the_clients_of_the_realm(self) -> None:
        self.assertEqual(
            argv(self.read_clients["ansible.builtin.shell"], **self.context),
            [
                KCADM,
                "get",
                "clients",
                "-r",
                REALM,
                "--fields",
                "id,clientId",
                "--format",
                "json",
            ],
        )
        self.assertIs(self.read_clients["changed_when"], False)

    def test_a_client_the_realm_lacks_is_refused(self) -> None:
        for clients, accepted in (([OTHER], False), ([OTHER, CLIENT], True)):
            with self.subTest(clients=clients):
                context = self.with_vars(self.refuse_clients, **self.plan(clients, []))
                that = self.refuse_clients["ansible.builtin.assert"]["that"]
                self.assertIs(holds(that, **context), accepted)

    def test_only_the_wanted_client_has_its_scopes_read(self) -> None:
        context = self.plan([OTHER, CLIENT], [])
        self.assertEqual(evaluate(self.read_held["loop"], **context), [CLIENT])
        self.assertEqual(
            argv(self.read_held["ansible.builtin.shell"], **context, item=CLIENT),
            [
                KCADM,
                "get",
                "clients/c1/default-client-scopes",
                "-r",
                REALM,
                "--format",
                "json",
            ],
        )
        self.assertIs(self.read_held["changed_when"], False)

    def test_a_client_lacking_the_scope_gets_exactly_one_put(self) -> None:
        context = self.plan([OTHER, CLIENT], ["s-basic", "s-roles"])
        item = context["held_result"]
        self.assertTrue(holds(self.put["when"], **context, item=item))
        self.assertEqual(
            argv(self.put["ansible.builtin.shell"], **context, item=item),
            [
                KCADM,
                "update",
                f"clients/c1/default-client-scopes/{SCOPE_ID}",
                "-r",
                REALM,
            ],
        )
        self.assertEqual(
            evaluate(self.put["loop"], keycloak_admin_api_held={"results": [item]}),
            [item],
        )

    def test_a_client_holding_the_scope_gets_no_put(self) -> None:
        context = self.plan([OTHER, CLIENT], ["s-basic", SCOPE_ID])
        self.assertFalse(
            holds(self.put["when"], **context, item=context["held_result"])
        )

    def test_the_routine_only_reads_and_assigns(self) -> None:
        verbs = {
            command_text(task).split("}}", 1)[1].split()[0]
            for task in every_task(load_yaml_any(str(UTIL)))
            if command_text(task)
        }
        self.assertEqual(verbs, {"get", "update"})


class TestAdminApiScopeCallers(unittest.TestCase):
    def test_the_realm_check_runs_before_the_settings_converge(self) -> None:
        routines = load_yaml_any(str(ROUTINES))
        includes = [str(task.get("include_tasks", "")) for task in routines]
        check = next(i for i, path in enumerate(includes) if path.endswith(UTIL_REF))
        settings = next(i for i, path in enumerate(includes) if "01_settings" in path)
        self.assertLess(check, settings)
        task = routines[check]
        self.assertEqual(task["vars"]["keycloak_admin_api_clients"], [])
        self.assertEqual(
            task["vars"]["keycloak_admin_api_kcadm"], "{{ KEYCLOAK_EXEC_KCADM }}"
        )
        self.assertEqual(task["when"], "KEYCLOAK_ADMIN_API_CLIENT_IDS | length > 0")

    def test_opentalk_assigns_the_scope_after_granting_its_roles(self) -> None:
        tasks = load_yaml_any(str(OPENTALK))
        grant = next(i for i, t in enumerate(tasks) if grants_realm_management(t))
        assign = next(i for i, t in enumerate(tasks) if assigns_scope(t))
        self.assertLess(grant, assign)
        self.assertEqual(
            tasks[assign]["vars"]["keycloak_admin_api_clients"],
            ["{{ OPENTALK_CTRL_OIDC_CLIENT_ID }}"],
        )


class TestRealmManagementGrantGuard(unittest.TestCase):
    def test_every_service_account_grant_assigns_the_scope(self) -> None:
        files = role_task_files()
        granting = [
            name
            for name, tasks in files.items()
            if any(map(grants_realm_management, every_task(tasks)))
        ]
        self.assertIn(os.path.relpath(OPENTALK, PROJECT_ROOT), granting)
        self.assertEqual(guard_findings(files), [])

    def test_a_grant_without_the_scope_is_caught(self) -> None:
        tasks = load_yaml_any(str(OPENTALK))
        grant = next(t for t in tasks if grants_realm_management(t))
        assign = next(t for t in tasks if assigns_scope(t))
        self.assertEqual(guard_findings({"planted.yml": [grant]}), ["planted.yml"])
        self.assertEqual(
            guard_findings({"planted.yml": [{"block": [grant]}]}), ["planted.yml"]
        )
        self.assertEqual(guard_findings({"planted.yml": [grant, assign]}), [])


if __name__ == "__main__":
    unittest.main()
