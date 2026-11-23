from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

APPLICATION = "svc-bkp-volume-2-local"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
TEST_ENV = ROLE / "templates" / "test.env.j2"
SEMAPHORE_FILES = PROJECT_ROOT / "roles" / "web-app-semaphore" / "files"
SEMAPHORE_PYTHON = SEMAPHORE_FILES / "python"
INTERFACE = SEMAPHORE_FILES / "opentofu" / "interface.json"
INCUS = "svc-virt-incus"
E2E_PROVIDER = "incus"
PARTNERS = (
    "web-app-semaphore",
    "web-app-openbao",
    "web-svc-seaweedfs",
    "web-app-gitea",
)
INCUS_GATE = f"((groups.get('{INCUS}', []) | length) > 0)"
HOST_ONLY_GATE = f"('{INCUS}' in group_names)"
STACK_HOST = "stack"
TARGET_HOST = "target"
LOCAL_INCUS = {STACK_HOST: (*PARTNERS, APPLICATION, INCUS)}
REMOTE_INCUS = {STACK_HOST: (*PARTNERS, APPLICATION), TARGET_HOST: (INCUS,)}
NO_INCUS = {STACK_HOST: (*PARTNERS, APPLICATION)}
GATE = "BKP_TEST_WORKSPACES"
ORDER = "BKP_TEST_WORKSPACE_ORDER"
SOURCED = "set -a && . /dev/stdin && set +a && env -0"
STUB = "stub"
CONFIG = {
    "web-app-gitea": {
        "services": {"gitea": {"workspaces": {"enabled": True, "organization": STUB}}}
    },
    "web-svc-seaweedfs": {"services": {"seaweedfs": {"region": STUB}}},
}


def _module(name: str, path: str) -> object:
    """Args:
        name: the module name the file is loaded under.
        path: the Python file.

    Returns:
        The loaded module.
    """
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@functools.cache
def provision_inputs() -> object:
    """Returns:
    ``provision.inputs``, the module the provision runner reads the survey of
    an order template with, importable as the runner imports it.
    """
    directory = str(SEMAPHORE_PYTHON)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return _module(
        "provision.inputs", str(SEMAPHORE_PYTHON / "provision" / "inputs.py")
    )


@functools.cache
def e2e_surveys() -> dict[str, set[str]]:
    """Returns:
    The survey variable names of each order template of the Incus e2e target,
    keyed by the template name without its workspace.
    """
    project = _module("semaphore_project", str(SEMAPHORE_PYTHON / "project.py"))
    templates = {entry["name"]: entry for entry in project.PROVISION_TEMPLATES}
    return {
        name: {variable for variable, _ in templates[name]["survey"]}
        for name in (f"{action}-{E2E_PROVIDER}" for action in project.ORDER_ACTIONS)
    }


def configured_order() -> dict[str, str]:
    """Returns:
    ``services.test.workspace_order`` of the role's services file.
    """
    return load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["test"]["workspace_order"]


def _config(application: str, path: str) -> object:
    """Args:
        application: the application whose config is read.
        path: the dotted path below it.

    Returns:
        The role's own services file for this role, a stub for the others.
    """
    node = (
        {"services": load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))}
        if application == APPLICATION
        else CONFIG[application]
    )
    for key in path.split("."):
        node = node[key]
    return node


LOOKUPS = {
    "config": _config,
    "database_consumerless_volumes": list,
    "timeout": int,
    "tls": lambda application, _key: f"https://{application}.example",
    "users": lambda _user: dict.fromkeys(("username", "password"), STUB),
}


def _lookup(name: str, *terms: object) -> object:
    return LOOKUPS[name](*terms)


def render(source: str, inventory: dict[str, tuple[str, ...]]) -> str:
    """Args:
        source: a test.env.j2 source.
        inventory: the roles of each host; ``STACK_HOST`` renders.

    Returns:
        The rendered env file.
    """
    groups: dict[str, list[str]] = {}
    for host, roles in inventory.items():
        for role in roles:
            groups.setdefault(role, []).append(host)
    env = Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(CoreFilters().filters())
    env.filters.update(MathFilters().filters())
    env.filters["entity_name"] = entity_name
    admin = dict.fromkeys(("REALM", "CLI_CLIENT_ID", "PASSWORD", "USERNAME"), STUB)
    return env.from_string(source).render(
        lookup=_lookup,
        application_id=APPLICATION,
        group_names=list(inventory[STACK_HOST]),
        groups=groups,
        OIDC={"ADMIN": admin, "CLIENT": {"REALM": STUB}, "URL": "https://auth.example"},
        DIR_BACKUPS="/var/lib/backups",
        DIR_SCRIPTS_SYSTEMCTL="/opt/scripts/systemctl",
        BKP_VOLUME_2_LOCAL_DISABLED=[],
        BKP_VOLUME_2_LOCAL_MAINTENANCE_BIN="/usr/local/bin/baudolo-maintenance",
        BKP_VOLUME_2_LOCAL_STOPPING=[],
        BKP_VOLUME_2_LOCAL_VOLUMES_DISABLED=[],
        DEPLOY_IS_UPDATE=False,
        FILE_MAINTENANCE_BACKUP="/run/infinito/maintenance/backup.json",
        IS_STACK_HOST=True,
        SYS_SERVICE_BACKUP_VOLUME_2_LOCAL="svc-bkp-volume-2-local.service",
        SYS_TIMEOUT_BACKUP_SERVICES_SECONDS=600,
        ansible_python_interpreter="/usr/bin/python3",
        playbook_dir="/opt/src/infinito",
    )


def sourced(rendered: str) -> dict[str, str]:
    """Args:
        rendered: a rendered env file.

    Returns:
        The variables bash holds after sourcing it the way test-e2e-cli does.
    """
    result = subprocess.run(
        ["bash", "-c", SOURCED],
        input=rendered,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )
    if result.returncode != 0 or result.stderr:
        raise AssertionError(f"sourcing test.env failed: {result.stderr}")
    return dict(entry.split("=", 1) for entry in result.stdout.split("\0") if entry)


def order_findings(env: dict[str, str]) -> list[str]:
    """Args:
        env: the variables the sourced test.env sets.

    Returns:
        One message per reason ``drill.py task`` could not hand the order to
        an order template of the Incus e2e target, empty when it can.
    """
    if ORDER not in env:
        return [f"{ORDER} is not rendered"]
    order = json.loads(env[ORDER])
    findings = [
        f"{name} surveys {sorted(survey)}, the order holds {sorted(order)}"
        for name, survey in e2e_surveys().items()
        if set(order) != survey
    ]
    inputs = provision_inputs()
    interface = json.loads(read_text(str(INTERFACE)))
    for reader in (inputs.order_line, inputs.provider_token):
        try:
            reader(order, interface)
        except inputs.RefusedError as error:
            findings.append(str(error))
    return findings


def base_template(source: str) -> str:
    """Args:
        source: the role's test.env.j2.

    Returns:
        The template before the order was rendered: no order line and no
        Incus target in the workspace gate.
    """
    kept = [
        line
        for line in source.splitlines(keepends=True)
        if not line.startswith(f"{ORDER}=")
    ]
    return "".join(kept).replace(f" and {INCUS_GATE}", "", 1)


class TestWorkspaceOrder(unittest.TestCase):
    def test_an_incus_target_on_any_host_hands_the_drill_its_order(self) -> None:
        for name, inventory in (("local", LOCAL_INCUS), ("remote", REMOTE_INCUS)):
            with self.subTest(target=name):
                env = sourced(render(read_text(str(TEST_ENV)), inventory))
                self.assertEqual(env[GATE], "true")
                self.assertEqual(order_findings(env), [])
                self.assertEqual(json.loads(env[ORDER]), configured_order())

    def test_a_round_without_the_incus_target_skips_the_workspace_pass(
        self,
    ) -> None:
        env = sourced(render(read_text(str(TEST_ENV)), NO_INCUS))
        self.assertEqual(env[GATE], "false")
        self.assertNotIn(ORDER, env)

    def test_negative_control_the_base_template_runs_the_pass_without_an_order(
        self,
    ) -> None:
        base = base_template(read_text(str(TEST_ENV)))
        self.assertNotIn(INCUS, base)
        self.assertNotIn(ORDER, base)
        for name, inventory in (("none", NO_INCUS), ("local", LOCAL_INCUS)):
            with self.subTest(target=name):
                env = sourced(render(base, inventory))
                self.assertEqual(env[GATE], "true")
                self.assertEqual(order_findings(env), [f"{ORDER} is not rendered"])

    def test_negative_control_a_host_only_gate_skips_a_remote_target(self) -> None:
        source = read_text(str(TEST_ENV))
        planted = source.replace(INCUS_GATE, HOST_ONLY_GATE, 1)
        self.assertNotEqual(planted, source)
        self.assertEqual(sourced(render(planted, LOCAL_INCUS))[GATE], "true")
        env = sourced(render(planted, REMOTE_INCUS))
        self.assertEqual(env[GATE], "false")
        self.assertNotIn(ORDER, env)

    def test_negative_control_an_order_off_the_survey_is_reported(self) -> None:
        order = configured_order()
        cases = (
            ({**order, "LINE": "007"}, "LINE: "),
            (
                {key: value for key, value in order.items() if key != "PROVIDER_TOKEN"},
                "PROVIDER_TOKEN is missing",
            ),
            ({**order, "HOST": STUB}, f"provision-{E2E_PROVIDER} surveys"),
        )
        for planted, expected in cases:
            with self.subTest(expected=expected):
                findings = order_findings({ORDER: json.dumps(planted)})
                self.assertTrue(
                    any(finding.startswith(expected) for finding in findings),
                    findings,
                )


if __name__ == "__main__":
    unittest.main()
