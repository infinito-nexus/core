from __future__ import annotations

import unittest

from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
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
        self.assertIn("{{ " + KEY + " }}", read_text(str(SWARM_IMPORT)))

    def test_the_truststore_and_the_mount_share_one_gate(self) -> None:
        env = read_text(str(ENV_TEMPLATE))
        self.assertIn("{% if lookup('ca_injected', application_id) %}", env)
        self.assertIn("KC_TRUSTSTORE_PATHS={{ CA_TRUST.inject_cert_container }}", env)
        self.assertIn(
            "lookup('ca_injected', application_id)",
            load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))[KEY],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
