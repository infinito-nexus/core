from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

from ._semaphore_fake import (
    ALIAS,
    CHANGELOG,
    FINISHED,
    SCRIPTS,
    SCRIPTS_DIR,
    WORKSPACE_ID,
    FakeSemaphore,
    load_project,
    load_workspace,
    platform_spec,
    workspace_spec,
)

REQUIREMENT = (
    PROJECT_ROOT / "docs" / "requirements" / "102-one-semaphore-runner-per-workspace.md"
)
FIXTURE = re.compile(
    r"reads from here as its fixture:\n\n\s*```json\n\s*(\{[^\n]*\})\n"
)
IDS = (
    "project_id",
    "template_id",
    "ssh_key_id",
    "repository_id",
    "inventory_id",
    "environment_id",
)
PROVIDERS = json.loads(
    read_text(
        str(PROJECT_ROOT / "roles/web-app-semaphore/files/opentofu/credentials.json")
    )
)["providers"]
PRIVATE = "203.0.113.0/24"
TARGET = "203.0.113.10:22"
OWN_TAG = "ci-0123abcd"
OWN_BUILD = f"registry.local:5000/infinito-nexus/core:{OWN_TAG}"
WORKSPACES = "Infinito.Nexus Workspaces"
SECOND_READ_KEY = {
    "private": "-----BEGIN OPENSSH PRIVATE KEY-----\nread2\n-----END OPENSSH PRIVATE KEY-----",
    "public": "ssh-ed25519 AAAAread2",
}
KEYCLOAK_REFUSAL = (
    f"the alias {ALIAS} belongs to an organization without the workspace marker"
)
SHIM = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
variables = json.loads(Path(next(a[1:] for a in args if a.startswith("@"))).read_text())
password = Path(args[args.index("--vault-password-file") + 1])
Path(os.environ["SHIM_RECORD"]).write_text(json.dumps({
    "argv": args,
    "cwd": os.getcwd(),
    "variables": variables,
    "password_mode": password.stat().st_mode & 0o777,
    "password_in_env": "DEPLOY_VAULT_PASSWORD" in os.environ,
    "bao_token": os.environ.get("BAO_TOKEN"),
}))
if os.environ["SHIM_MODE"] == "fail":
    print(os.environ["SHIM_REFUSAL"], file=sys.stderr)
    sys.exit(2)
Path(variables["WORKSPACE_RESULT_FILE"]).write_text(os.environ["SHIM_RESULT"])
print("PLAY RECAP")
"""


def example_line():
    """Returns:
    The example line of 102 decision 3, the fixture store and core share.
    """
    match = FIXTURE.search(read_text(str(REQUIREMENT)))
    assert match is not None, "102 decision 3 lost its example line"
    return match.group(1)


def without_ids(entry):
    return {k: v for k, v in entry.items() if k not in IDS}


def shape(entry):
    return {k: type(v).__name__ for k, v in entry.items()}


def apply(mod, api, hint=None):
    """Args:
    mod: the converger module.
    api: the fake.
    hint: the project id of the workspace's runner row.

    Returns:
        The ``result`` of a workspace apply after a platform converge.
    """
    if not api.projects:
        mod.converge(api, platform_spec(), lambda seconds: None)
    return mod.run_workspace(api, workspace_spec(hint=hint), lambda seconds: None)[1][
        "result"
    ]


def checked_result(module, directory, written):
    """Args:
    module: :func:`load_workspace`.
    directory: a scratch directory.
    written: the text the playbook wrote as result.

    Returns:
        The line ``workspace.py result`` prints for it.
    """
    operation = Path(directory) / "operation.json"
    result = Path(directory) / "result.json"
    operation.write_text(
        json.dumps(
            {
                "WORKSPACE": WORKSPACE_ID,
                "WORKSPACE_ACTION": "apply",
                "WORKSPACE_RESULT_FILE": str(result),
            }
        ),
        encoding="utf-8",
    )
    result.write_text(written, encoding="utf-8")
    return module.result(operation, result)


def erase_order_findings(api, tasks):
    """Args:
    api: the fake after a destroy.
    tasks: the tasks of the workspace that were unfinished before it.

    Returns:
        One finding per task that got no stop before the first erase, then
        one per task that had not finished by the first erase.
    """
    erases = [i for i, (method, _) in enumerate(api.writes) if method == "DELETE"]
    stops = [path for method, path in api.writes[: erases[0]] if method == "POST"]
    findings = [
        f"task {task['id']} got no stop before the first erase"
        for task in tasks
        if f"/project/{task['project_id']}/tasks/{task['id']}/stop" not in stops
    ]
    findings += [
        f"task {task['id']} was {api.at_first_erase[task['id']]} at the first erase"
        for task in tasks
        if api.at_first_erase[task["id"]] not in FINISHED
    ]
    return findings


class ScriptCase:
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name)
        self.bin = self.tmp / "bin"
        self.src = self.tmp / "src"
        self.home = self.tmp / "home"
        self.checkout = self.tmp / "checkout"
        for directory in (self.bin, self.src, self.home, self.checkout):
            directory.mkdir()
        shim = self.bin / "ansible-playbook"
        shim.write_text(SHIM, encoding="utf-8")
        shim.chmod(0o755)
        python = self.bin / "python3"
        python.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
        )
        python.chmod(0o755)
        for package in ("cli", "utils"):
            (self.src / package).symlink_to(PROJECT_ROOT / package)
        (self.src / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        (self.checkout / "devices.yml").write_text("all: {}\n", encoding="utf-8")
        self.record = self.tmp / "record.json"

    def run_script(self, env=None, args=(), mode="write", result=None):
        full = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "WORKSPACE": WORKSPACE_ID,
            "WORKSPACE_ACTION": "apply",
            "WORKSPACE_CORE_VERSION": "latest",
            "WORKSPACE_TARGETS": TARGET,
            "WORKSPACE_PLATFORM_TOKENS": "false",
            "WORKSPACE_PRIVATE_TARGETS": json.dumps([PRIVATE]),
            "WORKSPACE_CORE_FLOOR": "17.0.0",
            "WORKSPACE_OWN_BUILD": "",
            "WORKSPACE_OWN_BUILD_VERSION": "",
            "DEPLOY_VAULT_PASSWORD": "vaultpassword",
            "DEPLOY_LOGIN": "root",
            "DEPLOY_KNOWN_HOSTS": "",
            "SSH_AUTH_SOCK": str(self.tmp / "agent.sock"),
            "WORKSPACE_INVENTORY_FILE": "devices.yml",
            "INFINITO_SRC_DIR": str(self.src),
            "SHIM_MODE": mode,
            "SHIM_RECORD": str(self.record),
            "SHIM_REFUSAL": KEYCLOAK_REFUSAL,
            "SHIM_RESULT": example_line() if result is None else result,
            **(env or {}),
        }
        return subprocess.run(
            ["bash", str(SCRIPTS_DIR / "workspace.sh"), *args],
            cwd=self.checkout,
            env=full,
            capture_output=True,
            text=True,
            check=False,
        )

    def recorded(self):
        return json.loads(
            self.record.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )


class WorkspaceScriptTests(ScriptCase, unittest.TestCase):
    def test_workspace_sh_refuses_each_malformed_input(self):
        cases = [
            (
                "uppercase id",
                {"WORKSPACE": WORKSPACE_ID.upper()},
                (),
                "no lowercase UUID",
            ),
            ("no uuid", {"WORKSPACE": "ws-1"}, (), "no lowercase UUID"),
            (
                "action",
                {"WORKSPACE_ACTION": "rebuild"},
                (),
                "neither apply nor destroy",
            ),
            (
                "unreleased version",
                {"WORKSPACE_CORE_VERSION": "99.0.0"},
                (),
                "99.0.0 is no released version",
            ),
            (
                "leading v",
                {"WORKSPACE_CORE_VERSION": "v17.0.0"},
                (),
                "neither latest nor a version",
            ),
            (
                "release below the floor",
                {"WORKSPACE_CORE_VERSION": "16.2.0"},
                (),
                "16.2.0 predates the workspace runner, which ships from 17.0.0 on",
            ),
            (
                "release while none ships the runner",
                {"WORKSPACE_CORE_VERSION": "17.0.0", "WORKSPACE_CORE_FLOOR": ""},
                (),
                "17.0.0 predates the workspace runner, which ships in no release yet",
            ),
            (
                "latest below the floor",
                {"WORKSPACE_CORE_FLOOR": "17.1.0"},
                (),
                "latest finds no release of the workspace runner",
            ),
            (
                "malformed floor",
                {"WORKSPACE_CORE_FLOOR": "v17.0.0"},
                (),
                "WORKSPACE_CORE_FLOOR 'v17.0.0' is no version",
            ),
            (
                "own build on production",
                {"WORKSPACE_CORE_VERSION": OWN_TAG},
                (),
                f"{OWN_TAG!r} is neither latest nor a version",
            ),
            (
                "pair without port",
                {"WORKSPACE_TARGETS": "203.0.113.10"},
                (),
                "malformed pair",
            ),
            (
                "pair with bad port",
                {"WORKSPACE_TARGETS": "203.0.113.10:70000"},
                (),
                "port",
            ),
            (
                "private target",
                {"WORKSPACE_TARGETS": "10.0.0.5:22"},
                (),
                "neither public nor in services.semaphore.workspaces.private_targets",
            ),
            (
                "loopback target",
                {
                    "WORKSPACE_TARGETS": "127.0.0.1:22",
                    "WORKSPACE_PRIVATE_TARGETS": json.dumps(["127.0.0.0/8"]),
                },
                (),
                "neither public nor",
            ),
            (
                "link-local target",
                {
                    "WORKSPACE_TARGETS": "169.254.169.254:80",
                    "WORKSPACE_PRIVATE_TARGETS": json.dumps(["169.254.0.0/16"]),
                },
                (),
                "neither public nor",
            ),
            (
                "destroy with targets",
                {"WORKSPACE_ACTION": "destroy", "WORKSPACE_CORE_VERSION": ""},
                (),
                "WORKSPACE_TARGETS is not taken by destroy",
            ),
            (
                "apply without the platform switch",
                {"WORKSPACE_PLATFORM_TOKENS": ""},
                (),
                "WORKSPACE_PLATFORM_TOKENS '' is neither true nor false",
            ),
            (
                "non-boolean platform switch",
                {"WORKSPACE_PLATFORM_TOKENS": "yes"},
                (),
                "WORKSPACE_PLATFORM_TOKENS 'yes' is neither true nor false",
            ),
            (
                "destroy with the platform switch",
                {
                    "WORKSPACE_ACTION": "destroy",
                    "WORKSPACE_CORE_VERSION": "",
                    "WORKSPACE_TARGETS": "",
                },
                (),
                "WORKSPACE_PLATFORM_TOKENS is not taken by destroy",
            ),
            ("argument", {}, ("extra",), "unexpected argument 'extra'"),
        ]
        for name, env, args, message in cases:
            with self.subTest(name):
                self.record.unlink(missing_ok=True)
                run = self.run_script(env, args)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("workspace.sh: ", run.stderr)
                self.assertIn(message, run.stderr)
                self.assertFalse(self.record.exists(), "the playbook ran")
                self.assertEqual(run.stdout, "")

    def test_an_alias_without_the_marker_fails_apply_without_a_result(self):
        run = self.run_script(mode="fail")
        self.assertEqual(run.returncode, 2)
        self.assertIn(KEYCLOAK_REFUSAL, run.stderr)
        self.assertNotIn('"templates"', run.stdout)

    def test_apply_hands_the_playbook_the_pinned_operation(self):
        run = self.run_script()
        self.assertEqual(run.returncode, 0, run.stderr)
        record = self.recorded()
        self.assertEqual(Path(record["cwd"]).resolve(), self.src.resolve())
        argv = record["argv"]
        self.assertEqual(argv[0], "-i")
        self.assertEqual(
            Path(argv[1]).resolve(), (self.checkout / "devices.yml").resolve()
        )
        self.assertEqual(argv[2], "playbook-workspace.yml")
        self.assertEqual(record["argv"][record["argv"].index("-u") + 1], "root")
        self.assertEqual(record["password_mode"], 0o400)
        self.assertFalse(record["password_in_env"])
        variables = record["variables"]
        self.assertEqual(variables["WORKSPACE"], WORKSPACE_ID)
        self.assertEqual(variables["WORKSPACE_ACTION"], "apply")
        self.assertEqual(variables["WORKSPACE_CORE_VERSION"], "17.0.0")
        self.assertEqual(variables["WORKSPACE_CORE_BASE"], "")
        self.assertEqual(
            variables["WORKSPACE_TARGETS"],
            [{"host": "203.0.113.10", "port": 22, "address": "203.0.113.10"}],
        )
        self.assertIs(variables["WORKSPACE_PLATFORM_TOKENS"], False)

    def test_apply_hands_the_granted_platform_switch_as_true(self):
        run = self.run_script({"WORKSPACE_PLATFORM_TOKENS": "true"})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIs(self.recorded()["variables"]["WORKSPACE_PLATFORM_TOKENS"], True)

    def test_a_dev_or_ci_apply_builds_on_the_own_build_it_selects(self):
        for selected, floor in ((OWN_TAG, ""), ("latest", "17.0.0")):
            with self.subTest(selected=selected):
                self.record.unlink(missing_ok=True)
                run = self.run_script(
                    {
                        "WORKSPACE_CORE_VERSION": selected,
                        "WORKSPACE_CORE_FLOOR": floor,
                        "WORKSPACE_OWN_BUILD": OWN_BUILD,
                        "WORKSPACE_OWN_BUILD_VERSION": "17.1.0",
                    }
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                variables = self.recorded()["variables"]
                self.assertEqual(variables["WORKSPACE_CORE_VERSION"], "17.1.0")
                self.assertEqual(variables["WORKSPACE_CORE_BASE"], OWN_BUILD)

    def test_apply_ends_with_its_result(self):
        run = self.run_script()
        self.assertEqual(run.returncode, 0, run.stderr)
        last = run.stdout.rstrip("\n").splitlines()[-1]
        self.assertEqual(json.loads(last), json.loads(example_line()))
        self.assertEqual(last, example_line())

    def test_negative_control_a_result_with_another_key_fails_apply(self):
        planted = {**json.loads(example_line()), "token": "x"}
        run = self.run_script(result=json.dumps(planted))
        self.assertEqual(run.returncode, 2)
        self.assertIn("the playbook wrote the result keys", run.stderr)

    def test_negative_control_a_result_of_another_workspace_fails_apply(self):
        planted = {
            **json.loads(example_line()),
            "workspace": "11111111-2222-4333-8444-555555555555",
        }
        run = self.run_script(result=json.dumps(planted))
        self.assertEqual(run.returncode, 2)
        self.assertIn("the result of another workspace", run.stderr)

    def test_negative_control_a_template_without_its_runner_tag_fails_apply(self):
        planted = json.loads(example_line())
        del planted["templates"]["deploy"]["runner_tag"]
        run = self.run_script(result=json.dumps(planted))
        self.assertEqual(run.returncode, 2)
        self.assertIn("for deploy", run.stderr)

    def run_destroy(self, written):
        return self.run_script(
            {
                "WORKSPACE_ACTION": "destroy",
                "WORKSPACE_CORE_VERSION": "",
                "WORKSPACE_TARGETS": "",
                "WORKSPACE_PLATFORM_TOKENS": "",
            },
            result=json.dumps(written),
        )

    def test_destroy_ends_with_its_result(self):
        for stopped in (0, 2):
            with self.subTest(stopped=stopped):
                run = self.run_destroy(
                    {"workspace": WORKSPACE_ID, "stopped_tasks": stopped}
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    run.stdout.splitlines()[-1],
                    f'{{"destroyed": true, "stopped_tasks": {stopped}, '
                    f'"workspace": "{WORKSPACE_ID}"}}',
                )

    def test_negative_control_a_destroy_result_without_a_count_fails_destroy(self):
        cases = [
            ({"workspace": WORKSPACE_ID}, "the playbook wrote the destroy keys"),
            (
                {"workspace": WORKSPACE_ID, "stopped_tasks": True},
                "the stopped task count True",
            ),
            (
                {"workspace": WORKSPACE_ID, "stopped_tasks": -1},
                "the stopped task count -1",
            ),
        ]
        for written, message in cases:
            with self.subTest(written=written):
                run = self.run_destroy(written)
                self.assertEqual(run.returncode, 2)
                self.assertIn(message, run.stderr)
                self.assertNotIn('"destroyed"', run.stdout)

    def test_apply_accepts_an_empty_target_list(self):
        run = self.run_script({"WORKSPACE_TARGETS": ""})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.recorded()["variables"]["WORKSPACE_TARGETS"], [])


class ApplyResultTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def test_apply_reports_project_and_template_identity(self):
        fixture = json.loads(example_line())
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                checked_result(load_workspace(), directory, example_line()),
                example_line(),
            )
        result = apply(self.mod, self.api)
        self.assertEqual(sorted(result), sorted(fixture))
        self.assertEqual(result["workspace"], fixture["workspace"])
        self.assertEqual(result["alias"], fixture["alias"])
        self.assertEqual(result["project_id"], self.api.project_id(ALIAS))
        self.assertEqual(sorted(result["templates"]), sorted(fixture["templates"]))
        for name, entry in result["templates"].items():
            expected = fixture["templates"][name]
            self.assertEqual(without_ids(entry), without_ids(expected), name)
            self.assertEqual(shape(entry), shape(expected), name)
            template = self.api.call(
                "GET",
                f"/project/{entry['project_id']}/templates/{entry['template_id']}",
            )
            self.assertEqual(template["name"], name)
            self.assertEqual(template["runner_tag"], entry["runner_tag"])
            repository = self.api.call(
                "GET",
                f"/project/{entry['project_id']}/repositories/{template['repository_id']}",
            )
            self.assertEqual(repository["ssh_key_id"], entry["ssh_key_id"], name)
        with tempfile.TemporaryDirectory() as directory:
            checked_result(load_workspace(), directory, json.dumps(result))

    def test_negative_control_a_renamed_project_keeps_its_id(self):
        original = apply(self.mod, self.api)["project_id"]
        self.api.call("PUT", f"/project/{original}", {"name": "renamed by hand"})
        impostor = self.api.add_project(ALIAS)["id"]
        result = apply(self.mod, self.api, hint=original)
        self.assertEqual(result["project_id"], original)
        self.assertNotEqual(result["project_id"], impostor)
        self.assertEqual(self.api._project(original)["name"], ALIAS)

    def test_without_the_runner_hint_the_impostor_would_win(self):
        original = apply(self.mod, self.api)["project_id"]
        self.api.call("PUT", f"/project/{original}", {"name": "renamed by hand"})
        impostor = self.api.add_project(ALIAS)["id"]
        self.assertEqual(apply(self.mod, self.api)["project_id"], impostor)

    def test_every_template_name_is_unique_across_the_projects(self):
        names = [e["name"] for e in self.mod.WORKSPACES_TEMPLATES]
        names += [e["name"] for e in self.mod.WORKSPACES_SCHEDULED_TEMPLATES]
        names += [e["name"] for e in self.mod.EXPORT_SCHEDULED_TEMPLATES]
        names += [e["name"] for e in self.mod.WORKSPACE_TEMPLATES]
        names += [
            f"{e['name']} {ALIAS}"
            for entries in self.mod.PLATFORM_TEMPLATES.values()
            for e in entries
        ]
        self.assertEqual(len(names), len(set(names)))

    def test_apply_refuses_a_template_name_held_twice(self):
        planted = {**self.mod.WORKSPACE_TEMPLATES[0], "name": "members"}
        with (
            mock.patch.object(
                self.mod,
                "WORKSPACE_TEMPLATES",
                (*self.mod.WORKSPACE_TEMPLATES, planted),
            ),
            self.assertRaisesRegex(self.mod.ApiError, "members is not unique"),
        ):
            apply(self.mod, self.api)

    def test_every_handed_template_names_its_inventory(self):
        handed = apply(self.mod, self.api)["templates"]
        self.assertTrue(handed)
        for name, identity in handed.items():
            with self.subTest(name):
                self.assertIsInstance(identity["inventory_id"], int)

    def test_the_identities_refuse_a_template_without_an_inventory(self):
        replies = {
            "templates": {
                "name": "deploy",
                "repository_id": 1,
                "environment_id": 2,
                "inventory_id": None,
            },
            "repositories": {"git_url": "u", "git_branch": "main", "ssh_key_id": 3},
            "environment": {"env": "{}"},
        }
        api = mock.Mock()
        api.call.side_effect = lambda method, path: replies[path.split("/")[3]]
        with self.assertRaisesRegex(self.mod.ApiError, "deploy has no inventory"):
            self.mod.identities(api, [(1, 4)], {})

    def test_apply_hands_the_semaphore_ids_to_the_roles_after_it(self):
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)
        semaphore = self.mod.run_workspace(
            self.api, workspace_spec(), lambda seconds: None
        )[1]["semaphore"]
        workspaces = self.api.project_id("Infinito.Nexus Workspaces")
        provision = self.api.templates(self.api.project_id("Infinito.Nexus Provision"))
        export = self.api.templates(self.api.project_id("Infinito.Nexus Export"))
        self.assertEqual(
            semaphore,
            {
                "project_id": self.api.project_id(ALIAS),
                "workspaces_project_id": workspaces,
                "members_template_id": self.api.templates(workspaces)["members"]["id"],
                "provision_project_id": self.api.project_id("Infinito.Nexus Provision"),
                "provider_templates": {
                    provider: {
                        action: provision[f"{action}-{provider} {ALIAS}"]["id"]
                        for action in ("provision", "destroy")
                    }
                    for provider in PROVIDERS
                },
                "unlock_template_id": provision[f"unlock {ALIAS}"]["id"],
                "dns_template_id": provision[f"dns {ALIAS}"]["id"],
                "zone_template_id": provision[f"zone {ALIAS}"]["id"],
                "export_project_id": self.api.project_id("Infinito.Nexus Export"),
                "export_template_id": export[f"export {ALIAS}"]["id"],
            },
        )
        self.assertTrue(
            all(
                isinstance(v, int)
                for v in semaphore.values()
                if not isinstance(v, dict)
            )
        )

    def identity_command(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        spec = {
            "url": "http://semaphore",
            "token": "t",
            "workspaces": {"project": WORKSPACES},
        }
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = self.mod.main(
                argv, io.StringIO(json.dumps(spec)), None, lambda s: None
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_the_workspaces_identity_equals_the_entries_apply_reports(self):
        result = apply(self.mod, self.api)
        code, stdout, stderr = self.identity_command([self.mod.IDENTITY_COMMAND])
        self.assertEqual(code, 0, stderr)
        identity = json.loads(stdout)
        names = [e["name"] for e in self.mod.WORKSPACES_TEMPLATES]
        self.assertEqual(names, ["workspace", "members", "user"])
        self.assertEqual(identity["project_id"], self.api.project_id(WORKSPACES))
        self.assertEqual(
            identity["templates"], {n: result["templates"][n] for n in names}
        )
        self.assertEqual(
            self.mod.run_workspace(self.api, workspace_spec(), lambda s: None)[1][
                "semaphore"
            ]["members_template_id"],
            identity["templates"]["members"]["template_id"],
        )

    def test_negative_control_a_hand_changed_template_differs_from_apply(self):
        result = apply(self.mod, self.api)
        members = result["templates"]["members"]
        path = f"/project/{members['project_id']}/templates/{members['template_id']}"
        self.api.call(
            "PUT", path, {**self.api.call("GET", path), "runner_tag": "deploy"}
        )
        identity = json.loads(self.identity_command([self.mod.IDENTITY_COMMAND])[1])
        self.assertNotEqual(identity["templates"]["members"], members)

    def test_negative_control_an_unknown_command_is_refused(self):
        code, stdout, stderr = self.identity_command(["workspace-identity"])
        self.assertEqual((code, stdout), (2, ""))
        self.assertIn("expects no argument or workspaces-identity", stderr)

    def test_the_read_key_is_the_public_half_the_workspace_project_holds(self):
        result = apply(self.mod, self.api)
        keys = [
            k["name"]
            for k in self.api.objects[(result["project_id"], "keys")]
            if k["name"].startswith("read ")
        ]
        self.assertEqual(keys, [f"read {result['read_key']}"])

    def reapply_with_a_fresh_candidate(self):
        """Returns:
        The result of a second apply whose candidate pair differs from the
        first, and every body that apply wrote.
        """
        spec = workspace_spec(public=SECOND_READ_KEY["public"])
        spec["read_key"] = dict(SECOND_READ_KEY)
        written = len(self.api.bodies)
        result = self.mod.run_workspace(self.api, spec, lambda seconds: None)[1]
        return result["result"], self.api.bodies[written:]

    def read_keys(self, project_id):
        return [
            k["name"]
            for k in self.api.objects[(project_id, "keys")]
            if k["name"].startswith("read ")
        ]

    def test_apply_keeps_the_read_key(self):
        first = apply(self.mod, self.api)
        second, written = self.reapply_with_a_fresh_candidate()
        self.assertEqual(second["read_key"], first["read_key"])
        self.assertEqual(
            {name: e["ssh_key_id"] for name, e in second["templates"].items()},
            {name: e["ssh_key_id"] for name, e in first["templates"].items()},
        )
        self.assertEqual([path for _, path, _ in written if "/keys" in path], [])
        self.assertNotIn(SECOND_READ_KEY["private"], json.dumps(written))
        self.assertEqual(
            self.read_keys(second["project_id"]), [f"read {first['read_key']}"]
        )

    def test_negative_control_a_lost_read_key_takes_the_candidate(self):
        first = apply(self.mod, self.api)
        held = next(
            k
            for k in self.api.objects[(first["project_id"], "keys")]
            if k["name"] == f"read {first['read_key']}"
        )
        self.api.call("DELETE", f"/project/{first['project_id']}/keys/{held['id']}")
        second, _ = self.reapply_with_a_fresh_candidate()
        self.assertEqual(second["read_key"], SECOND_READ_KEY["public"])
        self.assertNotEqual(second["read_key"], first["read_key"])


def export_source_findings(api, result):
    """Args:
    api: the fake after an apply.
    result: what the apply printed.

    Returns:
        One finding per way ``export ws-<id>`` reaches past the export
        runner's egress: a repository that is no local path of the runner
        image, a repository key other than the project's empty key, and a
        workspace read key left in the export project.
    """
    entry = result["templates"][f"export {ALIAS}"]
    project_id = entry["project_id"]
    keys = {k["id"]: k["name"] for k in api.objects[(project_id, "keys")]}
    findings = []
    if entry["git_url"] != SCRIPTS["path"] or entry["git_branch"] != "":
        findings.append(f"the export clones {entry['git_url']}")
    if keys.get(entry["ssh_key_id"]) != "None":
        findings.append(f"the export reads with {keys.get(entry['ssh_key_id'])}")
    findings += [
        f"the export project holds {name}"
        for name in keys.values()
        if name.startswith("read ")
    ]
    return findings


class ExportSourceTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)

    def test_the_export_runs_from_the_runner_image_like_its_scheduled_siblings(self):
        result = apply(self.mod, self.api)
        self.assertEqual(export_source_findings(self.api, result), [])
        provision = result["templates"][f"provision-incus {ALIAS}"]
        self.assertTrue(provision["git_url"].startswith("ssh://"))

    def test_a_reapply_moves_an_export_off_the_workspace_repository(self):
        with mock.patch.object(self.mod, "CHECKOUT_KINDS", self.mod.PLATFORM_KINDS):
            apply(self.mod, self.api)
        result = apply(self.mod, self.api)
        self.assertEqual(export_source_findings(self.api, result), [])

    def test_negative_control_an_export_that_clones_the_workspace_is_reported(self):
        with mock.patch.object(self.mod, "CHECKOUT_KINDS", self.mod.PLATFORM_KINDS):
            result = apply(self.mod, self.api)
        public = result["read_key"]
        self.assertEqual(
            export_source_findings(self.api, result),
            [
                f"the export clones ssh://git@git.example.org:2201/workspaces/{ALIAS}.git",
                f"the export reads with read {public}",
                f"the export project holds read {public}",
            ],
        )


class DestroyTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_project()
        self.api = FakeSemaphore(self.mod.ApiError)
        self.applied = apply(self.mod, self.api)

    def destroy(self):
        spec = workspace_spec(action="destroy")
        return self.mod.run_workspace(self.api, spec, lambda seconds: None)[0]

    def leftovers(self):
        found = [p["name"] for p in self.api.projects if p["name"] == ALIAS]
        for (project_id, collection), items in self.api.objects.items():
            found += [
                f"{project_id}/{collection}/{item['name']}"
                for item in items
                if item["name"] == ALIAS
                or item["name"].endswith(f" {ALIAS}")
                or (collection == "keys" and item["name"].startswith("read "))
            ]
        return found

    def test_each_destroy_step_counts_a_missing_resource_as_removed(self):
        provision = self.api.project_id("Infinito.Nexus Provision")
        dropped = self.applied["templates"][f"unlock {ALIAS}"]["template_id"]
        self.api.call("DELETE", f"/project/{provision}/templates/{dropped}")
        self.api.call("DELETE", f"/project/{self.applied['project_id']}")
        self.assertTrue(self.destroy())
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.destroy(), [])

    def test_a_delete_that_finds_the_object_gone_counts_as_removed(self):
        call = self.api.call

        def racing(method, path, body=None):
            if method == "DELETE" and "/templates/" in path:
                raise self.mod.ApiError(f"DELETE {path}: HTTP 404 not found")
            return call(method, path, body)

        with mock.patch.object(self.api, "call", racing):
            changes = self.destroy()
        self.assertEqual([c for c in changes if c.startswith("template ")], [])
        self.assertIn(f"project {ALIAS} removed", changes)

    def test_negative_control_any_other_error_stops_destroy(self):
        call = self.api.call

        def failing(method, path, body=None):
            if method == "DELETE" and "/templates/" in path:
                raise self.mod.ApiError(f"DELETE {path}: HTTP 500 internal error")
            return call(method, path, body)

        with (
            mock.patch.object(self.api, "call", failing),
            self.assertRaisesRegex(self.mod.ApiError, "HTTP 500"),
        ):
            self.destroy()

    def test_destroy_of_a_workspace_that_never_existed_changes_nothing(self):
        self.api = FakeSemaphore(self.mod.ApiError)
        self.mod.converge(self.api, platform_spec(), lambda seconds: None)
        self.assertEqual(self.destroy(), [])

    def run_destroy(self, sleeps):
        spec = workspace_spec(action="destroy")
        return self.mod.run_workspace(self.api, spec, sleeps.append)

    def plant(self):
        """Returns:
        ``(active, kept)``: a queued ``provision-incus ws-<id>`` and a running
        ``deploy`` task of the workspace, and a finished task of it, a running
        task of another workspace and the running ``workspace`` task of the
        destroy itself.
        """
        templates = self.applied["templates"]
        provision = templates[f"provision-incus {ALIAS}"]
        deploy = templates["deploy"]
        workspace = templates["workspace"]
        foreign = self.api.call(
            "POST",
            f"/project/{provision['project_id']}/templates",
            {"name": "provision-incus ws-other"},
        )
        kept = [
            self.api.add_task(deploy["project_id"], deploy["template_id"], "success"),
            self.api.add_task(provision["project_id"], foreign["id"], "running"),
            self.api.add_task(
                workspace["project_id"], workspace["template_id"], "running"
            ),
        ]
        active = [
            self.api.add_task(
                provision["project_id"], provision["template_id"], "waiting"
            ),
            self.api.add_task(deploy["project_id"], deploy["template_id"], "running"),
        ]
        self.api.writes.clear()
        self.api.at_first_erase = None
        return active, kept

    def stops(self):
        return [path for method, path in self.api.writes if path.endswith("/stop")]

    def test_destroy_stops_queued_and_running_tasks_before_the_first_erase(self):
        active, kept = self.plant()
        changes, output = self.run_destroy([])
        self.assertEqual(erase_order_findings(self.api, active), [])
        self.assertEqual(
            self.stops(),
            [f"/project/{t['project_id']}/tasks/{t['id']}/stop" for t in active],
        )
        self.assertEqual(
            output["result"], {"workspace": WORKSPACE_ID, "stopped_tasks": 2}
        )
        for task in active:
            self.assertIn(
                f"task {task['id']} of project {task['project_id']} stopped", changes
            )
        self.assertEqual(
            [t["status"] for t in self.api.tasks if t["id"] in {k["id"] for k in kept}],
            ["running", "running"],
        )
        self.assertEqual(self.leftovers(), [])

    def test_negative_control_a_destroy_without_the_stop_fails_the_order(self):
        active, _ = self.plant()
        queued, running = active
        with mock.patch.object(
            self.mod, "stop_tasks", lambda api, templates, changes, sleep: 0
        ):
            self.run_destroy([])
        self.assertEqual(
            erase_order_findings(self.api, active),
            [
                f"task {queued['id']} got no stop before the first erase",
                f"task {running['id']} got no stop before the first erase",
                f"task {queued['id']} was waiting at the first erase",
                f"task {running['id']} was running at the first erase",
            ],
        )

    def test_destroy_without_an_unfinished_task_reports_none_stopped(self):
        deploy = self.applied["templates"]["deploy"]
        self.api.add_task(deploy["project_id"], deploy["template_id"], "success")
        self.api.writes.clear()
        stdout, stderr = io.StringIO(), io.StringIO()
        spec = workspace_spec(action="destroy")
        with (
            mock.patch.object(self.mod, "Api", lambda url, token, opener: self.api),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = self.mod.main([], io.StringIO(json.dumps(spec)), None, lambda s: 0)
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(self.stops(), [])
        last = stdout.getvalue().splitlines()[-1]
        self.assertTrue(last.startswith("RESULT "), last)
        written = json.loads(last[len("RESULT ") :])["result"]
        self.assertEqual(written, {"workspace": WORKSPACE_ID, "stopped_tasks": 0})
        with tempfile.TemporaryDirectory() as directory:
            operation = Path(directory) / "operation.json"
            result = Path(directory) / "result.json"
            operation.write_text(
                json.dumps({"WORKSPACE": WORKSPACE_ID, "WORKSPACE_ACTION": "destroy"}),
                encoding="utf-8",
            )
            result.write_text(json.dumps(written), encoding="utf-8")
            self.assertEqual(
                load_workspace().result(operation, result),
                f'{{"destroyed": true, "stopped_tasks": 0, "workspace": "{WORKSPACE_ID}"}}',
            )

    def test_a_task_that_never_stops_fails_destroy_naming_it(self):
        active, _ = self.plant()
        running = active[1]
        self.api.stuck.add(running["id"])
        sleeps = []
        message = (
            f"the tasks {running['id']} are still unfinished "
            f"{self.mod.STOP_TIMEOUT} seconds after their stop"
        )
        with self.assertRaisesRegex(self.mod.ApiError, re.escape(message)):
            self.run_destroy(sleeps)
        self.assertEqual([m for m, _ in self.api.writes if m == "DELETE"], [])
        self.assertEqual(
            sleeps,
            [self.mod.STOP_DELAY] * (self.mod.STOP_TIMEOUT // self.mod.STOP_DELAY),
        )
        self.assertIn(self.applied["project_id"], [p["id"] for p in self.api.projects])

    def test_a_destroy_after_a_stop_timeout_finishes_once_the_task_stopped(self):
        active, _ = self.plant()
        self.api.stuck.add(active[1]["id"])
        with self.assertRaises(self.mod.ApiError):
            self.run_destroy([])
        self.api.stuck.clear()
        _, output = self.run_destroy([])
        self.assertEqual(output["result"]["stopped_tasks"], 1)
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
