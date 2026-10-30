"""The Semaphore project converger creates once, then changes nothing."""

from __future__ import annotations

import copy
import io
import json
import re
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-semaphore" / "files" / "python" / "project.py"
)
COLLECTION = re.compile(r"^/project/(\d+)/([a-z]+)(?:/(\d+))?$")


def load_module():
    spec = spec_from_file_location("semaphore_project", str(SCRIPT))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeSemaphore:
    def __init__(self):
        self.projects = []
        self.objects = {}
        self.next_id = 1
        self.writes = []
        self.bodies = []

    def _new_id(self):
        self.next_id += 1
        return self.next_id

    def _store(self, project_id, collection, body):
        stored = {**copy.deepcopy(body), "id": self._new_id()}
        if collection == "keys":
            stored.pop("ssh", None)
        if collection == "environment":
            stored["secrets"] = [
                {"id": self._new_id(), "type": s["type"], "name": s["name"]}
                for s in stored.get("secrets", [])
            ]
        self.objects.setdefault((project_id, collection), []).append(stored)
        return stored

    def call(self, method, path, body=None):
        if method != "GET":
            self.writes.append((method, path))
            self.bodies.append((method, path, copy.deepcopy(body)))
        if path == "/projects":
            if method == "GET":
                return copy.deepcopy(self.projects)
            project = {"id": self._new_id(), "name": body["name"]}
            self.projects.append(project)
            self._store(project["id"], "keys", {"name": "None", "type": "none"})
            return project
        match = COLLECTION.match(path)
        project_id, collection, object_id = (
            int(match.group(1)),
            match.group(2),
            match.group(3),
        )
        items = self.objects.setdefault((project_id, collection), [])
        if method == "GET":
            return copy.deepcopy(items)
        if method == "POST":
            return self._store(project_id, collection, body)
        index = next(i for i, item in enumerate(items) if item["id"] == int(object_id))
        if method == "PUT":
            items[index] = copy.deepcopy(body)
            return None
        del items[index]
        return None

    def names(self, project_id, collection):
        return sorted(item["name"] for item in self.objects[(project_id, collection)])


def spec(applications, key_name="app-control 0123456789ab"):
    return {
        "url": "http://127.0.0.1:3000/api",
        "token": "deploytoken",
        "project": "Infinito.Nexus",
        "key": {
            "name": key_name,
            "prefix": "app-control ",
            "login": "app-control",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nkey\n-----END OPENSSH PRIVATE KEY-----",
        },
        "hosts": ["host.docker.internal"],
        "known_hosts": ["host.docker.internal ssh-ed25519 AAAAhostkey"],
        "inventory": "app-control",
        "repository": {"name": "app-control", "path": "/opt/app-control"},
        "environment": "app-control",
        "playbook": "app-control.sh",
        "applications": applications,
    }


def deploy():
    return {
        "project": "Infinito.Nexus Deploy",
        "key": {
            "name": "deploy 111111111111",
            "prefix": "deploy ",
            "login": "root",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\ndeploy\n-----END OPENSSH PRIVATE KEY-----",
        },
        "repository": {
            "name": "inventory",
            "url": "ssh://git@git.example.org:2201/administrator/target-inventory.git",
            "branch": "main",
            "key": {
                "name": "inventory 222222222222",
                "prefix": "inventory ",
                "login": "",
                "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nrepository\n-----END OPENSSH PRIVATE KEY-----",
            },
        },
        "inventory": "deploy",
        "environment": {
            "prefix": "deploy ",
            "login": "root",
            "known_hosts": ["target ssh-ed25519 AAAAtargetkey"],
            "vault_password": "vaultpassword",
        },
        "task_template": {
            "name": "deploy",
            "app": "infinito",
            "playbook": "devices.yml",
        },
    }


def spec_with_deploy():
    return {**spec(["web-app-wiki"]), "deploy": deploy()}


class ConvergeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.api = FakeSemaphore()

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)

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
        self.mod = load_module()
        self.api = FakeSemaphore()

    def converge(self, document):
        return self.mod.converge(self.api, document, lambda seconds: None)

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
        first = self.mod.deploy_environment(1, deploy()["environment"], "key-a")
        second = self.mod.deploy_environment(1, deploy()["environment"], "key-b")
        self.assertNotEqual(first["name"], second["name"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

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
                io.StringIO(json.dumps(spec([]))), opener, lambda s: None
            )
        self.assertEqual(code, 1)
        self.assertIn("HTTP 401", stderr.getvalue())
        self.assertNotIn("deploytoken", stderr.getvalue())


class DesiredTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

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


if __name__ == "__main__":
    unittest.main()
