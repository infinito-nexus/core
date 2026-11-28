from __future__ import annotations

import shlex
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
SWARM_IMPORT = ROLE / "tasks" / "04_realm_import" / "swarm.yml"
ENV_TEMPLATE = ROLE / "templates" / "env.j2"
KEY = "KEYCLOAK_IMPORT_CA_MOUNT_ARG"
CA_TRUST = {
    "cert_host": "/etc/infinito/ca/root-ca.crt",
    "inject_cert_container": "/tmp/infinito/ca/root-ca.crt",
}


def _render(injected: bool) -> str:
    variables = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
    environment = NativeEnvironment()
    environment.filters["quote"] = lambda value: value
    template = environment.from_string(variables[KEY])
    return template.render(
        lookup=lambda kind, *_terms: injected if kind == "ca_injected" else "",
        application_id="web-app-keycloak",
        CA_TRUST=CA_TRUST,
    )


def _environment() -> Environment:
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["quote"] = shlex.quote
    environment.filters["entity_name"] = lambda _app: "keycloak"
    return environment


def _import_job_mounts(injected: bool) -> list[str]:
    """
    Args:
        injected: what lookup('ca_injected', application_id) answers.

    Returns:
        Every ``--mount`` value of the rendered ``container service create``
        call of the swarm realm import job.
    """
    task = next(
        task
        for task in load_yaml_any(str(SWARM_IMPORT))
        if "Run one-shot import job" in task.get("name", "")
    )
    rendered = (
        _environment()
        .from_string(task["ansible.builtin.shell"])
        .render(
            lookup=lambda *_terms: "x",
            application_id="web-app-keycloak",
            entity_name="keycloak",
            KEYCLOAK_DB_NETWORK_ARG="",
            KEYCLOAK_REALM_IMPORT_DIR_HOST="/opt/compose/keycloak/import",
            KEYCLOAK_REALM_IMPORT_DIR_DOCKER="/opt/keycloak/data/import",
            KEYCLOAK_IMPORT_CA_MOUNT_ARG=_render(injected) or "",
            KEYCLOAK_IMAGE="keycloak",
            KEYCLOAK_VERSION="26",
            KEYCLOAK_REALM_IMPORT_FILE_DOCKER="/opt/keycloak/data/import/realm.json",
        )
    )
    create = next(
        line
        for line in rendered.replace("\\\n", " ").splitlines()
        if line.strip().startswith("container service create")
    )
    argv = shlex.split(create)
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]


def _truststore_env(injected: bool) -> dict[str, str]:
    """
    Args:
        injected: what lookup('ca_injected', application_id) answers.

    Returns:
        The ``KEY=VALUE`` pairs the CA gate of env.j2 renders.
    """
    lines = read_text(str(ENV_TEMPLATE)).splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("{% if lookup('ca_injected'")
    )
    end = lines.index("{% endif %}", start)
    rendered = (
        _environment()
        .from_string("\n".join(lines[start : end + 1]))
        .render(
            lookup=lambda kind, *_terms: injected if kind == "ca_injected" else "",
            application_id="web-app-keycloak",
            CA_TRUST=CA_TRUST,
        )
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


class TestSwarmRealmImportTrustsTheInjectedCa(unittest.TestCase):
    def test_an_injected_ca_is_mounted_where_the_truststore_reads_it(self) -> None:
        self.assertEqual(
            _render(True),
            "--mount type=bind,source=/etc/infinito/ca/root-ca.crt,"
            "target=/tmp/infinito/ca/root-ca.crt,readonly",
        )

    def test_no_mount_without_an_injected_ca(self) -> None:
        self.assertEqual(_render(False) or "", "")

    def test_the_import_job_passes_the_mount(self) -> None:
        ca_mount = _render(True).split(" ", 1)[1]
        self.assertIn(ca_mount, _import_job_mounts(True))
        self.assertNotIn(ca_mount, _import_job_mounts(False))

    def test_the_truststore_and_the_mount_share_one_gate(self) -> None:
        ca_mount = dict(
            part.split("=", 1)
            for part in _render(True).split(" ", 1)[1].split(",")
            if "=" in part
        )
        self.assertEqual(
            _truststore_env(True), {"KC_TRUSTSTORE_PATHS": ca_mount["target"]}
        )
        self.assertEqual(_truststore_env(False), {})
        self.assertFalse(_render(False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
