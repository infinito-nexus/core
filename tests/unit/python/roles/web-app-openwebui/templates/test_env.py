from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-openwebui"
SOURCES = {
    "env": ROLE / "templates/env.j2",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "services": ROLE / ROLE_FILE_META_SERVICES,
    "client": ROLE / "templates/keycloak/clients.json.j2",
    "realm": PROJECT_ROOT / "roles/web-app-keycloak/templates/import/realm.json.j2",
}
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
REALM_LIFESPAN = re.compile(r'"ssoSessionMaxLifespan": (\d+),')
LIFETIME_FINDING = (
    "JWT_EXPIRES_IN is not the realm's ssoSessionMaxLifespan in every variant"
)
OIDC_BLOCK = "{% if OPENWEBUI_OIDC_ENABLED | bool %}"
OIDC_ENV = {
    "OAUTH_CLIENT_ID": "{{ OPENWEBUI_OIDC_CLIENT_ID }}",
    "OAUTH_CODE_CHALLENGE_METHOD": "S256",
    "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD": "none",
    "ENABLE_OAUTH_BACKCHANNEL_LOGOUT": "true",
}
REDIS_ENV = ("REDIS_URL", "{{ OPENWEBUI_REDIS_URL | dotenv_quote }}")
VARS = {
    "OPENWEBUI_OIDC_CLIENT_ID": "{{ lookup('config', application_id, 'services.sso.oidc.clients.web') }}",
    "OPENWEBUI_REDIS_URL": "{{ lookup('engine', 'redis', application_id, 'url') }}",
}
SHARED_CLIENT_READ = re.compile(r"OIDC\.CLIENT\.(?:ID|SECRET)\b")
CLIENT_ATTRIBUTES = (
    re.compile(r'"publicClient":\s*true\b'),
    re.compile(r'"pkce\.code\.challenge\.method":\s*"S256"'),
)


def role_sources() -> dict[str, str]:
    return {name: read_text(str(path)) for name, path in SOURCES.items()}


def env_entries(source: str) -> dict[str, tuple[str, str]]:
    """Map each ``KEY=value`` line of an env template to its value and block.

    Args:
        source: the unrendered env template.

    Returns:
        Each key mapped to its value and the opening tag of the innermost
        ``{% if %}`` block around it, empty at the top level.
    """
    blocks: list[str] = []
    entries = {}
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("{% if "):
            blocks.append(stripped)
        elif stripped.startswith("{% endif"):
            blocks.pop()
        elif match := re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", stripped):
            entries[match.group(1)] = (match.group(2), blocks[-1] if blocks else "")
    return entries


def seconds(duration: str) -> int:
    match = re.fullmatch(r"(\d+)([smhdw])", duration)
    if match is None:
        raise AssertionError(f"unparsable Open WebUI duration {duration!r}")
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


def realm_lifespan(realm: str) -> int:
    match = REALM_LIFESPAN.search(realm)
    if match is None:
        raise AssertionError("ssoSessionMaxLifespan is missing from the realm import")
    return int(match.group(1))


def findings(sources: dict[str, str]) -> list[str]:
    """What keeps Open WebUI from its own public client and its revocation store.

    Args:
        sources: the env template, vars, services and Keycloak client fragment
            of the role and the realm import, keyed as in ``SOURCES``.
    """
    entries = env_entries(sources["env"])
    variables = load_yaml_str(sources["vars"])
    services = load_yaml_str(sources["services"])
    found = [
        f"{key} is not {value} in the SSO block"
        for key, value in OIDC_ENV.items()
        if entries.get(key) != (value, OIDC_BLOCK)
    ]
    if "OAUTH_CLIENT_SECRET" in entries:
        found.append("the public client carries OAUTH_CLIENT_SECRET")
    found.extend(
        f"the env reads the shared client: {match.group(0)}"
        for match in SHARED_CLIENT_READ.finditer(sources["env"])
    )
    if entries.get(REDIS_ENV[0]) != (REDIS_ENV[1], ""):
        found.append("REDIS_URL is not rendered in every variant")
    lifetime, block = entries.get("JWT_EXPIRES_IN", ("", None))
    if block != "" or seconds(lifetime) != realm_lifespan(sources["realm"]):
        found.append(LIFETIME_FINDING)
    if entries.get("ENABLE_PERSISTENT_CONFIG") != ("false", ""):
        found.append("ENABLE_PERSISTENT_CONFIG is not false in every variant")
    found.extend(
        f"{key} is not {value}"
        for key, value in VARS.items()
        if variables.get(key) != value
    )
    if services["redis"]["enabled"] is not True:
        found.append("services.redis is not enabled in every variant")
    found.extend(
        f"the Keycloak client lacks {pattern.pattern}"
        for pattern in CLIENT_ATTRIBUTES
        if not pattern.search(sources["client"])
    )
    return found


def planted(name: str, old: str, new: str) -> list[str]:
    """Return the findings of the role sources with one text replaced.

    Args:
        name: the key of the source in ``SOURCES``.
        old: text the source holds.
        new: its replacement.
    """
    sources = role_sources()
    if old not in sources[name]:
        raise AssertionError(f"{old!r} is not in the {name} source")
    sources[name] = sources[name].replace(old, new, 1)
    return findings(sources)


class TestOpenWebuiBackchannelLogout(unittest.TestCase):
    def test_open_webui_signs_in_with_its_own_public_client_and_revokes_through_redis(
        self,
    ) -> None:
        self.assertEqual(findings(role_sources()), [])

    def test_the_shared_client_id_or_secret_is_caught(self) -> None:
        found = planted(
            "env",
            "OAUTH_CLIENT_ID={{ OPENWEBUI_OIDC_CLIENT_ID }}",
            "OAUTH_CLIENT_ID={{ OIDC.CLIENT.ID }}\nOAUTH_CLIENT_SECRET={{ OIDC.CLIENT.SECRET }}",
        )
        self.assertIn(
            "OAUTH_CLIENT_ID is not {{ OPENWEBUI_OIDC_CLIENT_ID }} in the SSO block",
            found,
        )
        self.assertIn("the public client carries OAUTH_CLIENT_SECRET", found)
        self.assertIn("the env reads the shared client: OIDC.CLIENT.SECRET", found)

    def test_a_missing_pkce_or_backchannel_switch_is_caught(self) -> None:
        self.assertEqual(
            planted("env", "OAUTH_CODE_CHALLENGE_METHOD=S256\n", ""),
            ["OAUTH_CODE_CHALLENGE_METHOD is not S256 in the SSO block"],
        )
        self.assertEqual(
            planted(
                "env",
                "ENABLE_OAUTH_BACKCHANNEL_LOGOUT=true",
                "ENABLE_OAUTH_BACKCHANNEL_LOGOUT=false",
            ),
            ["ENABLE_OAUTH_BACKCHANNEL_LOGOUT is not true in the SSO block"],
        )

    def test_redis_behind_a_switch_or_off_is_caught(self) -> None:
        line = "REDIS_URL={{ OPENWEBUI_REDIS_URL | dotenv_quote }}"
        self.assertEqual(
            planted("env", line, f"{OIDC_BLOCK}\n{line}\n{{% endif %}}"),
            ["REDIS_URL is not rendered in every variant"],
        )
        self.assertEqual(
            planted(
                "services",
                "    disabled: true\n  enabled: true",
                "    disabled: true\n  enabled: false",
            ),
            ["services.redis is not enabled in every variant"],
        )

    def test_a_token_that_outlives_the_longest_sso_session_is_caught(self) -> None:
        line = "JWT_EXPIRES_IN=10h\n"
        self.assertEqual(
            planted("env", line, "JWT_EXPIRES_IN=4w\n"), [LIFETIME_FINDING]
        )
        self.assertEqual(planted("env", line, ""), [LIFETIME_FINDING])
        self.assertEqual(
            planted(
                "realm",
                '"ssoSessionMaxLifespan": 36000,',
                '"ssoSessionMaxLifespan": 72000,',
            ),
            [LIFETIME_FINDING],
        )

    def test_a_persistent_config_is_caught(self) -> None:
        self.assertEqual(
            planted(
                "env",
                "ENABLE_PERSISTENT_CONFIG=false",
                "ENABLE_PERSISTENT_CONFIG=true",
            ),
            ["ENABLE_PERSISTENT_CONFIG is not false in every variant"],
        )

    def test_a_client_id_with_a_fallback_is_caught(self) -> None:
        self.assertEqual(
            planted(
                "vars",
                "'services.sso.oidc.clients.web') }}",
                "'services.sso.oidc.clients.web') | default(OIDC.CLIENT.ID) }}",
            ),
            [f"OPENWEBUI_OIDC_CLIENT_ID is not {VARS['OPENWEBUI_OIDC_CLIENT_ID']}"],
        )

    def test_a_confidential_or_pkce_less_keycloak_client_is_caught(self) -> None:
        self.assertEqual(
            planted("client", '"publicClient": true', '"publicClient": false'),
            [f"the Keycloak client lacks {CLIENT_ATTRIBUTES[0].pattern}"],
        )
        self.assertEqual(
            planted("client", '    "pkce.code.challenge.method": "S256",\n', ""),
            [f"the Keycloak client lacks {CLIENT_ATTRIBUTES[1].pattern}"],
        )


if __name__ == "__main__":
    unittest.main()
