from __future__ import annotations

import posixpath
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = ROLES_DIR / "web-app-semaphore"
FIXTURE = ROLE / "tasks" / "utils" / "project" / "fixture.yml"
REPOSITORY = ROLE / "tasks" / "utils" / "project" / "fixture" / "repository.yml"
COMMIT = ROLE / "tasks" / "utils" / "project" / "fixture" / "commit.yml"
PLATFORM = ROLE / "tasks" / "utils" / "project" / "fixture" / "platform.yml"
SYNC = ROLE / "tasks" / "utils" / "project" / "sync.yml"
PROVISION_MODULE = "cli.administration.inventory.provision"
COMMIT_FACT = "semaphore_deploy_fixture_commit"
PLATFORM_FACT = "semaphore_deploy_fixture_platform_files"
PLATFORM_FILTERS = {
    "{{ SEMAPHORE_WORKSPACES_INVENTORY_FILE }}": re.compile(
        r"\| semaphore_fixture_workspaces\("
    ),
    "{{ ['host_vars', SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_HOST ~ '.yml'] | path_join }}": re.compile(
        r"\| semaphore_fixture_host_vars\(SEMAPHORE_DEPLOY_FIXTURE_REFERENCES,"
    ),
}
INVENTORY_FINDINGS = "semaphore_fixture_inventory_findings"
INVENTORY_VAR = "semaphore_deploy_fixture_inventory"
PASSWORD_VAR = "semaphore_deploy_fixture_password_file"
LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")
REFERENCE = re.compile(r"(?<![.\w])([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)*)")
ONE_WAY = re.compile(r"[A-Za-z_][\w.]*\s*\|\s*ssh_public_key\b")
DIGEST = re.compile(r"\|\s*hash\('sha256'\)\s*\}\}\s*$")
CREDENTIAL_READ = re.compile(
    r"secrets\.credentials|lookup\('users'[^)]*\)\.password|vault_password|repository\.key"
)
SCRATCH = "/scratch/fixture"


def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def fixture_scope():
    """Returns:
    Every name a committed value can read: the role vars, the facts of
    ``tasks/utils/project/fixture.yml`` and the include vars of
    ``tasks/utils/project/fixture/repository.yml``.
    """
    scope = dict(load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN)))
    for path in (FIXTURE, PLATFORM):
        for task in _tasks(load_yaml_any(str(path))):
            scope.update(task.get("ansible.builtin.set_fact") or {})
    for task in _tasks(load_yaml_any(str(REPOSITORY))):
        scope.update(task.get("vars") or {})
    return scope


def committed_values(commit_tasks):
    """Args:
    commit_tasks: the parsed ``tasks/utils/project/fixture/commit.yml``.

    Returns:
        The raw argv of the provision call, whose inputs end up in the
        provisioned inventory, every list the commit writes into that
        inventory and every value the commit fact collects.
    """
    found = []
    for task in _tasks(commit_tasks):
        argv = (task.get("ansible.builtin.command") or {}).get("argv") or []
        if PROVISION_MODULE in argv:
            found.extend(argv)
        dest = str((task.get("ansible.builtin.copy") or {}).get("dest", ""))
        if dest.startswith(f"{{{{ [{INVENTORY_VAR},"):
            found.append(task.get("loop"))
        fact = (task.get("ansible.builtin.set_fact") or {}).get(COMMIT_FACT)
        if fact is not None:
            found.append(fact)
    return found


def unfiltered_platform_files(files):
    """Args:
    files: the ``semaphore_deploy_fixture_platform_files`` fact as declared.

    Returns:
        The path of every platform file whose content does not pass the
        filter that keeps only host names or OpenBao references.
    """
    return [
        entry["path"]
        for entry in files
        if entry["path"] not in PLATFORM_FILTERS
        or not PLATFORM_FILTERS[entry["path"]].search(
            " ".join(str(entry["content"]).split())
        )
    ]


def _converged(node, name):
    if isinstance(node, list):
        return next((found for item in node if (found := _converged(item, name))), None)
    if isinstance(node, dict):
        if name in (node.get("vars") or {}):
            return node["vars"][name]
        return _converged(node.get("block"), name)
    return None


def inventory_findings(variables, commit_tasks, platform_files, sync_tasks):
    """Args:
    variables: the role vars.
    commit_tasks: the parsed ``tasks/utils/project/fixture/commit.yml``.
    platform_files: the ``semaphore_deploy_fixture_platform_files`` fact.
    sync_tasks: the parsed ``tasks/utils/project/sync.yml``.

    Returns:
        One message per way the ``deploy`` template could reach the platform
        host or the Workspaces project could read another inventory.
    """
    findings = []
    argv = next(
        a
        for t in _tasks(commit_tasks)
        if PROVISION_MODULE
        in (a := (t.get("ansible.builtin.command") or {}).get("argv") or [])
    )
    if argv[argv.index("--host") + 1] != "{{ SEMAPHORE_DEPLOY_FIXTURE_HOST }}":
        findings.append(
            "the provision of devices.yml names another host than the target"
        )
    if (
        variables["SEMAPHORE_DEPLOY_FIXTURE_HOST"]
        == variables["SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_HOST"]
    ):
        findings.append("the target and the platform host share a name")
    if (
        variables["SEMAPHORE_WORKSPACES_INVENTORY_FILE"]
        == variables["SEMAPHORE_DEPLOY_INVENTORY_FILE"]
    ):
        findings.append(
            "the Workspaces project and the deploy template share an inventory file"
        )
    if (
        variables["SEMAPHORE_WORKSPACES_VARIABLES"]["WORKSPACE_INVENTORY_FILE"]
        != "{{ SEMAPHORE_WORKSPACES_INVENTORY_FILE }}"
    ):
        findings.append(
            "WORKSPACE_INVENTORY_FILE names another file than workspaces.yml"
        )
    deploy = _converged(sync_tasks, "semaphore_project_deploy") or {}
    if (deploy.get("task_template") or {}).get(
        "playbook"
    ) != "{{ SEMAPHORE_DEPLOY_INVENTORY_FILE }}":
        findings.append("the deploy template runs another inventory than devices.yml")
    if [entry["path"] for entry in platform_files][:1] != [
        "{{ SEMAPHORE_WORKSPACES_INVENTORY_FILE }}"
    ]:
        findings.append(
            "the platform host is written to another inventory than workspaces.yml"
        )
    checks = [
        i
        for i, t in enumerate(_tasks(commit_tasks))
        if INVENTORY_FINDINGS in str(t.get("vars"))
    ]
    collect = [
        i for i, t in enumerate(_tasks(commit_tasks)) if "ansible.builtin.find" in t
    ]
    if not checks or not collect or checks[0] > collect[0]:
        findings.append("no inventory check runs before the commit collects its files")
    return findings


def _resolve(name, attributes, scope):
    value = scope[name]
    for attribute in attributes:
        if not isinstance(value, dict) or attribute not in value:
            return value
        value = value[attribute]
    return value


def credential_reads(raw, scope):
    """Args:
    raw: a committed value as the role declares it, before templating.
    scope: as ``fixture_scope`` returns it.

    Returns:
        The raw text of the value and of everything it reads, transitively,
        that reads a credential; a public key derived by ``ssh_public_key``
        and an expression that ends in a sha256 digest count as no read.
    """
    found, pending, seen = [], [raw], set()
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
            continue
        if isinstance(value, list):
            pending.extend(value)
            continue
        text = str(value)
        if DIGEST.search(text):
            continue
        text = ONE_WAY.sub("", text)
        if CREDENTIAL_READ.search(text):
            found.append(text)
        for name, path in REFERENCE.findall(LITERAL.sub("", text)):
            key = name + path
            if name in scope and key not in seen:
                seen.add(key)
                pending.append(_resolve(name, path.split(".")[1:], scope))
    return found


def password_outside_inventory(scope):
    """Args:
    scope: as ``fixture_scope`` returns it.

    Returns:
        True when the vault password file and the committed inventory are
        two different children of the scratch directory, so the commit,
        which collects the inventory tree alone, never reaches the file.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["path_join"] = lambda parts: posixpath.join(*parts)
    facts = {"semaphore_deploy_fixture_scratch": {"path": SCRATCH}}
    inventory = env.from_string(str(scope[INVENTORY_VAR])).render(**facts)
    password = env.from_string(str(scope[PASSWORD_VAR])).render(
        **facts, **{INVENTORY_VAR: inventory}
    )
    children = {posixpath.dirname(inventory), posixpath.dirname(password)}
    return children == {SCRATCH} and inventory != password


class TestFixtureCommit(unittest.TestCase):
    def setUp(self):
        self.scope = fixture_scope()
        self.commit = load_yaml_any(str(COMMIT))

    def test_the_fixture_commits_no_live_credential(self):
        values = committed_values(self.commit)
        self.assertIn("{{ SEMAPHORE_DEPLOY_FIXTURE_VARS | to_json }}", values)
        self.assertEqual(
            [read for value in values for read in credential_reads(value, self.scope)],
            [],
        )

    def test_a_planted_credential_in_the_inventory_vars_is_caught(self):
        for planted in (
            "{{ SEMAPHORE_DEPLOY_PRIVATE_KEY }}",
            "{{ lookup('users', 'platform_administrator').password }}",
            "{{ SEMAPHORE_DEPLOY_VAULT_PASSWORD }}",
            "{{ lookup('config', 'web-app-keycloak', 'secrets.credentials.administrator_password') }}",
        ):
            with self.subTest(planted=planted):
                scope = {
                    **self.scope,
                    "SEMAPHORE_DEPLOY_FIXTURE_VARS": {
                        **self.scope["SEMAPHORE_DEPLOY_FIXTURE_VARS"],
                        "planted": planted,
                    },
                }
                values = committed_values(self.commit)
                self.assertNotEqual(
                    [
                        read
                        for value in values
                        for read in credential_reads(value, scope)
                    ],
                    [],
                )

    def test_a_public_key_without_its_derivation_is_caught(self):
        scope = {
            **self.scope,
            "SEMAPHORE_DEPLOY_FIXTURE_PUBLIC_KEY": "{{ SEMAPHORE_DEPLOY_PRIVATE_KEY }}",
        }
        self.assertNotEqual(
            credential_reads("{{ SEMAPHORE_DEPLOY_FIXTURE_VARS | to_json }}", scope), []
        )

    def test_an_openbao_reference_commits_no_credential(self):
        scope = {
            **self.scope,
            "SEMAPHORE_DEPLOY_FIXTURE_VARS": {
                **self.scope["SEMAPHORE_DEPLOY_FIXTURE_VARS"],
                "applications": {
                    "web-app-keycloak": {
                        "secrets": {
                            "credentials": {
                                "administrator_password": {
                                    "openbao": "platform/fixture/web-app-keycloak#administrator_password"
                                }
                            }
                        }
                    }
                },
            },
        }
        self.assertEqual(
            credential_reads("{{ SEMAPHORE_DEPLOY_FIXTURE_VARS | to_json }}", scope), []
        )

    def test_the_vault_password_file_lies_outside_the_committed_inventory(self):
        self.assertTrue(password_outside_inventory(self.scope))

    def test_a_password_file_inside_the_inventory_is_caught(self):
        for planted in (
            "{{ [semaphore_deploy_fixture_inventory, 'vault-password'] | path_join }}",
            "{{ [semaphore_deploy_fixture_scratch.path, 'inventory'] | path_join }}",
        ):
            with self.subTest(planted=planted):
                scope = {**self.scope, PASSWORD_VAR: planted}
                self.assertFalse(password_outside_inventory(scope))

    def test_the_platform_files_reach_the_commit_only_through_their_filters(self):
        self.assertIn("{{ " + PLATFORM_FACT + " }}", committed_values(self.commit))
        self.assertEqual(unfiltered_platform_files(self.scope[PLATFORM_FACT]), [])

    def test_negative_control_raw_platform_host_vars_are_caught(self):
        files = [
            *self.scope[PLATFORM_FACT][:1],
            {
                "path": self.scope[PLATFORM_FACT][1]["path"],
                "content": "{{ semaphore_deploy_fixture_platform_sources.results[1].content | b64decode }}",
            },
        ]
        self.assertEqual(unfiltered_platform_files(files), [files[1]["path"]])

    def test_devices_and_workspaces_are_two_inventories(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(variables["SEMAPHORE_DEPLOY_INVENTORY_FILE"], "devices.yml")
        self.assertEqual(
            variables["SEMAPHORE_WORKSPACES_INVENTORY_FILE"], "workspaces.yml"
        )
        self.assertEqual(
            inventory_findings(
                variables,
                self.commit,
                self.scope[PLATFORM_FACT],
                load_yaml_any(str(SYNC)),
            ),
            [],
        )

    def test_negative_control_a_platform_host_planted_in_devices_is_caught(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        sync = load_yaml_any(str(SYNC))
        planted_commit = [
            {
                "ansible.builtin.command": {
                    "argv": [
                        PROVISION_MODULE,
                        "--host",
                        "{{ SEMAPHORE_DEPLOY_FIXTURE_PLATFORM_HOST }}",
                    ]
                }
            },
            *self.commit,
        ]
        planted_vars = {
            **variables,
            "SEMAPHORE_WORKSPACES_VARIABLES": {
                **variables["SEMAPHORE_WORKSPACES_VARIABLES"],
                "WORKSPACE_INVENTORY_FILE": "{{ SEMAPHORE_DEPLOY_INVENTORY_FILE }}",
            },
        }
        reversed_files = list(reversed(self.scope[PLATFORM_FACT]))
        for label, args, finding in (
            (
                "provision",
                (variables, planted_commit, self.scope[PLATFORM_FACT], sync),
                "the provision of devices.yml names another host than the target",
            ),
            (
                "environment",
                (planted_vars, self.commit, self.scope[PLATFORM_FACT], sync),
                "WORKSPACE_INVENTORY_FILE names another file than workspaces.yml",
            ),
            (
                "files",
                (variables, self.commit, reversed_files, sync),
                "the platform host is written to another inventory than workspaces.yml",
            ),
        ):
            with self.subTest(planted=label):
                self.assertEqual(inventory_findings(*args), [finding])


if __name__ == "__main__":
    unittest.main()
