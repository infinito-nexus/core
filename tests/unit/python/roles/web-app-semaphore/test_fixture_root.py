from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import ROLES_DIR
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from ._gates import gated_tasks

ROLE = ROLES_DIR / "web-app-semaphore"
ROOT = ROLE / "tasks" / "utils" / "project" / "fixture" / "root.yml"
AUTHORIZE = ROLE / "tasks" / "utils" / "project" / "fixture" / "root" / "authorize.yml"
INPUTS = ROLE / "tasks" / "utils" / "project" / "inputs.yml"
SECRETS = ROLE / ROLE_FILE_META_SECRETS
APP_CONTROL_VARS = ROLES_DIR / "sys-svc-app-control" / ROLE_FILE_VARS_MAIN
GATE = "SEMAPHORE_DEPLOY_FIXTURE_ENABLED | bool"
ROOT_WRITES = re.compile(
    r"SEMAPHORE_DEPLOY_FIXTURE_ROOT_(?:PUBLIC_KEY|KEYS_FILE|DROPIN)\b"
)
PRIVATE_READ = re.compile(
    r"SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY\b|\bfixture_ssh_key\b"
)
CREDENTIAL = re.compile(r"secrets\.credentials\.([a-z0-9_]+)")
TEST_RUNTIMES = ("dev", "act", "github")
PRIVATE_READERS = {
    "SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY",
    "SEMAPHORE_DEPLOY_FIXTURE_ROOT_PUBLIC_KEY",
    "SEMAPHORE_WORKSPACES_PRIVATE_KEY",
}


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def _bool(value):
    return (
        value
        if isinstance(value, bool)
        else str(value).strip().lower() in ("true", "1", "yes")
    )


def render(expression, runtime, **context):
    """Args:
    expression: a role var as ``vars/main.yml`` declares it.
    runtime: the ``RUNTIME`` of the render.
    context: further names the expression reads.

    Returns:
        The rendered text, every ``lookup`` answering true.
    """
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False, default=False),
    )
    environment.filters["bool"] = _bool
    return environment.from_string(str(expression)).render(
        RUNTIME=runtime,
        application_id="web-app-semaphore",
        SEMAPHORE_DEPLOY_ENABLED=True,
        lookup=lambda *args, **kwargs: True,
        **context,
    )


def render_findings(variables, runtime):
    """Args:
    variables: the role vars.
    runtime: the ``RUNTIME`` of the render.

    Returns:
        One message per fixture key a render of that runtime carries where a
        production render must carry none.
    """
    enabled = _bool(render(variables["SEMAPHORE_DEPLOY_FIXTURE_ENABLED"], runtime))
    chosen = render(
        variables["SEMAPHORE_WORKSPACES_PRIVATE_KEY"],
        runtime,
        SEMAPHORE_DEPLOY_FIXTURE_ENABLED=enabled,
        SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY="FIXTURE",
        SEMAPHORE_DEPLOY_PRIVATE_KEY="DEPLOY",
    )
    findings = []
    if enabled:
        findings.append(f"RUNTIME {runtime} turns the fixture on")
    if chosen != "DEPLOY":
        findings.append(
            f"RUNTIME {runtime} hands the Workspaces project the fixture key"
        )
    return findings


def ungated_writes(tasks):
    """Args:
    tasks: parsed task files.

    Returns:
        The name of every task that writes the fixture key or its sshd
        drop-in without the gate ``SEMAPHORE_DEPLOY_FIXTURE_ENABLED``.
    """
    found = []
    for task in tasks:
        body = {
            k: v
            for k, v in task.items()
            if k not in ("name", "when", "block", "rescue", "always")
        }
        if not ROOT_WRITES.search(str(body)) or "state" in str(
            body.get("ansible.builtin.file") or ""
        ):
            continue
        if "ansible.builtin.assert" in task:
            continue
        when = task.get("when")
        conditions = when if isinstance(when, list) else [when]
        if GATE not in conditions:
            found.append(task.get("name"))
    return found


def private_findings(role_dir):
    """Args:
    role_dir: the role directory.

    Returns:
        Every file and var outside ``PRIVATE_READERS`` that reads the private
        half of the fixture key.
    """
    found = []
    prefix = f"{role_dir}{os.sep}"
    for path in sorted(Path(p) for p in iter_project_files() if p.startswith(prefix)):
        if not path.is_file() or path.suffix not in (
            ".yml",
            ".j2",
            ".sh",
            ".py",
            ".js",
        ):
            continue
        if path.name == "secrets.yml" or path == role_dir / ROLE_FILE_VARS_MAIN:
            continue
        if PRIVATE_READ.search(read_text(str(path))):
            found.append(str(path.relative_to(role_dir)))
    variables = load_yaml_any(str(role_dir / ROLE_FILE_VARS_MAIN))
    found.extend(
        name
        for name, value in variables.items()
        if name not in PRIVATE_READERS and PRIVATE_READ.search(str(value))
    )
    return found


def credential(expression):
    match = CREDENTIAL.search(str(expression))
    return match[1] if match else None


def distinct_findings(variables, app_control):
    """Args:
    variables: the role vars.
    app_control: the vars of ``sys-svc-app-control``.

    Returns:
        One message per key the fixture key shares its source with.
    """
    fixture = credential(variables["SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY"])
    others = {
        "deploy": credential(variables["SEMAPHORE_DEPLOY_PRIVATE_KEY"]),
        "app-control": credential(variables["SEMAPHORE_APP_CONTROL_PRIVATE_KEY"]),
        "app-control account": app_control["APP_CONTROL_SSH_KEY_CREDENTIAL"],
    }
    findings = [
        f"the fixture key reads the {name} credential"
        for name, other in others.items()
        if other == fixture
    ]
    if fixture is None or "INFINITO_TARGET_KEY" in str(
        variables["SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY"]
    ):
        findings.append("the fixture key is no credential of its own")
    return findings


class TestFixtureRoot(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.root = list(gated_tasks(load_yaml_any(str(ROOT))))

    def test_only_test_runtimes_turn_the_fixture_key_on(self):
        self.assertEqual(render_findings(self.vars, "production"), [])
        for runtime in TEST_RUNTIMES:
            with self.subTest(runtime=runtime):
                self.assertEqual(
                    render_findings(self.vars, runtime),
                    [
                        f"RUNTIME {runtime} turns the fixture on",
                        f"RUNTIME {runtime} hands the Workspaces project the fixture key",
                    ],
                )

    def test_negative_control_a_key_planted_under_a_production_render_fails(self):
        for name, planted in (
            ("SEMAPHORE_DEPLOY_FIXTURE_ENABLED", "{{ true }}"),
            (
                "SEMAPHORE_WORKSPACES_PRIVATE_KEY",
                "{{ SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY }}",
            ),
        ):
            with self.subTest(planted=name):
                self.assertNotEqual(
                    render_findings({**self.vars, name: planted}, "production"), []
                )

    def test_every_write_of_the_root_key_is_gated_by_the_fixture(self):
        self.assertEqual(ungated_writes(self.root), [])
        removal = [t for t in self.root if "ansible.builtin.file" in t]
        self.assertEqual([t["when"] for t in removal], [f"not {GATE}"])
        self.assertEqual(removal[0]["ansible.builtin.file"]["state"], "absent")

    def test_negative_control_an_ungated_key_write_is_caught(self):
        planted = {
            "name": "planted",
            "ansible.builtin.copy": {
                "content": "{{ SEMAPHORE_DEPLOY_FIXTURE_ROOT_PUBLIC_KEY }}",
                "dest": "/root/.ssh/x",
            },
        }
        self.assertEqual(ungated_writes([*self.root, planted]), ["planted"])

    def test_negative_control_an_include_that_drops_the_gate_is_caught(self):
        ungated = [
            {k: v for k, v in t.items() if k != "when"}
            if "ansible.builtin.include_tasks" in t
            else t
            for t in load_yaml_any(str(ROOT))
        ]
        self.assertEqual(
            ungated_writes(list(gated_tasks(ungated))),
            [
                t["name"]
                for t in load_yaml_any(str(AUTHORIZE))
                if "ansible.builtin.assert" not in t
            ],
        )

    def test_the_root_tasks_run_on_every_deploy_of_the_project(self):
        includes = [
            t
            for t in _tasks(load_yaml_any(str(INPUTS)))
            if str(t.get("ansible.builtin.include_tasks", "")).endswith(
                "fixture/root.yml"
            )
        ]
        self.assertEqual(len(includes), 1)
        self.assertNotIn("when", includes[0])

    def test_the_drop_in_admits_root_with_the_fixture_key_file_alone(self):
        drop_in = read_text(
            str(ROLE / "templates" / "sshd" / "fixture_root.conf.j2")
        ).split()
        self.assertEqual(
            drop_in,
            [
                "Match",
                "User",
                "root",
                "PermitRootLogin",
                "prohibit-password",
                "AuthorizedKeysFile",
                "{{",
                "SEMAPHORE_DEPLOY_FIXTURE_ROOT_KEYS_FILE",
                "}}",
            ],
        )

    def test_the_fixture_key_is_a_generated_key_of_its_own(self):
        secrets = load_yaml_any(str(SECRETS))["credentials"]
        self.assertEqual(
            secrets["fixture_ssh_key"]["algorithm"],
            secrets["deploy_ssh_key"]["algorithm"],
        )
        self.assertEqual(
            distinct_findings(self.vars, load_yaml_any(str(APP_CONTROL_VARS))), []
        )

    def test_negative_control_a_fixture_key_equal_to_app_control_or_target_is_caught(
        self,
    ):
        app_control = load_yaml_any(str(APP_CONTROL_VARS))
        for planted in (
            "{{ lookup('config', application_id, 'secrets.credentials.app_control_ssh_key') }}",
            "{{ lookup('config', application_id, 'secrets.credentials.deploy_ssh_key') }}",
            "{{ lookup('file', INFINITO_TARGET_KEY) }}",
        ):
            with self.subTest(planted=planted):
                variables = {
                    **self.vars,
                    "SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY": planted,
                }
                self.assertNotEqual(distinct_findings(variables, app_control), [])

    def test_the_runtime_assert_compares_the_key_with_app_control_deploy_and_target(
        self,
    ):
        asserts = [
            str(t.get("vars")) for t in self.root if "ansible.builtin.assert" in t
        ]
        self.assertEqual(len(asserts), 1)
        for name in (
            "'app-control'",
            "'deploy'",
            "'target'",
            "semaphore_deploy_fixture_holder_key",
        ):
            self.assertIn(name, asserts[0])

    def test_the_private_half_stays_in_the_workspaces_key(self):
        self.assertEqual(private_findings(ROLE), [])

    def test_negative_control_a_private_half_read_elsewhere_is_caught(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        planted = {
            **variables,
            "PLANTED": "{{ SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY }}",
        }
        self.assertEqual(
            [
                name
                for name, value in planted.items()
                if name not in PRIVATE_READERS and PRIVATE_READ.search(str(value))
            ],
            ["PLANTED"],
        )


if __name__ == "__main__":
    unittest.main()
