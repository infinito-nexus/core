from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

ENV_TEMPLATE = "roles/web-app-keycloak/templates/env.j2"
COMPOSE_TEMPLATE = PROJECT_ROOT / "roles/web-app-keycloak" / ROLE_FILE_TEMPL_COMPOSE
CA_TRUST = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/02_tls.yml"))["CA_TRUST"]
VERIFICATION_OFF = re.compile(
    r"HOSTNAME[_-]VERIFIER|DISABLE[_-]TRUST[_-]MANAGER|TRUST[_-]ALL|INSECURE",
    re.IGNORECASE,
)


def render_env(ca_injected: bool, debug: bool) -> dict[str, str]:
    """Render Keycloak's env file and return its keys and values.

    Args:
        ca_injected: answer of lookup('ca_injected', 'web-app-keycloak').
        debug: value of KEYCLOAK_DEBUG_ENABLED.
    """

    def lookup(name, *args, **_kwargs):
        if name == "ca_injected":
            return ca_injected
        if name == "tls":
            return True
        if name == "database":
            return f"{args[1]}-of-the-database"
        raise AssertionError(f"unexpected lookup {name}{args}")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["dotenv_quote"] = str
    env.filters["bool"] = bool
    rendered = env.get_template(ENV_TEMPLATE).render(
        lookup=lookup,
        application_id="web-app-keycloak",
        HOST_TIMEZONE="UTC",
        OIDC={"URL": "https://auth.example.test"},
        CA_TRUST=CA_TRUST,
        IS_SWARM_MODE=False,
        KEYCLOAK_HEALTH_ENABLED=True,
        KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME="bootstrap",
        KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD="bootstrap-value",
        KEYCLOAK_PERMANENT_ADMIN_USERNAME="administrator",
        KEYCLOAK_PERMANENT_ADMIN_PASSWORD="administrator-value",
        KEYCLOAK_DEBUG_ENABLED=debug,
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


def verification_switches(sources: list[str]) -> list[str]:
    """Return every setting that would let Keycloak skip certificate verification.

    Args:
        sources: Keycloak's rendered env file and its raw compose template.
    """
    return sorted(
        {
            match.group(0)
            for source in sources
            for match in VERIFICATION_OFF.finditer(source)
        }
    )


class TestKeycloakVerifiesBackchannelCertificates(unittest.TestCase):
    def test_a_self_signed_deployment_trusts_the_deployment_ca(self) -> None:
        self.assertEqual(
            render_env(ca_injected=True, debug=False)["KC_TRUSTSTORE_PATHS"],
            CA_TRUST["inject_cert_container"],
        )

    def test_without_the_ca_keycloak_keeps_the_system_trust_store(self) -> None:
        self.assertNotIn(
            "KC_TRUSTSTORE_PATHS", render_env(ca_injected=False, debug=False)
        )

    def test_no_setting_turns_certificate_verification_off(self) -> None:
        for ca_injected in (True, False):
            with self.subTest(ca_injected=ca_injected):
                env = render_env(ca_injected, debug=False)
                sources = [
                    "\n".join(f"{k}={v}" for k, v in env.items()),
                    read_text(str(COMPOSE_TEMPLATE)),
                ]
                self.assertEqual(verification_switches(sources), [])

    def test_a_switch_that_turns_verification_off_is_caught(self) -> None:
        self.assertEqual(
            verification_switches(
                [
                    "KC_TLS_HOSTNAME_VERIFIER=ANY",
                    "KC_SPI_CONNECTIONS_HTTP_CLIENT_DEFAULT_DISABLE_TRUST_MANAGER=true",
                ]
            ),
            ["DISABLE_TRUST_MANAGER", "HOSTNAME_VERIFIER"],
        )


if __name__ == "__main__":
    unittest.main()
