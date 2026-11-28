from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import ROLES_DIR
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from ._gates import conditions, gated_tasks, included
from .test_fixture_commit import credential_reads, fixture_scope

ROLE = ROLES_DIR / "web-app-semaphore"
OPENBAO = ROLES_DIR / "web-app-openbao"
FIXTURE = ROLE / "tasks" / "utils" / "project" / "fixture.yml"
INPUTS = ROLE / "tasks" / "utils" / "project" / "inputs.yml"
WRITER = "tasks/utils/project/fixture/credentials.yml"
ENV_TEMPLATE = ROLE / "templates" / "playwright.env.j2"
GATE = "SEMAPHORE_DEPLOY_FIXTURE_ENABLED | bool"
CREDENTIAL = "fixture_workspace_ssh_key"
PRIVATE = "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_PRIVATE_KEY"
PUBLIC = "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_PUBLIC_KEY"
READS = re.compile(r"SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_|\bfixture_workspace_ssh_key\b")
PRIVATE_READ = re.compile(rf"\b{PRIVATE}\b|\b{CREDENTIAL}\b")
CREDENTIAL_NAME = re.compile(r"secrets\.credentials\.([a-z0-9_]+)")
ENV_NAMES = (
    "SEMAPHORE_WORKSPACE_FIXTURE_KEY_PATH",
    "SEMAPHORE_DEPLOY_TARGET_VARS_JSON",
)
PRIVATE_READERS = {PUBLIC}
OTHER_KEYS = {
    "root": "SEMAPHORE_DEPLOY_FIXTURE_ROOT_PRIVATE_KEY",
    "deploy": "SEMAPHORE_DEPLOY_PRIVATE_KEY",
    "app-control": "SEMAPHORE_APP_CONTROL_PRIVATE_KEY",
}
WORKSPACE_LINE = "WORKSPACE-PUBLIC"
TARGET_VARS = "SEMAPHORE_DEPLOY_FIXTURE_TARGET_VARS"


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


def jinja():
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False, default=False),
    )
    environment.filters.update(bool=_bool, to_json=json.dumps, dotenv_quote=json.dumps)
    return environment


def source_findings(variables):
    """Args:
    variables: the role vars.

    Returns:
        One message per key the workspace fixture key shares its credential
        with, and one when it reads no generated credential of its own.
    """
    own = CREDENTIAL_NAME.search(str(variables[PRIVATE]))
    if own is None or own[1] != CREDENTIAL:
        return [f"{PRIVATE} reads no {CREDENTIAL} credential"]
    return [
        f"the workspace fixture key reads the {name} credential"
        for name, var in OTHER_KEYS.items()
        if (other := CREDENTIAL_NAME.search(str(variables[var]))) and other[1] == own[1]
    ]


def private_findings(role_dir, variables):
    """Args:
    role_dir: the role directory.
    variables: the role vars.

    Returns:
        Every file and var beside the writer, the secrets schema and
        ``PRIVATE_READERS`` that reads the private half.
    """
    prefix = f"{role_dir}{os.sep}"
    found = [
        str(path.relative_to(role_dir))
        for path in sorted(
            Path(p) for p in iter_project_files() if p.startswith(prefix)
        )
        if path.is_file()
        and path.suffix in (".yml", ".j2", ".sh", ".py", ".js")
        and path
        not in (
            role_dir / ROLE_FILE_VARS_MAIN,
            role_dir / ROLE_FILE_META_SECRETS,
            role_dir / WRITER,
        )
        and PRIVATE_READ.search(read_text(str(path)))
    ]
    found.extend(
        name
        for name, value in variables.items()
        if name != PRIVATE
        and name not in PRIVATE_READERS
        and PRIVATE_READ.search(str(value))
    )
    return found


def ungated_includes(inputs, role_dir):
    """Args:
    inputs: the parsed ``tasks/utils/project/inputs.yml``.
    role_dir: the role directory.

    Returns:
        Every task file of the role that reads the workspace fixture key and
        is neither included from ``inputs`` under the fixture gate nor
        reached through such a file.
    """
    tasks_dir = role_dir / "tasks"
    gated = {
        str(target.relative_to(tasks_dir))
        for task in gated_tasks(inputs)
        if (target := included(task)) is not None and GATE in conditions(task)
    }
    readers = sorted(
        str(Path(path).relative_to(tasks_dir))
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(f"{tasks_dir}{os.sep}") and READS.search(read_text(path))
    )
    return [reader for reader in readers if reader not in gated]


def env_render(template, enabled, holder_defined=True):
    """Args:
    template: the text of ``templates/playwright.env.j2``.
    enabled: the value of ``SEMAPHORE_DEPLOY_FIXTURE_ENABLED``.
    holder_defined: whether the fixture set the target's holder key fact.

    Returns:
        ``{name: rendered value}`` of the ``ENV_NAMES`` lines, the target
        vars rendered from the role var as the deploy would.
    """
    variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
    environment = jinja()
    context = {
        "SEMAPHORE_DEPLOY_FIXTURE_ENABLED": enabled,
        "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH": "fixture/platform/workspace-ssh",
        "SEMAPHORE_DEPLOY_FIXTURE_VARS": {
            "users": {"root": {"authorized_keys": ["DEPLOY", "HOLDER", WORKSPACE_LINE]}}
        },
    }
    if holder_defined:
        context["semaphore_deploy_fixture_holder_key"] = "HOLDER"
    expression = variables[TARGET_VARS].strip().removeprefix("{{").removesuffix("}}")
    context[TARGET_VARS] = environment.compile_expression(expression)(**context)
    found = {}
    for line in template.splitlines():
        name, _, value = line.partition("=")
        if name in ENV_NAMES:
            found[name] = json.loads(environment.from_string(value).render(**context))
            if name.endswith("_JSON"):
                found[name] = json.loads(found[name])
    return found


def production_findings(template):
    """Args:
    template: the text of ``templates/playwright.env.j2``.

    Returns:
        One message per ``ENV_NAMES`` line a render with the fixture off
        fills, and one per line a render with the fixture on leaves empty.
    """
    off, on = env_render(template, False), env_render(template, True)
    findings = [f"{name} is missing" for name in ENV_NAMES if name not in off]
    findings.extend(
        f"{name} carries a value with the fixture off"
        for name, value in off.items()
        if value
    )
    findings.extend(
        f"{name} is empty with the fixture on"
        for name, value in on.items()
        if not value
    )
    return findings


def authorize_findings(variables, fixture_tasks):
    """Args:
    variables: the role vars.
    fixture_tasks: the parsed ``tasks/utils/project/fixture.yml``.

    Returns:
        One message per place the shared target misses the public half of
        the workspace fixture key, or the platform account gains it, and one
        when the distinct-key assert does not run before the authorization.
    """
    findings = []
    users = variables["SEMAPHORE_DEPLOY_FIXTURE_VARS"]["users"]
    line = f"{{{{ {PUBLIC} }}}}"
    if line not in users["root"]["authorized_keys"]:
        findings.append(
            "SEMAPHORE_DEPLOY_FIXTURE_VARS authorizes no workspace fixture key for root"
        )
    if line in users["administrator"]["authorized_keys"]:
        findings.append(
            "SEMAPHORE_DEPLOY_FIXTURE_VARS authorizes the workspace fixture key for administrator"
        )
    tasks = list(_tasks(fixture_tasks))
    authorize = [i for i, t in enumerate(tasks) if line in (t.get("loop") or [])]
    checks = [
        i
        for i, t in enumerate(tasks)
        if "ansible.builtin.assert" in t
        and PUBLIC in str(t.get("vars"))
        and all(f"'{name}'" in str(t.get("vars")) for name in (*OTHER_KEYS, "target"))
        and "semaphore_deploy_fixture_holder_key" in str(t.get("vars"))
    ]
    if not authorize:
        findings.append(
            "fixture.yml authorizes no workspace fixture key on the shared target"
        )
    if not checks or (authorize and checks[0] > authorize[0]):
        findings.append("no distinct-key assert runs before the authorization")
    return findings


def policy_findings(variables, openbao_vars, policy):
    """Args:
    variables: the role vars.
    openbao_vars: the vars of ``web-app-openbao``.
    policy: the text of ``templates/policies/playwright.hcl.j2``.

    Returns:
        One message when the Playwright AppRole cannot read the path the
        writer fills, under the mount the fixture writes to.
    """
    literal = {
        k: v for k, v in openbao_vars.items() if isinstance(v, str) and "{{" not in v
    }
    rendered = jinja().from_string(policy).render(**literal)
    root = (
        jinja()
        .from_string(variables["SEMAPHORE_DEPLOY_FIXTURE_BAO_ROOT"])
        .render(
            SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_HOST=variables[
                "SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_HOST"
            ]
        )
    )
    path = (
        jinja()
        .from_string(variables["SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH"])
        .render(SEMAPHORE_DEPLOY_FIXTURE_BAO_ROOT=root)
    )
    request = f"{variables['SEMAPHORE_DEPLOY_FIXTURE_BAO_MOUNT']}/data/{path}"
    readable = [
        pattern
        for pattern, caps in re.findall(
            r'path "([^"]+)" \{\s*capabilities = \[([^\]]*)\]', rendered
        )
        if '"read"' in caps
        and re.fullmatch(re.escape(pattern).replace(r"\+", "[^/]+"), request)
    ]
    return [] if readable else [f"the Playwright policy reads no {request}"]


class TestTheWorkspaceFixtureKey(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.template = read_text(str(ENV_TEMPLATE))

    def test_the_key_is_a_generated_ed25519_credential_of_its_own(self):
        secrets = load_yaml_any(str(ROLE / ROLE_FILE_META_SECRETS))["credentials"]
        self.assertEqual(
            secrets[CREDENTIAL]["algorithm"], secrets["deploy_ssh_key"]["algorithm"]
        )
        self.assertEqual(source_findings(self.vars), [])

    def test_negative_control_a_key_shared_with_root_or_deploy_is_caught(self):
        for credential in ("fixture_ssh_key", "deploy_ssh_key", "app_control_ssh_key"):
            with self.subTest(credential=credential):
                planted = {
                    **self.vars,
                    PRIVATE: f"{{{{ lookup('config', application_id, 'secrets.credentials.{credential}') }}}}",
                }
                self.assertNotEqual(source_findings(planted), [])

    def test_only_the_target_root_holds_the_public_half_after_the_distinct_assert(self):
        self.assertEqual(authorize_findings(self.vars, load_yaml_any(str(FIXTURE))), [])

    def test_negative_control_an_authorization_without_the_assert_is_caught(self):
        tasks = [
            t for t in load_yaml_any(str(FIXTURE)) if "ansible.builtin.assert" not in t
        ]
        self.assertEqual(
            authorize_findings(self.vars, tasks),
            ["no distinct-key assert runs before the authorization"],
        )

    def test_every_task_reading_the_key_waits_for_the_fixture(self):
        self.assertEqual(ungated_includes(load_yaml_any(str(INPUTS)), ROLE), [])

    def test_negative_control_an_ungated_include_is_caught(self):
        inputs = [
            {k: v for k, v in t.items() if k != "when"} if included(t) == FIXTURE else t
            for t in load_yaml_any(str(INPUTS))
        ]
        self.assertEqual(
            ungated_includes(inputs, ROLE),
            ["utils/project/fixture.yml", "utils/project/fixture/credentials.yml"],
        )

    def test_the_fixture_off_renders_no_key_path_and_no_root_key(self):
        self.assertEqual(production_findings(self.template), [])
        self.assertEqual(
            env_render(self.template, True, holder_defined=False)[
                "SEMAPHORE_DEPLOY_TARGET_VARS_JSON"
            ],
            {},
        )
        self.assertIn(
            WORKSPACE_LINE,
            env_render(self.template, True)["SEMAPHORE_DEPLOY_TARGET_VARS_JSON"][
                "users"
            ]["root"]["authorized_keys"],
        )

    def test_the_target_vars_the_specs_commit_read_no_credential(self):
        scope = fixture_scope()
        self.assertEqual(credential_reads(f"{{{{ {TARGET_VARS} }}}}", scope), [])
        planted = {
            **scope,
            "SEMAPHORE_DEPLOY_FIXTURE_VARS": {
                **scope["SEMAPHORE_DEPLOY_FIXTURE_VARS"],
                "planted": f"{{{{ {PRIVATE} }}}}",
            },
        }
        self.assertNotEqual(credential_reads(f"{{{{ {TARGET_VARS} }}}}", planted), [])

    def test_negative_control_an_ungated_env_line_is_caught(self):
        planted = self.template.replace(
            "(SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH if SEMAPHORE_DEPLOY_FIXTURE_ENABLED | bool else '')",
            "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH",
        )
        self.assertNotEqual(planted, self.template)
        self.assertEqual(
            production_findings(planted),
            [
                "SEMAPHORE_WORKSPACE_FIXTURE_KEY_PATH carries a value with the fixture off"
            ],
        )

    def test_the_private_half_is_read_by_the_writer_alone(self):
        self.assertEqual(private_findings(ROLE, self.vars), [])

    def test_negative_control_a_private_half_read_elsewhere_is_caught(self):
        planted = {**self.vars, "PLANTED": f"{{{{ {PRIVATE} }}}}"}
        self.assertEqual(private_findings(ROLE, planted), ["PLANTED"])

    def test_the_playwright_approle_reads_the_path_the_writer_fills(self):
        policy = read_text(
            str(OPENBAO / "templates" / "policies" / "playwright.hcl.j2")
        )
        openbao_vars = load_yaml_any(str(OPENBAO / ROLE_FILE_VARS_MAIN))
        self.assertEqual(policy_findings(self.vars, openbao_vars, policy), [])
        drifted = {
            **self.vars,
            "SEMAPHORE_DEPLOY_FIXTURE_WORKSPACE_KEY_PATH": "{{ SEMAPHORE_DEPLOY_FIXTURE_BAO_ROOT }}/ssh",
        }
        self.assertNotEqual(policy_findings(drifted, openbao_vars, policy), [])


if __name__ == "__main__":
    unittest.main()
