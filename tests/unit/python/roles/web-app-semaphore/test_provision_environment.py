from __future__ import annotations

import ast
import copy
import unittest

from ansible.plugins.filter.core import combine
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.container_volumes import container_volumes
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

ROLE_ID = "web-app-semaphore"
ROLE = PROJECT_ROOT / "roles" / ROLE_ID
PROVISION = ROLE / "files" / "python" / "provision.py"
README = ROLE / "README.md"
CATALOGS = "semaphore_provision_catalogs"
RUNNER = "provision-runner"
OTHER_RUNNERS = ("task-runner", "deploy-runner", "workspaces-runner", "export-runner")
HOST_DIR = "/opt/compositions/web-app-semaphore/catalogs"
PLANTED_ROLE = "x-planted-semaphore"


def read_names(source):
    """Args:
        source: the text of ``provision.py``.

    Returns:
        Every environment name ``configuration`` reads through
        ``inputs.required`` or ``env.get``.
    """
    function = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "configuration"
    )
    names = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not isinstance(owner, ast.Name):
            continue
        if (owner.id, node.func.attr) == ("inputs", "required"):
            names.add(node.args[1].value)
        elif (owner.id, node.func.attr) == ("env", "get"):
            names.add(node.args[0].value)
    return names


def converge_task():
    """Returns:
    The task of ``tasks/utils/workspace/operation.yml`` that hands the spec to
    ``project.py``.
    """
    tasks = load_yaml_str(
        read_text(str(ROLE / "tasks" / "utils" / "workspace" / "operation.yml"))
    )
    return next(t for t in tasks if "semaphore_workspace_spec" in t.get("vars", {}))


def provision_environment(task, variables):
    """Args:
        task: the result of :func:`converge_task`.
        variables: ``SEMAPHORE_PROVISION_VARIABLES``.

    Returns:
        The provision environment the task hands ``project.py``, each value
        still its expression.
    """
    environment = NativeEnvironment(undefined=StrictUndefined)
    environment.filters["combine"] = combine
    expression = task["vars"]["semaphore_workspace_spec"]["provision"]["environment"]
    return environment.from_string(expression).render(
        SEMAPHORE_PROVISION_VARIABLES=variables,
        semaphore_workspace_provision_values=task["vars"][
            "semaphore_workspace_provision_values"
        ],
    )


def environment_findings(names, environment):
    """Args:
        names: the names the provision script reads.
        environment: the provision environment of the templates.

    Returns:
        One finding per name the environment does not set.
    """
    return [f"{name} is not set" for name in sorted(names - set(environment))]


def render(expression):
    if "'catalogs' ]" in expression:
        return HOST_DIR
    if ".enabled') | bool" in expression:
        return "True"
    if "'services.task-runner.name') }}" in expression:
        return "/home/semaphore-runner"
    raise AssertionError(f"unexpected expression {expression!r}")


def mount_findings(applications, application_id, target):
    """Args:
        applications: the applications ``container_volumes`` reads.
        application_id: the role whose volumes it renders.
        target: the container path of the catalog mount.

    Returns:
        One finding per runner whose catalog mount is not exactly the
        read-only mount of the provision runner.
    """
    findings = []
    for service in (RUNNER, *OTHER_RUNNERS):
        block = load_yaml_str(
            container_volumes(
                applications, application_id, service, render_jinja=render
            )
        )
        mounted = [
            volume
            for volume in block.get("volumes", [])
            if isinstance(volume, str) and f":{target}" in volume
        ]
        expected = [f"{HOST_DIR}:{target}:ro"] if service == RUNNER else []
        if mounted != expected:
            findings.append(f"{service} mounts {mounted}, expected {expected}")
    return findings


class TestProvisionEnvironment(unittest.TestCase):
    def setUp(self):
        self.source = read_text(str(PROVISION))
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.variables = self.vars["SEMAPHORE_PROVISION_VARIABLES"]
        self.task = converge_task()

    def test_the_provision_environment_sets_every_name_the_script_reads(self):
        names = read_names(self.source)
        self.assertTrue(names)
        environment = provision_environment(self.task, self.variables)
        self.assertEqual(environment_findings(names, environment), [])

    def test_the_platform_values_reuse_the_role_values(self):
        self.assertEqual(
            self.variables["BAO_ADDR"], "{{ SEMAPHORE_WORKSPACES_VARIABLES.BAO_ADDR }}"
        )
        self.assertEqual(
            self.variables["PROVISION_CA_FILE"],
            "{{ CA_TRUST_CERT_CONTAINER_SELFSIGNED }}",
        )
        self.assertEqual(
            self.variables["PROVISION_DNS_FLAVOR"], "{{ SEMAPHORE_DNS_FLAVOR }}"
        )
        self.assertEqual(
            self.variables["PROVISION_STATE_ENDPOINT"],
            "{{ lookup('canonical_url', 'web-svc-seaweedfs', 'api') }}",
        )
        self.assertEqual(
            self.variables["PROVISION_CATALOG_DIR"],
            "{{ SEMAPHORE_WORKSPACE_CATALOG_DIR }}",
        )

    def test_negative_control_a_dropped_platform_variable_is_reported(self):
        variables = {
            k: v for k, v in self.variables.items() if k != "PROVISION_CATALOG_DIR"
        }
        environment = provision_environment(self.task, variables)
        self.assertEqual(
            environment_findings(read_names(self.source), environment),
            ["PROVISION_CATALOG_DIR is not set"],
        )

    def test_negative_control_a_new_name_of_the_script_is_reported(self):
        planted = self.source.replace(
            '"flavor": flavor,',
            '"flavor": flavor, "planted": inputs.required(env, "PROVISION_PLANTED"),',
        )
        self.assertNotEqual(planted, self.source)
        environment = provision_environment(self.task, self.variables)
        self.assertEqual(
            environment_findings(read_names(planted), environment),
            ["PROVISION_PLANTED is not set"],
        )


class TestCatalogMount(unittest.TestCase):
    def setUp(self):
        self.volumes = load_yaml_any(str(ROLE / ROLE_FILE_META_VOLUMES))
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.target = self.volumes[CATALOGS]["mounts"][0]["target"]

    def planted(self, change):
        volumes = copy.deepcopy(self.volumes)
        change(volumes[CATALOGS])
        return {PLANTED_ROLE: {"volumes": volumes}}

    def test_the_catalogs_mount_read_only_into_the_provision_runner_only(self):
        self.assertEqual(mount_findings({}, ROLE_ID, self.target), [])

    def test_the_mount_is_the_directory_the_deploy_writes(self):
        source = self.volumes[CATALOGS]["source"].replace(
            f"'{ROLE_ID}'", "application_id"
        )
        self.assertEqual(source, self.vars["SEMAPHORE_WORKSPACE_CATALOG_DIR_HOST"])
        catalog = read_text(str(ROLE / "tasks" / "utils" / "catalog.yml"))
        self.assertIn(
            "[SEMAPHORE_WORKSPACE_CATALOG_DIR_HOST, semaphore_catalog.key", catalog
        )

    def test_the_catalog_dir_of_the_script_is_the_mount_target(self):
        self.assertEqual(
            self.vars["SEMAPHORE_WORKSPACE_CATALOG_DIR"],
            f"{{{{ lookup('volume', application_id, '{CATALOGS}').target }}}}",
        )
        self.assertEqual(
            self.vars["SEMAPHORE_PROVISION_VARIABLES"]["PROVISION_CATALOG_DIR"],
            "{{ SEMAPHORE_WORKSPACE_CATALOG_DIR }}",
        )
        self.assertEqual(
            {m["target"] for m in self.volumes[CATALOGS]["mounts"]}, {self.target}
        )

    def test_negative_control_a_writable_mount_is_reported(self):
        def writable(entry):
            entry["read_only"] = False

        mounted = f"['{HOST_DIR}:{self.target}']"
        expected = f"['{HOST_DIR}:{self.target}:ro']"
        self.assertEqual(
            mount_findings(self.planted(writable), PLANTED_ROLE, self.target),
            [f"{RUNNER} mounts {mounted}, expected {expected}"],
        )

    def test_negative_control_a_mount_on_another_runner_is_reported(self):
        def moved(entry):
            entry["mounts"][0]["service"] = "export-runner"

        self.assertEqual(
            mount_findings(self.planted(moved), PLANTED_ROLE, self.target),
            [
                f"{RUNNER} mounts [], expected ['{HOST_DIR}:{self.target}:ro']",
                f"export-runner mounts ['{HOST_DIR}:{self.target}:ro'], expected []",
            ],
        )


def readme_findings(text, variables):
    """Args:
        text: the README.
        variables: ``SEMAPHORE_PROVISION_VARIABLES``.

    Returns:
        One finding per platform variable the README does not name.
    """
    return [f"{name} is not named" for name in variables if f"`{name}`" not in text]


class TestProvisionEnvironmentReadme(unittest.TestCase):
    def setUp(self):
        self.text = read_text(str(README))
        self.variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))[
            "SEMAPHORE_PROVISION_VARIABLES"
        ]

    def test_the_readme_names_the_provision_environment(self):
        self.assertEqual(readme_findings(self.text, self.variables), [])
        self.assertIn("`SEMAPHORE_PROVISION_VARIABLES`", self.text)

    def test_negative_control_a_dropped_name_is_reported(self):
        planted = self.text.replace("`PROVISION_CATALOG_DIR`", "")
        self.assertEqual(
            readme_findings(planted, self.variables),
            ["PROVISION_CATALOG_DIR is not named"],
        )


if __name__ == "__main__":
    unittest.main()
