"""The Semaphore project converger creates once, then changes nothing."""

from __future__ import annotations

import copy
import io
import json
import re
import unittest
import unittest.mock as mock
import urllib.error
from contextlib import redirect_stderr, redirect_stdout

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._semaphore_fake import (
    ALIAS,
    ROLE,
    SCRIPTS,
    SCRIPTS_DIR,
    FakeSemaphore,
    app_control_spec,
    decoded,
    deploy_spec,
    env_secret_names,
    load_project,
    platform_spec,
    playbook_refusal,
    workspace_spec,
    workspaces_spec,
)

spec = app_control_spec
deploy = deploy_spec


def spec_with_deploy():
    return {**spec(["web-app-wiki"]), "deploy": deploy()}


class ConvergeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)[0]

    def project_id(self):
        return self.api.projects[0]["id"]

    def test_the_first_run_provisions_every_resource(self):
        changes = self.converge(spec(["web-app-wiki", "web-app-board"]))
        project_id = self.project_id()
        self.assertIn("project Infinito.Nexus created", changes)
        self.assertEqual(
            self.api.names(project_id, "templates"),
            [
                "start all",
                "start web-app-board",
                "start web-app-wiki",
                "stop all",
                "stop web-app-board",
                "stop web-app-wiki",
            ],
        )
        self.assertEqual(self.api.names(project_id, "inventory"), ["app-control"])
        self.assertEqual(self.api.names(project_id, "repositories"), ["app-control"])
        self.assertEqual(self.api.names(project_id, "environment"), ["app-control"])

    def test_a_second_run_against_an_unchanged_host_writes_nothing(self):
        self.converge(spec(["web-app-wiki", "web-app-board"]))
        writes = len(self.api.writes)
        self.assertEqual(self.converge(spec(["web-app-board", "web-app-wiki"])), [])
        self.assertEqual(len(self.api.writes), writes)

    def test_a_later_deploy_adds_exactly_the_new_applications_templates(self):
        self.converge(spec(["web-app-wiki"]))
        changes = self.converge(spec(["web-app-wiki", "web-app-board"]))
        self.assertEqual(
            sorted(changes),
            [
                "template start web-app-board created",
                "template stop web-app-board created",
            ],
        )

    def test_a_vanished_application_loses_its_templates_and_foreign_ones_stay(self):
        self.converge(spec(["web-app-wiki", "web-app-board"]))
        project_id = self.project_id()
        foreign = {
            "name": "stop web-app-board",
            "playbook": "deploy.yml",
            "repository_id": -1,
        }
        self.api.objects[(project_id, "templates")].append({**foreign, "id": 999})
        changes = self.converge(spec(["web-app-wiki"]))
        self.assertEqual(
            sorted(changes),
            [
                "template start web-app-board removed",
                "template stop web-app-board removed",
            ],
        )
        self.assertIn(
            999, [item["id"] for item in self.api.objects[(project_id, "templates")]]
        )

    def test_the_templates_run_the_script_with_action_and_target(self):
        self.converge(spec(["web-app-wiki"]))
        project_id = self.project_id()
        templates = {t["name"]: t for t in self.api.objects[(project_id, "templates")]}
        inventory = self.api.objects[(project_id, "inventory")][0]
        stop_all = templates["stop all"]
        self.assertEqual(stop_all["app"], "bash")
        self.assertEqual(stop_all["playbook"], "app-control.sh")
        self.assertEqual(json.loads(stop_all["arguments"]), ["stop", "all"])
        self.assertEqual(stop_all["inventory_id"], inventory["id"])
        self.assertFalse(stop_all["allow_override_args_in_task"])
        self.assertEqual(
            json.loads(templates["start web-app-wiki"]["arguments"]),
            ["start", "web-app-wiki"],
        )

    def test_the_inventory_carries_the_app_control_key(self):
        self.converge(spec(["web-app-wiki"]))
        project_id = self.project_id()
        inventory = self.api.objects[(project_id, "inventory")][0]
        keys = {k["id"]: k for k in self.api.objects[(project_id, "keys")]}
        self.assertEqual(
            keys[inventory["ssh_key_id"]]["name"], "app-control 0123456789ab"
        )
        self.assertEqual(
            inventory["inventory"],
            "[app_control]\nhost.docker.internal ansible_user=app-control\n",
        )

    def test_the_environment_names_the_targets_and_pins_their_host_keys(self):
        self.converge(spec(["web-app-wiki"]))
        environment = self.api.objects[(self.project_id(), "environment")][0]
        self.assertEqual(
            json.loads(environment["env"]),
            {
                "APP_CONTROL_TARGETS": "app-control@host.docker.internal",
                "APP_CONTROL_KNOWN_HOSTS": "host.docker.internal ssh-ed25519 AAAAhostkey",
            },
        )

    def test_the_repository_is_the_local_script_directory_of_the_runner(self):
        self.converge(spec(["web-app-wiki"]))
        project_id = self.project_id()
        repository = self.api.objects[(project_id, "repositories")][0]
        none_key = next(
            k for k in self.api.objects[(project_id, "keys")] if k["type"] == "none"
        )
        self.assertEqual(repository["git_url"], "/opt/app-control")
        self.assertEqual(repository["ssh_key_id"], none_key["id"])

    def test_a_rotated_key_replaces_the_old_one(self):
        self.converge(spec(["web-app-wiki"]))
        changes = self.converge(
            spec(["web-app-wiki"], key_name="app-control fedcba987654")
        )
        project_id = self.project_id()
        self.assertEqual(
            changes,
            [
                "key app-control fedcba987654 created",
                "inventory app-control updated",
                "key app-control 0123456789ab removed",
            ],
        )
        ssh_keys = [
            k["name"]
            for k in self.api.objects[(project_id, "keys")]
            if k["type"] == "ssh"
        ]
        self.assertEqual(ssh_keys, ["app-control fedcba987654"])

    def test_a_hand_edited_template_is_set_back(self):
        self.converge(spec(["web-app-wiki"]))
        project_id = self.project_id()
        template = next(
            t
            for t in self.api.objects[(project_id, "templates")]
            if t["name"] == "stop web-app-wiki"
        )
        template["arguments"] = json.dumps(["start", "web-app-wiki"])
        self.assertEqual(
            self.converge(spec(["web-app-wiki"])),
            ["template stop web-app-wiki updated"],
        )


class DeployConvergeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)[0]

    def deploy_project_id(self):
        return next(
            p["id"] for p in self.api.projects if p["name"] == "Infinito.Nexus Deploy"
        )

    def objects(self, collection):
        return self.api.objects[(self.deploy_project_id(), collection)]

    def test_without_a_deploy_block_no_deploy_project_exists(self):
        self.converge(spec(["web-app-wiki"]))
        self.assertEqual([p["name"] for p in self.api.projects], ["Infinito.Nexus"])

    def test_the_deploy_project_is_separate_from_the_app_control_project(self):
        self.converge(spec_with_deploy())
        self.assertEqual(
            sorted(p["name"] for p in self.api.projects),
            ["Infinito.Nexus", "Infinito.Nexus Deploy"],
        )
        self.assertEqual([t["name"] for t in self.objects("templates")], ["deploy"])

    def test_the_inventory_repository_is_bound_with_its_own_key(self):
        self.converge(spec_with_deploy())
        keys = {k["id"]: k for k in self.objects("keys")}
        repository = self.objects("repositories")[0]
        self.assertEqual(
            repository["git_url"],
            "ssh://git@git.example.org:2201/administrator/target-inventory.git",
        )
        self.assertEqual(repository["git_branch"], "main")
        self.assertEqual(
            keys[repository["ssh_key_id"]]["name"], "inventory 222222222222"
        )

    def test_the_template_runs_the_deploy_app_on_the_inventory_file_with_the_deploy_key(
        self,
    ):
        self.converge(spec_with_deploy())
        template = self.objects("templates")[0]
        inventory = self.objects("inventory")[0]
        keys = {k["id"]: k for k in self.objects("keys")}
        self.assertEqual(template["app"], "infinito")
        self.assertEqual(template["playbook"], "devices.yml")
        self.assertEqual(json.loads(template["arguments"]), [])
        self.assertFalse(template["allow_override_args_in_task"])
        self.assertEqual(template["inventory_id"], inventory["id"])
        self.assertEqual(
            template["repository_id"], self.objects("repositories")[0]["id"]
        )
        self.assertEqual(keys[inventory["ssh_key_id"]]["name"], "deploy 111111111111")

    def test_the_vault_password_travels_only_as_an_env_secret(self):
        self.converge(spec_with_deploy())
        created = next(
            body
            for method, path, body in self.api.bodies
            if method == "POST"
            and path == f"/project/{self.deploy_project_id()}/environment"
        )
        self.assertEqual(
            created["secrets"],
            [
                {
                    "type": "env",
                    "name": "DEPLOY_VAULT_PASSWORD",
                    "secret": "vaultpassword",
                    "operation": "create",
                }
            ],
        )
        environment = self.objects("environment")[0]
        self.assertNotIn("vaultpassword", json.dumps(environment))
        self.assertEqual(
            json.loads(environment["env"]),
            {
                "DEPLOY_LOGIN": "root",
                "DEPLOY_KNOWN_HOSTS": "target ssh-ed25519 AAAAtargetkey",
            },
        )
        self.assertRegex(environment["name"], r"^deploy [0-9a-f]{12}$")

    def test_a_second_run_writes_nothing(self):
        self.converge(spec_with_deploy())
        writes = len(self.api.writes)
        self.assertEqual(self.converge(spec_with_deploy()), [])
        self.assertEqual(len(self.api.writes), writes)

    def test_a_new_vault_password_replaces_the_environment(self):
        self.converge(spec_with_deploy())
        old = self.objects("environment")[0]["name"]
        rotated = spec_with_deploy()
        rotated["deploy"]["environment"]["vault_password"] = "rotated"
        changes = self.converge(rotated)
        new = self.objects("environment")[0]["name"]
        self.assertNotEqual(old, new)
        self.assertEqual(
            changes,
            [
                f"environment {new} created",
                "templates deploy updated",
                f"environment {old} removed",
            ],
        )
        self.assertEqual(len(self.objects("environment")), 1)

    def test_a_reset_target_repins_its_host_keys(self):
        self.converge(spec_with_deploy())
        reset = spec_with_deploy()
        reset["deploy"]["environment"]["known_hosts"] = [
            "target ssh-ed25519 AAAAresetkey"
        ]
        self.converge(reset)
        environment = self.objects("environment")[0]
        self.assertEqual(
            json.loads(environment["env"])["DEPLOY_KNOWN_HOSTS"],
            "target ssh-ed25519 AAAAresetkey",
        )

    def test_rotated_keys_replace_their_predecessors_only(self):
        self.converge(spec_with_deploy())
        rotated = spec_with_deploy()
        rotated["deploy"]["key"]["name"] = "deploy 333333333333"
        rotated["deploy"]["repository"]["key"]["name"] = "inventory 444444444444"
        changes = self.converge(rotated)
        self.assertEqual(
            changes,
            [
                "key deploy 333333333333 created",
                "key inventory 444444444444 created",
                "inventory deploy updated",
                "repositories inventory updated",
                "key deploy 111111111111 removed",
                "key inventory 222222222222 removed",
            ],
        )
        self.assertEqual(
            sorted(k["name"] for k in self.objects("keys") if k["type"] == "ssh"),
            ["deploy 333333333333", "inventory 444444444444"],
        )

    def test_the_environment_name_reveals_nothing_without_the_deploy_key(self):
        environment = {**deploy()["environment"], "secrets": {}}
        first = self.mod.deploy_environment(1, environment, "key-a", {})
        second = self.mod.deploy_environment(1, environment, "key-b", {})
        self.assertNotEqual(first["name"], second["name"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()

    def test_requests_carry_the_bearer_token_and_a_json_body(self):
        seen = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(request, timeout):
            seen.append(request)
            return Response(b'{"id": 7}')

        api = self.mod.Api("http://127.0.0.1:3000/api/", "deploytoken", opener)
        self.assertEqual(api.call("POST", "/projects", {"name": "x"}), {"id": 7})
        request = seen[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:3000/api/projects")
        self.assertEqual(request.get_header("Authorization"), "Bearer deploytoken")
        self.assertEqual(json.loads(request.data), {"name": "x"})

    def test_a_refused_request_raises_with_the_answer(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {}, io.BytesIO(b"invalid app")
            )

        api = self.mod.Api("http://127.0.0.1:3000/api", "deploytoken", opener)
        with self.assertRaisesRegex(self.mod.ApiError, "HTTP 400 invalid app"):
            api.call("POST", "/project/1/templates", {})

    def test_the_api_is_awaited_while_it_refuses_connections(self):
        attempts = []

        class Starting:
            def call(self, method, path, body=None):
                attempts.append(path)
                if len(attempts) < 3:
                    raise urllib.error.URLError("connection refused")
                return []

        self.assertEqual(
            self.mod.wait_until_ready(Starting(), 5, 0, lambda seconds: None), []
        )
        self.assertEqual(len(attempts), 3)

    def test_main_reports_a_refusal_and_fails(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"")
            )

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = self.mod.main(
                [], io.StringIO(json.dumps(spec([]))), opener, lambda s: None
            )
        self.assertEqual(code, 1)
        self.assertIn("HTTP 401", stderr.getvalue())
        self.assertNotIn("deploytoken", stderr.getvalue())


class DesiredTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()

    def test_every_application_gets_stop_and_start_and_all_comes_last(self):
        self.assertEqual(
            [
                t["name"]
                for t in self.mod.desired_templates(
                    ["web-app-b", "web-app-a", "web-app-a"]
                )
            ],
            [
                "stop web-app-a",
                "start web-app-a",
                "stop web-app-b",
                "start web-app-b",
                "stop all",
                "start all",
            ],
        )

    def test_a_host_without_applications_still_offers_all(self):
        self.assertEqual(
            [t["arguments"] for t in self.mod.desired_templates([])],
            [["stop", "all"], ["start", "all"]],
        )


def every_template_body(mod):
    """Args:
    mod: the converger module.

    Returns:
        ``(api, bodies)``: the fake after a platform converge and a workspace
        apply, and every template body the converger sent.
    """
    api = FakeSemaphore(mod.ApiError)
    mod.converge(api, platform_spec(), lambda seconds: None)
    mod.run_workspace(api, workspace_spec(), lambda seconds: None)
    return api, api.written("templates")


def runner_tags(api):
    """Args:
    api: the fake after a platform converge and a workspace apply.

    Returns:
        ``{project_id: tag}`` of the runner each project runs on.
    """
    tags = {
        "Infinito.Nexus": "app-control",
        "Infinito.Nexus Deploy": "deploy",
        "Infinito.Nexus Workspaces": "workspaces",
        "Infinito.Nexus Provision": "provision",
        "Infinito.Nexus Export": "export",
        ALIAS: ALIAS,
    }
    return {p["id"]: tags[p["name"]] for p in api.projects}


def input_findings(templates, environments):
    """Args:
    templates: template bodies.
    environments: environment bodies.

    Returns:
        Every survey variable without target ``env`` and every ``var`` secret.
    """
    findings = [
        f"{t['name']}: {v['name']} has target {v.get('target')}"
        for t in templates
        for v in t.get("survey_vars") or []
        if v.get("target") != "env"
    ]
    findings.extend(
        f"{e['name']}: {name} is a var secret"
        for e in environments
        for kind, name in env_secret_names(e)
        if kind != "env"
    )
    return findings


def survey_names(body):
    return [v["name"] for v in body["survey_vars"]]


HOST_TEMPLATES = (
    "deploy",
    "update",
    "backup",
    "restart",
    "suspend",
    "resume",
    "release",
)
DNS_SURVEY = [
    ("DNS_ACTION", True, "env"),
    ("SALES_ORDER", True, "env"),
    ("LINE", True, "env"),
    ("HOST", True, "env"),
    ("DNS_LABEL", True, "env"),
]


ZONE_SURVEY = [
    ("ZONE_ACTION", True, "env"),
    ("SALES_ORDER", True, "env"),
    ("LINE", True, "env"),
    ("DOMAIN", False, "env"),
]
FIXED_SURVEYS = {
    "dns": (DNS_SURVEY, ("WORKSPACE_TARGETS",)),
    "zone": (ZONE_SURVEY, ()),
}


def fixed_survey_findings(kind, body, environment):
    """Args:
    kind: ``dns`` or ``zone``, a key of ``FIXED_SURVEYS``.
    body: the body of ``<kind> ws-<id>``.
    environment: the environment body that template runs with.

    Returns:
        Every drift from the kind's survey, every environment variable of
        the kind it lacks and every secret of the environment.
    """
    expected, needed = FIXED_SURVEYS[kind]
    survey = [(v["name"], v["required"], v.get("target")) for v in body["survey_vars"]]
    findings = [] if survey == expected else [f"the {kind} survey drifted: {survey}"]
    findings += [
        f"the {kind} environment lacks {name}"
        for name in needed
        if name not in decoded(environment)
    ]
    findings += [
        f"the {kind} environment holds the secret {name}"
        for _, name in env_secret_names(environment)
    ]
    return findings


def export_survey_findings(body, environment):
    """Args:
    body: the body of ``export ws-<id>``.
    environment: the environment body that template runs with.

    Returns:
        Every drift from a survey of exactly ``WORKSPACE`` and ``EXPORT_FOR``
        with target ``env``, every secret of the environment and every
        recipient it names.
    """
    survey = [(v["name"], v["required"], v.get("target")) for v in body["survey_vars"]]
    expected = [("WORKSPACE", True, "env"), ("EXPORT_FOR", True, "env")]
    findings = [] if survey == expected else [f"the export survey drifted: {survey}"]
    findings += [
        f"the export environment holds the secret {name}"
        for _, name in env_secret_names(environment)
    ]
    findings += [
        f"the export environment names a recipient: {name}"
        for name in decoded(environment)
        if "RECIPIENT" in name
    ]
    return findings


def task_starts(writes):
    """Args:
    writes: the ``(method, path)`` writes the fake recorded.

    Returns:
        Every task the converger started.
    """
    return [
        path for method, path in writes if method == "POST" and path.endswith("/tasks")
    ]


class LockedTemplateTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api, self.bodies = every_template_body(self.mod)
        self.workspace = self.api.templates(self.api.project_id(ALIAS))

    def test_apply_starts_no_task(self):
        self.assertEqual(task_starts(self.api.writes), [])

    def test_negative_control_a_started_members_sync_is_caught(self):
        project_id = self.api.project_id("Infinito.Nexus Workspaces")
        planted = [*self.api.writes, ("POST", f"/project/{project_id}/tasks")]
        self.assertEqual(task_starts(planted), [f"/project/{project_id}/tasks"])

    def test_every_template_names_its_runner_tag(self):
        tags = runner_tags(self.api)
        self.assertEqual(
            sorted({body["name"].split(" ")[0] for body in self.bodies}),
            [
                "announce",
                "backup",
                "deploy",
                "destroy",
                "dns",
                "export",
                "members",
                "provision",
                "prune",
                "release",
                "restart",
                "resume",
                "rotate",
                "start",
                "stop",
                "suspend",
                "unlock",
                "update",
                "usage",
                "user",
                "workspace",
                "zone",
            ],
        )
        for body in self.bodies:
            with self.subTest(template=body["name"]):
                self.assertEqual(body["runner_tag"], tags[body["project_id"]])

    def test_every_template_is_locked(self):
        for body in self.bodies:
            with self.subTest(template=body["name"]):
                self.assertEqual(self.mod.lock_findings(body), [])

    def test_an_ansible_template_locks_its_inventory(self):
        body = self.mod.template_body(
            1,
            {
                "name": "x",
                "app": "ansible",
                "playbook": "site.yml",
                "arguments": [],
                "survey": (),
            },
            {"inventory": 1, "repository": 1, "environment": 1, "runner_tag": "t"},
        )
        self.assertEqual(body["task_params"], {"allow_override_inventory": False})
        self.assertEqual(self.mod.lock_findings(body), [])

    def _drifted(self, change):
        body = copy.deepcopy(self.bodies[0])
        change(body)
        return self.mod.lock_findings(body)

    def test_negative_control_args_override(self):
        self.assertEqual(
            self._drifted(lambda b: b.update(allow_override_args_in_task=True)),
            ["allow_override_args_in_task"],
        )

    def test_negative_control_branch_override(self):
        self.assertEqual(
            self._drifted(lambda b: b.update(allow_override_branch_in_task=True)),
            ["allow_override_branch_in_task"],
        )

    def test_negative_control_parallel_tasks(self):
        self.assertEqual(
            self._drifted(lambda b: b.update(allow_parallel_tasks=True)),
            ["allow_parallel_tasks"],
        )

    def test_negative_control_runner_tag(self):
        self.assertEqual(
            self._drifted(lambda b: b.update(runner_tag=None)), ["runner_tag"]
        )

    def test_negative_control_jwt_off(self):
        self.assertEqual(
            self._drifted(lambda b: b.update(jwt_params={"enabled": False})),
            ["jwt_params"],
        )

    def test_negative_control_jwt_audience(self):
        self.assertEqual(
            self._drifted(
                lambda b: b.update(jwt_params={"enabled": True, "audience": "x"})
            ),
            ["jwt_params"],
        )

    def test_negative_control_ansible_inventory_override(self):
        def ansible(body):
            body["app"] = "ansible"
            body["task_params"] = {"allow_override_inventory": True}

        self.assertEqual(
            self._drifted(ansible), ["task_params.allow_override_inventory"]
        )

    def test_same_template_sees_every_locked_field(self):
        body = self.workspace["deploy"]
        changes = {
            "allow_override_args_in_task": True,
            "allow_override_branch_in_task": True,
            "allow_parallel_tasks": True,
            "runner_tag": "other",
            "jwt_params": {"enabled": False, "audience": "openbao"},
            "survey_vars": body["survey_vars"][:-1],
            "app": "bash",
            "playbook": "other.yml",
            "arguments": json.dumps(["x"]),
            "inventory_id": -1,
            "repository_id": -1,
            "environment_ids": [-1],
        }
        self.assertTrue(self.mod.same_template(body, body))
        for field, value in changes.items():
            with self.subTest(field=field):
                drifted = {**body, field: value}
                self.assertFalse(self.mod.same_template(drifted, body))
        ansible = {**body, "app": "ansible", "task_params": {}}
        self.assertFalse(self.mod.same_template(ansible, {**body, "app": "ansible"}))

    def test_a_template_changed_by_hand_is_realigned_by_the_next_apply(self):
        project_id = self.api.project_id(ALIAS)
        self.workspace["deploy"]["allow_parallel_tasks"] = True
        self.api.objects[(project_id, "templates")] = list(self.workspace.values())
        changes, _ = self.mod.run_workspace(
            self.api, workspace_spec(hint=project_id), lambda s: None
        )
        self.assertIn("templates deploy updated", changes)

    def test_every_input_reaches_the_script_as_env(self):
        environments = self.api.written("environment")
        self.assertEqual(input_findings(self.bodies, environments), [])

    def test_negative_control_a_survey_variable_without_target(self):
        planted = copy.deepcopy(self.bodies)
        planted[0]["survey_vars"].append({"name": "PLANTED", "required": True})
        self.assertEqual(
            input_findings(planted, []),
            [f"{planted[0]['name']}: PLANTED has target None"],
        )

    def test_negative_control_a_var_secret(self):
        environments = copy.deepcopy(self.api.written("environment"))
        environments[0]["secrets"] = [{"type": "var", "name": "PLANTED"}]
        self.assertEqual(
            input_findings([], environments),
            [f"{environments[0]['name']}: PLANTED is a var secret"],
        )

    def test_the_deploy_survey_is_fixed(self):
        deploy_body = self.workspace["deploy"]
        self.assertEqual(
            survey_names(deploy_body),
            [
                "SALES_ORDER",
                "LINE",
                "HOST",
                "HOST_KEY",
                "ROLES",
                "DNS_LABEL",
                "INVENTORY_COMMIT",
            ],
        )
        environment = next(
            e
            for e in self.api.objects[(self.api.project_id(ALIAS), "environment")]
            if e["id"] == deploy_body["environment_id"]
        )
        variables = json.loads(environment["env"])
        self.assertIn("WORKSPACE_DNS_ZONE", variables)
        self.assertIn("WORKSPACE_TARGETS", variables)
        self.assertEqual(deploy_survey_findings(deploy_body, variables), [])

    def test_negative_control_a_planted_dns_domain(self):
        deploy_body = copy.deepcopy(self.workspace["deploy"])
        deploy_body["survey_vars"].append(self.mod.survey_var("DNS_DOMAIN", True))
        self.assertEqual(
            deploy_survey_findings(deploy_body, {"WORKSPACE_DNS_ZONE": "z"}),
            ["the deploy survey takes a domain: DNS_DOMAIN"],
        )

    def export_template(self):
        project_id = self.api.project_id(workspace_spec()["export"]["project"])
        body = copy.deepcopy(self.api.templates(project_id)[f"export {ALIAS}"])
        environment = next(
            e
            for e in self.api.objects[(project_id, "environment")]
            if e["id"] == body["environment_id"]
        )
        return body, copy.deepcopy(environment)

    def test_the_export_survey_is_fixed(self):
        body, environment = self.export_template()
        self.assertEqual(export_survey_findings(body, environment), [])
        self.assertEqual(self.mod.lock_findings(body), [])

    def test_negative_control_a_planted_recipient_survey_variable(self):
        body, environment = self.export_template()
        body["survey_vars"].append(self.mod.survey_var("EXPORT_RECIPIENT", True))
        planted = [
            ("WORKSPACE", True, "env"),
            ("EXPORT_FOR", True, "env"),
            ("EXPORT_RECIPIENT", True, "env"),
        ]
        self.assertEqual(
            export_survey_findings(body, environment),
            [f"the export survey drifted: {planted}"],
        )

    def test_negative_control_a_planted_recipient_in_the_export_environment(self):
        body, environment = self.export_template()
        environment["env"] = json.dumps({"EXPORT_RECIPIENT": "age1planted"})
        environment["secrets"] = [{"type": "env", "name": "EXPORT_PASSPHRASE"}]
        self.assertEqual(
            export_survey_findings(body, environment),
            [
                "the export environment holds the secret EXPORT_PASSPHRASE",
                "the export environment names a recipient: EXPORT_RECIPIENT",
            ],
        )

    def fixed_template(self, kind):
        project_id = self.api.project_id(workspace_spec()["provision"]["project"])
        body = copy.deepcopy(self.api.templates(project_id)[f"{kind} {ALIAS}"])
        environment = next(
            e
            for e in self.api.objects[(project_id, "environment")]
            if e["id"] == body["environment_id"]
        )
        return body, copy.deepcopy(environment)

    def assert_fixed_survey(self, kind):
        body, environment = self.fixed_template(kind)
        self.assertEqual(fixed_survey_findings(kind, body, environment), [])
        self.assertEqual(self.mod.lock_findings(body), [])

    def test_the_dns_survey_is_fixed(self):
        self.assert_fixed_survey("dns")

    def test_the_zone_survey_is_fixed(self):
        self.assert_fixed_survey("zone")

    def test_negative_control_a_survey_with_a_planted_variable(self):
        for kind, planted in (("dns", "DNS_ZONE"), ("zone", "ZONE_TOKEN")):
            with self.subTest(kind=kind):
                body, environment = self.fixed_template(kind)
                body["survey_vars"].append(self.mod.survey_var(planted, True))
                drifted = [*FIXED_SURVEYS[kind][0], (planted, True, "env")]
                self.assertEqual(
                    fixed_survey_findings(kind, body, environment),
                    [f"the {kind} survey drifted: {drifted}"],
                )

    def test_negative_control_a_dns_survey_variable_without_env_target(self):
        body, environment = self.fixed_template("dns")
        body["survey_vars"][3]["target"] = None
        drifted = [*DNS_SURVEY[:3], ("HOST", True, None), DNS_SURVEY[4]]
        self.assertEqual(
            fixed_survey_findings("dns", body, environment),
            [f"the dns survey drifted: {drifted}"],
        )

    def test_negative_control_a_dns_environment_with_a_secret_and_no_targets(self):
        body, environment = self.fixed_template("dns")
        environment["env"] = json.dumps({"WORKSPACE": ALIAS})
        environment["secrets"] = [{"type": "env", "name": "PLANTED_TOKEN"}]
        self.assertEqual(
            fixed_survey_findings("dns", body, environment),
            [
                "the dns environment lacks WORKSPACE_TARGETS",
                "the dns environment holds the secret PLANTED_TOKEN",
            ],
        )

    def test_negative_control_a_zone_environment_with_a_secret(self):
        body, environment = self.fixed_template("zone")
        environment["secrets"] = [{"type": "env", "name": "CLOUDFLARE_API_TOKEN"}]
        self.assertEqual(
            fixed_survey_findings("zone", body, environment),
            ["the zone environment holds the secret CLOUDFLARE_API_TOKEN"],
        )

    def test_only_the_host_templates_take_a_host_key(self):
        self.assertEqual(host_key_findings(self.bodies), [])

    def test_negative_control_backup_without_host_key(self):
        bodies = copy.deepcopy(self.bodies)
        backup = next(b for b in bodies if b["name"] == "backup")
        backup["survey_vars"] = [
            v for v in backup["survey_vars"] if v["name"] != "HOST_KEY"
        ]
        self.assertEqual(host_key_findings(bodies), ["backup takes no HOST_KEY"])

    def test_negative_control_members_with_host_key(self):
        bodies = copy.deepcopy(self.bodies)
        members = next(b for b in bodies if b["name"] == "members")
        members["survey_vars"].append(self.mod.survey_var("HOST_KEY", True))
        self.assertEqual(host_key_findings(bodies), ["members takes a HOST_KEY"])

    def members_template(self):
        workspaces = self.api.project_id(platform_spec()["workspaces"]["project"])
        return copy.deepcopy(self.api.templates(workspaces)["members"])

    def test_the_members_survey_takes_the_suspension_flag(self):
        members = self.members_template()
        self.assertEqual(members_survey_findings(members), [])
        self.assertEqual(self.mod.lock_findings(members), [])

    def test_negative_control_members_without_the_suspension_flag(self):
        members = self.members_template()
        members["survey_vars"] = [
            v for v in members["survey_vars"] if v["name"] != "WORKSPACE_SUSPENDED"
        ]
        self.assertEqual(
            members_survey_findings(members),
            ["members survey lacks ('WORKSPACE_SUSPENDED', True, 'env')"],
        )

    def test_negative_control_an_optional_suspension_flag(self):
        members = self.members_template()
        flag = next(
            v for v in members["survey_vars"] if v["name"] == "WORKSPACE_SUSPENDED"
        )
        flag["required"] = False
        self.assertEqual(
            members_survey_findings(members),
            [
                "members survey lacks ('WORKSPACE_SUSPENDED', True, 'env')",
                "members survey adds ('WORKSPACE_SUSPENDED', False, 'env')",
            ],
        )

    def test_the_host_templates_hold_the_workspace_targets(self):
        project_id = self.api.project_id(ALIAS)
        environments = {
            e["id"]: json.loads(e["env"])
            for e in self.api.objects[(project_id, "environment")]
        }
        for name in HOST_TEMPLATES:
            with self.subTest(template=name):
                body = self.workspace[name]
                self.assertIn("HOST", survey_names(body))
                self.assertEqual(
                    environments[body["environment_id"]]["WORKSPACE_TARGETS"],
                    "203.0.113.10:22",
                )

    def test_the_inventory_commit_is_a_survey_variable(self):
        self.assertEqual(commit_findings(self.workspace.values()), [])

    def test_negative_control_update_without_inventory_commit(self):
        bodies = copy.deepcopy(list(self.workspace.values()))
        update = next(b for b in bodies if b["name"] == "update")
        update["survey_vars"] = [
            v for v in update["survey_vars"] if v["name"] != "INVENTORY_COMMIT"
        ]
        self.assertEqual(commit_findings(bodies), ["update takes no INVENTORY_COMMIT"])

    def test_the_usage_template_is_fixed(self):
        project_id = self.api.project_id(ALIAS)
        self.assertEqual(usage_findings(self.mod, self.api, project_id), [])
        before = len(self.api.writes)
        self.mod.run_workspace(
            self.api, workspace_spec(hint=project_id), lambda s: None
        )
        self.assertEqual(
            usage_writes(self.api, project_id, self.api.writes[before:]), []
        )
        self.assertEqual(usage_findings(self.mod, self.api, project_id), [])
        self.mod.run_workspace(
            self.api, workspace_spec("destroy", hint=project_id), lambda s: None
        )
        self.assertNotIn(project_id, [p["id"] for p in self.api.projects])
        self.assertNotIn((project_id, "templates"), self.api.objects)
        self.assertEqual(self.api.schedules(project_id), [])

    def test_negative_control_a_usage_template_with_a_survey_and_no_schedule(self):
        project_id = self.api.project_id(ALIAS)
        usage = next(
            t
            for t in self.api.objects[(project_id, "templates")]
            if t["name"] == "usage"
        )
        usage["survey_vars"].append(self.mod.survey_var("HOST", True))
        usage["arguments"] = json.dumps(["all"])
        self.api.objects[(project_id, "schedules")] = []
        self.assertEqual(
            usage_findings(self.mod, self.api, project_id),
            [
                "usage takes a survey: HOST",
                'usage passes ["all"]',
                "usage has 0 schedules",
            ],
        )

    def test_negative_control_a_second_usage_template_is_caught(self):
        project_id = self.api.project_id(ALIAS)
        templates = self.api.objects[(project_id, "templates")]
        usage = next(t for t in templates if t["name"] == "usage")
        templates.append({**copy.deepcopy(usage), "id": usage["id"] + 1000})
        self.assertEqual(
            usage_findings(self.mod, self.api, project_id), ["2 usage templates"]
        )

    def provision_templates(self):
        provision = self.api.project_id(workspace_spec()["provision"]["project"])
        return copy.deepcopy(self.api.templates(provision))

    def test_each_provision_template_runs_its_own_wrapper_without_arguments(self):
        self.assertEqual(provision_findings(self.provision_templates()), [])

    def test_negative_control_destroy_through_the_provision_wrapper(self):
        templates = self.provision_templates()
        destroy = templates[f"destroy {ALIAS}"]
        destroy["playbook"] = destroy["playbook"].replace("destroy.sh", "provision.sh")
        destroy["arguments"] = json.dumps(["destroy"])
        self.assertEqual(
            provision_findings(templates),
            [f"destroy runs {destroy['playbook']}", 'destroy passes ["destroy"]'],
        )

    def workspace_identities(self):
        _, output = self.mod.run_workspace(
            self.api, workspace_spec(hint=self.api.project_id(ALIAS)), lambda s: None
        )
        return output["result"]["templates"]

    def test_the_identity_pins_every_ref_by_id_and_names_only(self):
        identities = self.workspace_identities()
        self.assertEqual(identity_findings(self.api, identities), [])
        self.assertEqual(
            identities[f"provision {ALIAS}"]["environment_variables"],
            [
                "WORKSPACE",
                "WORKSPACE_DNS_ZONE",
                "WORKSPACE_DNS_ZONE_ID",
                "WORKSPACE_TARGETS",
            ],
        )
        self.assertIn(
            "MEMBERS_CLIENT_SECRET", identities["members"]["environment_variables"]
        )

    def test_negative_control_an_identity_with_values_is_caught(self):
        self.mod.environment_names = lambda environment: sorted(
            json.loads(environment["env"]).values()
        )
        findings = identity_findings(self.api, self.workspace_identities())
        self.assertIn(f"provision {ALIAS} names a value: ws.example.org", findings)

    def test_the_identity_records_the_shape_of_the_live_template(self):
        for name, identity in self.workspace_identities().items():
            live = self.api.call(
                "GET",
                f"/project/{identity['project_id']}/templates/{identity['template_id']}",
            )
            with self.subTest(template=name):
                self.assertEqual(
                    (
                        identity["app"],
                        identity["playbook"],
                        identity["arguments"],
                        identity["survey_variables"],
                    ),
                    (
                        live["app"],
                        live["playbook"],
                        json.loads(live["arguments"]),
                        sorted(survey["name"] for survey in live["survey_vars"]),
                    ),
                )
                self.assertEqual(bool(identity["survey_variables"]), name != "usage")


PROVISION_WRAPPERS = {
    "provision": ("provision.sh", ["SALES_ORDER", "LINE", "PROVIDER_TOKEN"]),
    "destroy": ("destroy.sh", ["SALES_ORDER", "LINE", "PROVIDER_TOKEN"]),
    "unlock": ("unlock.sh", ["SALES_ORDER", "LINE"]),
    "dns": ("dns.sh", ["DNS_ACTION", "SALES_ORDER", "LINE", "HOST", "DNS_LABEL"]),
    "zone": ("zone.sh", ["ZONE_ACTION", "SALES_ORDER", "LINE", "DOMAIN"]),
}
REFUSES_ARGUMENTS = "any argument is refused"


def provision_findings(templates):
    """Args:
    templates: ``{name: body}`` of the provision project's templates.

    Returns:
        Every provision template of ``ALIAS`` whose wrapper, arguments or
        survey drifted, and every wrapper whose header takes arguments.
    """
    findings = []
    for name, (script, survey) in PROVISION_WRAPPERS.items():
        body = templates[f"{name} {ALIAS}"]
        if (body["app"], body["playbook"]) != (SCRIPTS["script_app"], script):
            findings.append(f"{name} runs {body['playbook']}")
        if json.loads(body["arguments"]) != []:
            findings.append(f"{name} passes {body['arguments']}")
        if survey_names(body) != survey:
            findings.append(f"{name} survey drifted: {survey_names(body)}")
        if REFUSES_ARGUMENTS not in read_text(str(SCRIPTS_DIR / script)):
            findings.append(f"{script} takes arguments")
    return findings


def identity_findings(api, identities):
    """Args:
    api: the fake after the workspace apply.
    identities: the ``templates`` of the apply's result.

    Returns:
        Every identity whose repository, inventory or environment id differs
        from its template, and every environment value an identity names.
    """
    findings = []
    for name, identity in identities.items():
        project_id = identity["project_id"]
        template = api.call(
            "GET", f"/project/{project_id}/templates/{identity['template_id']}"
        )
        findings.extend(
            f"{name} {ref} {identity[ref]} != {template.get(ref)}"
            for ref in ("repository_id", "inventory_id", "environment_id")
            if identity[ref] != template.get(ref)
        )
        environment = api.call(
            "GET", f"/project/{project_id}/environment/{template['environment_id']}"
        )
        values = {v for v in decoded(environment).values() if v}
        findings.extend(
            f"{name} names a value: {value}"
            for value in identity["environment_variables"]
            if value in values
        )
    return findings


DAILY = re.compile(r"^[0-5]?[0-9] (1?[0-9]|2[0-3]) \* \* \*$")
MEMBERS_SURVEY = [
    ("WORKSPACE", True, "env"),
    ("MEMBERS_ACTION", True, "env"),
    ("WORKSPACE_MEMBER", False, "env"),
    ("INVITE_KEY", False, "env"),
    ("WORKSPACE_ROLE", False, "env"),
    ("WORKSPACE_SUSPENDED", True, "env"),
]


def members_survey_findings(body):
    survey = [(v["name"], v["required"], v["target"]) for v in body["survey_vars"]]
    findings = [
        f"members survey lacks {entry}"
        for entry in MEMBERS_SURVEY
        if entry not in survey
    ]
    findings.extend(
        f"members survey adds {entry}"
        for entry in survey
        if entry not in MEMBERS_SURVEY
    )
    return findings


def deploy_survey_findings(body, variables):
    findings = [
        f"the deploy survey takes a domain: {name}"
        for name in survey_names(body)
        if "DOMAIN" in name
    ]
    findings.extend(
        f"the deploy environment holds a domain: {name}"
        for name in variables
        if "DOMAIN" in name
    )
    return findings


def host_key_findings(bodies):
    findings = []
    for body in bodies:
        has_key = "HOST_KEY" in survey_names(body)
        host_template = body["name"] in HOST_TEMPLATES and (body["runner_tag"] == ALIAS)
        if host_template and not has_key:
            findings.append(f"{body['name']} takes no HOST_KEY")
        if has_key and not host_template:
            findings.append(f"{body['name']} takes a HOST_KEY")
    return findings


def commit_findings(bodies):
    return [
        f"{body['name']} takes no INVENTORY_COMMIT"
        for body in bodies
        if body["name"] in ("deploy", "update", "backup")
        and "INVENTORY_COMMIT" not in survey_names(body)
    ]


def usage_findings(mod, api, project_id):
    """Args:
    mod: the converger module.
    api: the fake after a workspace apply.
    project_id: the workspace project.

    Returns:
        Every drift of the project from one locked ``usage`` template without
        survey and argument and one active daily schedule for it.
    """
    usages = [t for t in api.objects[(project_id, "templates")] if t["name"] == "usage"]
    if len(usages) != 1:
        return [f"{len(usages)} usage templates"]
    (usage,) = usages
    findings = [f"usage takes a survey: {name}" for name in survey_names(usage)]
    if json.loads(usage["arguments"]) != []:
        findings.append(f"usage passes {usage['arguments']}")
    if usage["playbook"] != "usage.sh":
        findings.append(f"usage runs {usage['playbook']}")
    findings.extend(f"usage is open: {field}" for field in mod.lock_findings(usage))
    schedules = [
        s for s in api.schedules(project_id) if s["template_id"] == usage["id"]
    ]
    if len(schedules) != 1:
        findings.append(f"usage has {len(schedules)} schedules")
    elif not (schedules[0]["active"] and DAILY.match(schedules[0]["cron_format"])):
        findings.append(f"usage runs at {schedules[0]['cron_format']}")
    return findings


def usage_writes(api, project_id, writes):
    """Args:
    api: the fake after a second workspace apply.
    project_id: the workspace project.
    writes: the ``(method, path)`` writes of that apply.

    Returns:
        The writes that touched a schedule or the ``usage`` template.
    """
    usage = api.templates(project_id)["usage"]["id"]
    touched = (
        f"/project/{project_id}/schedules",
        f"/project/{project_id}/templates/{usage}",
    )
    return [write for write in writes if write[1].startswith(touched)]


EXPORT = "Infinito.Nexus Export"
SCHEDULED = {
    "announce owners": ("announce-owners.sh", "0 6 * * *"),
    "prune exports": ("prune-exports.sh", "0 * * * *"),
}
TASK_ONLY = ("WORKSPACE", "EXPORT_FOR")


def schedule_environment_findings(names, secrets):
    """Args:
    names: the plain variable names of the environment the scheduled export
        templates run with.
    secrets: the names of its secrets.

    Returns:
        Every secret, every name outside ``EXPORT_*`` and ``BAO_*`` and every
        variable that belongs to one export task only.
    """
    findings = [
        f"the scheduled environment holds the secret {name}" for name in secrets
    ]
    findings += [
        f"the scheduled environment names {name}"
        for name in sorted(names)
        if name in TASK_ONLY or not name.startswith(("EXPORT_", "BAO_"))
    ]
    return findings


def converged_workspaces(node):
    """Args:
    node: the parsed ``tasks/utils/project/sync.yml`` or a part of it.

    Returns:
        The raw ``semaphore_project_workspaces`` the converge task hands over.
    """
    if isinstance(node, list):
        return next(
            (found for item in node if (found := converged_workspaces(item))), None
        )
    if isinstance(node, dict):
        if "semaphore_project_workspaces" in (node.get("vars") or {}):
            return node["vars"]["semaphore_project_workspaces"]
        return converged_workspaces(node.get("block"))
    return None


class ExportScheduleTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.findings = self.converge()
        self.project_id = self.api.project_id(EXPORT)
        self.templates = self.api.templates(self.project_id)

    def converge(self):
        return self.mod.converge(self.api, platform_spec(), lambda seconds: None)[1]

    def identity(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        document = {
            "url": "http://semaphore",
            "token": "t",
            "workspaces": {"export": {"project": EXPORT}},
        }
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = self.mod.main(
                [self.mod.EXPORT_SCHEDULE_COMMAND],
                io.StringIO(json.dumps(document)),
                None,
                lambda seconds: None,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def plant_grant(self, name):
        self.mod.ensure_grant(
            self.api, self.project_id, self.templates[name]["id"], "guest", []
        )

    def test_each_scheduled_template_exists_once_on_its_cron(self):
        self.assertEqual(
            self.mod.converge(self.api, platform_spec(), lambda seconds: None)[0], []
        )
        names = [t["name"] for t in self.api.objects[(self.project_id, "templates")]]
        self.assertEqual(sorted(names), sorted(SCHEDULED))
        held = {t["id"]: t["name"] for t in self.templates.values()}
        self.assertEqual(
            sorted(
                (held[s["template_id"]], s["cron_format"], s["active"])
                for s in self.api.schedules(self.project_id)
            ),
            sorted((name, cron, True) for name, (_, cron) in SCHEDULED.items()),
        )

    def test_each_runs_its_script_locked_on_the_export_runner(self):
        repositories = {
            r["id"]: r for r in self.api.objects[(self.project_id, "repositories")]
        }
        inventories = {
            i["id"]: i for i in self.api.objects[(self.project_id, "inventory")]
        }
        for name, (script, _) in SCHEDULED.items():
            with self.subTest(name):
                template = self.templates[name]
                self.assertEqual(
                    (
                        template["app"],
                        template["playbook"],
                        json.loads(template["arguments"]),
                    ),
                    (SCRIPTS["script_app"], script, []),
                )
                self.assertEqual(template["survey_vars"], [])
                self.assertEqual(
                    template["runner_tag"], workspace_spec()["export"]["runner_tag"]
                )
                self.assertEqual(self.mod.lock_findings(template), [])
                repository = repositories[template["repository_id"]]
                self.assertEqual(
                    (repository["name"], repository["git_url"]),
                    ("scripts", "/opt/app-control"),
                )
                self.assertEqual(inventories[template["inventory_id"]]["inventory"], "")

    def test_the_environment_holds_plain_export_and_bao_values_only(self):
        environments = {
            e["id"]: e for e in self.api.objects[(self.project_id, "environment")]
        }
        for name in SCHEDULED:
            with self.subTest(name):
                environment = environments[self.templates[name]["environment_id"]]
                self.assertEqual(
                    decoded(environment), workspaces_spec()["export"]["environment"]
                )
                self.assertEqual(
                    schedule_environment_findings(
                        decoded(environment),
                        [n for _, n in env_secret_names(environment)],
                    ),
                    [],
                )

    def test_the_deploy_hands_them_the_export_variables_and_the_export_runner(self):
        converge = converged_workspaces(
            load_yaml_any(str(ROLE / "tasks" / "utils" / "project" / "sync.yml"))
        )["export"]
        self.assertEqual(converge["environment"], "{{ SEMAPHORE_EXPORT_VARIABLES }}")
        self.assertEqual(
            converge["runner_tag"], "{{ SEMAPHORE_PLATFORM_RUNNER_TAGS.export }}"
        )
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            schedule_environment_findings(variables["SEMAPHORE_EXPORT_VARIABLES"], []),
            [],
        )

    def test_negative_control_a_task_variable_a_foreign_name_and_a_secret_fail(self):
        self.assertEqual(
            schedule_environment_findings(
                {"WORKSPACE": "w", "EXPORT_FOR": "u", "KC_URL": "k", "BAO_ADDR": "b"},
                ["EXPORT_S3_SECRET_KEY"],
            ),
            [
                "the scheduled environment holds the secret EXPORT_S3_SECRET_KEY",
                "the scheduled environment names EXPORT_FOR",
                "the scheduled environment names KC_URL",
                "the scheduled environment names WORKSPACE",
            ],
        )

    def test_the_store_holds_no_grant_on_them(self):
        for name in SCHEDULED:
            with self.subTest(name):
                self.assertEqual(
                    self.api.perms.get(
                        (self.project_id, self.templates[name]["id"]), []
                    ),
                    [],
                )
        self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)
        self.assertEqual(self.findings, [])
        self.assertEqual(self.converge(), [])

    def test_negative_control_a_planted_grant_is_a_post_converge_finding(self):
        for name in SCHEDULED:
            with self.subTest(name):
                self.plant_grant(name)
                self.assertIn(
                    f"template {name} of project {self.project_id} carries a grant",
                    self.converge(),
                )

    def test_control_without_the_schedule_check_a_planted_grant_passes(self):
        self.plant_grant("prune exports")
        with mock.patch.object(
            self.mod, "schedule_grant_findings", lambda *arguments: []
        ):
            self.assertEqual(self.converge(), [])

    def test_the_schedule_identity_names_the_project_and_both_templates(self):
        code, stdout, stderr = self.identity()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(
            json.loads(stdout),
            {
                "project_id": self.project_id,
                "templates": {name: self.templates[name]["id"] for name in SCHEDULED},
            },
        )

    def test_negative_control_a_doubled_template_is_refused(self):
        self.api.call(
            "POST",
            f"/project/{self.project_id}/templates",
            {**self.templates["announce owners"], "id": None},
        )
        code, stdout, stderr = self.identity()
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn(
            f"2 templates of project {self.project_id} are named announce owners",
            stderr,
        )

    def test_negative_control_a_missing_template_is_refused(self):
        self.api.call(
            "DELETE",
            f"/project/{self.project_id}/templates/{self.templates['prune exports']['id']}",
        )
        code, stdout, stderr = self.identity()
        self.assertEqual((code, stdout), (1, ""))
        self.assertIn(
            f"0 templates of project {self.project_id} are named prune exports", stderr
        )


def playbook_findings(api):
    """Args:
    api: the fake after a converge and a workspace apply.

    Returns:
        Every template write whose playbook Semaphore refuses, and every write
        under the script app whose playbook is no script of the runner image.
    """
    scripts = {path.name for path in SCRIPTS_DIR.glob("*.sh")}
    findings = []
    for body in api.written("templates"):
        refusal = playbook_refusal(body["playbook"])
        if refusal:
            findings.append(f"{body['name']}: {refusal}")
        if body["app"] == SCRIPTS["script_app"] and body["playbook"] not in scripts:
            findings.append(f"{body['name']} names no script: {body['playbook']}")
    return findings


def absolute_script_template(entry, scripts):
    return {
        "app": "bash",
        "playbook": f"{scripts['path']}/{entry['script']}",
        "arguments": list(entry.get("arguments", [])),
    }


class RelativePlaybookTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)

    def apply(self):
        return self.mod.run_workspace(self.api, workspace_spec(), lambda seconds: None)

    def provision_template(self, name):
        project_id = self.api.project_id(workspace_spec()["provision"]["project"])
        return self.api.templates(project_id)[f"{name} {ALIAS}"]

    def test_every_template_of_a_converge_and_an_apply_runs_a_relative_playbook(self):
        self.apply()
        self.assertEqual(playbook_findings(self.api), [])
        self.assertEqual(
            [
                (
                    self.provision_template(name)["app"],
                    self.provision_template(name)["playbook"],
                )
                for name in PROVISION_WRAPPERS
            ],
            [
                (SCRIPTS["script_app"], script)
                for script, _ in PROVISION_WRAPPERS.values()
            ],
        )

    def test_a_reapply_moves_a_template_stored_with_an_absolute_playbook(self):
        self.apply()
        self.provision_template("provision")["playbook"] = (
            "/opt/app-control/provision.sh"
        )
        self.apply()
        self.assertEqual(
            self.provision_template("provision")["playbook"], "provision.sh"
        )

    def test_the_script_app_is_registered_and_handed_to_every_converge(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(variables["SEMAPHORE_SCRIPT_APP_ID"], SCRIPTS["script_app"])
        self.assertEqual(
            variables["SEMAPHORE_SCRIPT_APP"]["args"],
            ["{{ [SEMAPHORE_RUNNER_REPOSITORY, 'script.sh'] | path_join }}"],
        )
        self.assertIn(
            "SEMAPHORE_SCRIPT_APP_ID: SEMAPHORE_SCRIPT_APP",
            variables["SEMAPHORE_APPS_JSON"],
        )
        for path in ("workspace/operation.yml", "project/sync.yml"):
            with self.subTest(path):
                self.assertIn(
                    'script_app: "{{ SEMAPHORE_SCRIPT_APP_ID }}"',
                    read_text(str(ROLE / "tasks" / "utils" / path)),
                )

    def test_negative_control_an_absolute_playbook_is_refused_on_apply(self):
        with (
            mock.patch.object(self.mod, "script_template", absolute_script_template),
            self.assertRaisesRegex(
                self.mod.ApiError,
                "HTTP 400 template playbook must be a relative path inside the repository",
            ),
        ):
            self.apply()

    def test_negative_control_the_check_names_a_refused_or_unknown_playbook(self):
        self.api.bodies += [
            (
                "POST",
                "/project/1/templates",
                {"name": "a", "app": "bash", "playbook": "/opt/x.sh"},
            ),
            (
                "POST",
                "/project/1/templates",
                {"name": "b", "app": SCRIPTS["script_app"], "playbook": "../x.sh"},
            ),
        ]
        self.assertEqual(
            playbook_findings(self.api),
            [
                "a: template playbook must be a relative path inside the repository",
                "b: template playbook must not point outside the repository",
                "b names no script: ../x.sh",
            ],
        )


FIXTURE_KEY = {
    "name": "deploy 555555555555",
    "prefix": "deploy ",
    "login": "root",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n-----END OPENSSH PRIVATE KEY-----",
}
PLATFORM_PIN = "host.docker.internal ssh-ed25519 AAAAplatformkey"


def fixture_platform_spec():
    """Returns:
    The platform document of the deploy fixture: the Workspaces project signs
    in with the fixture key and pins the platform host alone.
    """
    document = platform_spec()
    document["workspaces"] = {
        **document["workspaces"],
        "key": dict(FIXTURE_KEY),
        "known_hosts": [PLATFORM_PIN],
    }
    return document


def sign_in_findings(api, workspaces_key, deploy_key, pins):
    """Args:
    api: the fake after a converge.
    workspaces_key: the key name the Workspaces inventory has to carry.
    deploy_key: the key name the deploy inventory has to carry.
    pins: the ``DEPLOY_KNOWN_HOSTS`` the Workspaces environment has to hold.

    Returns:
        One message per project that signs in with a key or pins a host it
        must not.
    """
    findings = []
    for name, expected in (
        ("Infinito.Nexus Workspaces", workspaces_key),
        ("Infinito.Nexus Deploy", deploy_key),
    ):
        project_id = api.project_id(name)
        keys = {key["id"]: key["name"] for key in api.objects[(project_id, "keys")]}
        held = sorted(
            keys[i["ssh_key_id"]] for i in api.objects[(project_id, "inventory")]
        )
        if held != [expected]:
            findings.append(f"{name} signs in with {held}, not {expected}")
    environment = api.objects[
        (api.project_id("Infinito.Nexus Workspaces"), "environment")
    ]
    pinned = [json.loads(e["env"])["DEPLOY_KNOWN_HOSTS"] for e in environment]
    if pinned != [pins]:
        findings.append(f"the Workspaces environment pins {pinned}, not {pins}")
    return findings


class WorkspacesSignInTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)[0]

    def test_the_fixture_key_reaches_the_workspaces_project_alone(self):
        self.converge(fixture_platform_spec())
        self.assertEqual(
            sign_in_findings(
                self.api, FIXTURE_KEY["name"], "deploy 111111111111", PLATFORM_PIN
            ),
            [],
        )

    def test_outside_the_fixture_the_workspaces_project_keeps_the_deploy_key(self):
        self.converge(platform_spec())
        self.assertEqual(
            sign_in_findings(
                self.api,
                "deploy 111111111111",
                "deploy 111111111111",
                "target ssh-ed25519 AAAAtargetkey",
            ),
            [],
        )

    def test_negative_control_the_deploy_key_in_the_workspaces_project_is_caught(self):
        self.converge(platform_spec())
        self.assertEqual(
            sign_in_findings(
                self.api, FIXTURE_KEY["name"], "deploy 111111111111", PLATFORM_PIN
            ),
            [
                (
                    "Infinito.Nexus Workspaces signs in with ['deploy 111111111111'], "
                    "not deploy 555555555555"
                ),
                (
                    "the Workspaces environment pins ['target ssh-ed25519 AAAAtargetkey'], "
                    f"not {PLATFORM_PIN}"
                ),
            ],
        )


class ProbeTemplateTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)

    def apply(self, probe):
        return self.mod.run_workspace(
            self.api, workspace_spec(probe=probe), lambda seconds: None
        )

    def probes(self):
        return {
            (project["name"], name): template
            for project in self.api.projects
            for name, template in self.api.templates(project["id"]).items()
            if name.split(" ")[0] == self.mod.PROBE_TEMPLATE["name"]
        }

    def test_a_test_runtime_gives_every_workspace_project_a_locked_probe(self):
        _, applied = self.apply(True)
        probes = self.probes()
        self.assertEqual(
            sorted(probes),
            sorted(
                [
                    (ALIAS, "probe"),
                    (workspace_spec()["provision"]["project"], f"probe {ALIAS}"),
                    (workspace_spec()["export"]["project"], f"probe {ALIAS}"),
                ]
            ),
        )
        for key, template in probes.items():
            with self.subTest(probe=key):
                self.assertEqual(self.mod.lock_findings(template), [])
                self.assertEqual(
                    (template["app"], template["playbook"]),
                    (SCRIPTS["script_app"], "probe.sh"),
                )
                self.assertEqual(
                    [v["name"] for v in template["survey_vars"]],
                    ["PROBE_SCRIPT", "PROBE_ARGS"],
                )
        self.assertNotIn("probe", applied["result"]["templates"])
        self.assertEqual(
            [
                name
                for name in applied["result"]["templates"]
                if name.startswith("probe")
            ],
            [],
        )

    def test_a_second_test_runtime_apply_keeps_one_probe_per_project(self):
        self.apply(True)
        first = {key: t["id"] for key, t in self.probes().items()}
        self.apply(True)
        self.assertEqual({key: t["id"] for key, t in self.probes().items()}, first)

    def test_negative_control_a_production_apply_creates_no_probe(self):
        self.apply(False)
        self.assertEqual(self.probes(), {})

    def test_negative_control_a_stringified_flag_creates_no_probe(self):
        self.apply("True")
        self.assertEqual(self.probes(), {})


if __name__ == "__main__":
    unittest.main()
