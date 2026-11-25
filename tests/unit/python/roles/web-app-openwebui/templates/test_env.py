from __future__ import annotations

import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-openwebui"
SOURCES = {
    "env": ROLE / "templates/env.j2",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "services": ROLE / ROLE_FILE_META_SERVICES,
    "client": ROLE / "templates/keycloak/clients.json.j2",
    "core": ROLE / "tasks/00_core.yml",
}
JWT_ENV = ("JWT_EXPIRES_IN", "{{ OPENWEBUI_JWT_EXPIRES_IN }}s")
LIFETIME_FINDING = (
    "JWT_EXPIRES_IN is not the realm's ssoSessionMaxLifespan in every variant"
)
STAMP_SECONDS = 30 * 86400
LIFETIME_PROBES = (
    (36000, True),
    (1, True),
    (STAMP_SECONDS, True),
    (0, False),
    (-1, False),
    (STAMP_SECONDS + 1, False),
    ("36000", False),
    ("ten hours", False),
    (True, False),
)
NO_GUARD_FINDING = "no assert guards JWT_EXPIRES_IN before the stack renders the env"
STAMP_FINDING = "OPENWEBUI_REVOCATION_STAMP_SECONDS is not the 30 days of oauth.py"
MAX_KEY = "services.keycloak.realm.sso_session_max_lifespan_seconds"
IDLE_KEY = "services.keycloak.realm.sso_session_idle_timeout_seconds"
RENDER_PROBES = (
    (36000, 36000),
    (STAMP_SECONDS, STAMP_SECONDS),
    (2 * STAMP_SECONDS, STAMP_SECONDS),
)
BARE_LIFETIME = f"\"{{{{ lookup('config', 'web-app-keycloak', '{MAX_KEY}') }}}}\""
CAPPED_LIFETIME = (
    f"\"{{{{ [lookup('config', 'web-app-keycloak', '{MAX_KEY}'), "
    'OPENWEBUI_REVOCATION_STAMP_SECONDS] | min }}"'
)
OIDC_BLOCK = "{% if OPENWEBUI_OIDC_ENABLED | bool %}"
OIDC_ENV = {
    "OAUTH_CLIENT_ID": "{{ OPENWEBUI_OIDC_CLIENT_ID }}",
    "OAUTH_CODE_CHALLENGE_METHOD": "S256",
    "OAUTH_TOKEN_ENDPOINT_AUTH_METHOD": "none",
    "ENABLE_OAUTH_BACKCHANNEL_LOGOUT": "true",
    "OPENID_END_SESSION_ENDPOINT": "{{ OPENWEBUI_OIDC_END_SESSION_URL }}",
    "BYPASS_ADMIN_ACCESS_CONTROL": "false",
}
MODEL_BYPASS_LINE = "BYPASS_MODEL_ACCESS_CONTROL=false"
MODEL_BYPASS_FINDING = "BYPASS_MODEL_ACCESS_CONTROL is not false in every variant"
ARENA_ENV = (
    "EVALUATION_ARENA_MODELS",
    "{{ OPENWEBUI_ARENA_MODELS | to_json(separators=(',', ':')) | dotenv_quote }}",
)
ARENA_ID = "arena-model"
PUBLIC_READ = {"principal_type": "user", "principal_id": "*", "permission": "read"}
ARENA_ENV_FINDING = "EVALUATION_ARENA_MODELS is not rendered in every variant"
ARENA_GRANT_FINDING = "the arena model is not readable by every user"
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


def accepts(checks: list, value: object) -> bool:
    try:
        return all(
            check(
                OPENWEBUI_JWT_EXPIRES_IN=value,
                OPENWEBUI_REVOCATION_STAMP_SECONDS=STAMP_SECONDS,
            )
            for check in checks
        )
    except TypeError:
        return False


def rendered_lifetime(variables: dict, lifespan: object) -> object:
    """
    Args:
        variables: the role's ``vars/main.yml``.
        lifespan: the ``sso_session_max_lifespan_seconds`` Keycloak holds.

    Returns:
        ``OPENWEBUI_JWT_EXPIRES_IN`` as Ansible renders it from that lifespan.
    """
    realm = {MAX_KEY: lifespan, IDLE_KEY: 1800}
    env = NativeEnvironment(undefined=StrictUndefined)
    env.globals["lookup"] = lambda _kind, application_id, key: {
        ("web-app-keycloak", name): value for name, value in realm.items()
    }[(application_id, key)]
    return env.from_string(variables["OPENWEBUI_JWT_EXPIRES_IN"]).render(
        OPENWEBUI_REVOCATION_STAMP_SECONDS=variables[
            "OPENWEBUI_REVOCATION_STAMP_SECONDS"
        ]
    )


def lifetime_render_findings(variables: dict, core: str) -> list[str]:
    """
    Args:
        variables: the role's ``vars/main.yml``.
        core: the role's ``tasks/00_core.yml``.

    Returns:
        Every Keycloak lifespan that does not render the shorter of itself and
        the revocation stamp, or renders a lifetime the guard refuses, so the
        Open WebUI deploy would fail on a valid Keycloak realm.
    """
    found = []
    if variables.get("OPENWEBUI_REVOCATION_STAMP_SECONDS") != STAMP_SECONDS:
        found.append(STAMP_FINDING)
    checks = guard_checks(core) or []
    for lifespan, expected in RENDER_PROBES:
        rendered = rendered_lifetime(variables, lifespan)
        if rendered != expected or not accepts(checks, rendered):
            found.append(
                f"a Keycloak lifespan of {lifespan} renders JWT_EXPIRES_IN {rendered!r}"
            )
    return found


def guard_checks(core: str) -> list | None:
    """
    Args:
        core: the role's ``tasks/00_core.yml``.

    Returns:
        The compiled ``that`` expressions of the assert on
        ``OPENWEBUI_JWT_EXPIRES_IN`` before the stack renders the env, or
        ``None`` without one.
    """
    tasks = load_yaml_str(core)
    stack = next(
        index
        for index, task in enumerate(tasks)
        if (
            task.get("include_role") or task.get("ansible.builtin.include_role") or {}
        ).get("name")
        == "svc-stack"
    )
    guard = next(
        (
            task
            for task in tasks[:stack]
            if "OPENWEBUI_JWT_EXPIRES_IN" in str(task.get("ansible.builtin.assert"))
        ),
        None,
    )
    if guard is None:
        return None
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return [
        env.compile_expression(that) for that in guard["ansible.builtin.assert"]["that"]
    ]


def lifetime_guard_findings(core: str) -> list[str]:
    """
    Args:
        core: the role's ``tasks/00_core.yml``.

    Returns:
        Every lifetime the guard lets through to the env although Open WebUI
        would issue never-expiring tokens or tokens that outlive the
        revocation stamp, and every lifetime it refuses although it is valid.
    """
    checks = guard_checks(core)
    if checks is None:
        return [NO_GUARD_FINDING]
    return [
        f"JWT_EXPIRES_IN {value!r} is {'refused' if valid else 'accepted'}"
        for value, valid in LIFETIME_PROBES
        if accepts(checks, value) != valid
    ]


def findings(sources: dict[str, str]) -> list[str]:
    """What keeps Open WebUI from its own public client, its sign-out and its revocation store.

    Args:
        sources: the env template, vars, services, Keycloak client fragment
            and core tasks of the role, keyed as in ``SOURCES``.
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
    if entries.get(JWT_ENV[0]) != (JWT_ENV[1], ""):
        found.append(LIFETIME_FINDING)
    found.extend(lifetime_guard_findings(sources["core"]))
    found.extend(lifetime_render_findings(variables, sources["core"]))
    if entries.get("ENABLE_PERSISTENT_CONFIG") != ("false", ""):
        found.append("ENABLE_PERSISTENT_CONFIG is not false in every variant")
    if entries.get("BYPASS_MODEL_ACCESS_CONTROL") != ("false", ""):
        found.append(MODEL_BYPASS_FINDING)
    if entries.get(ARENA_ENV[0]) != (ARENA_ENV[1], ""):
        found.append(ARENA_ENV_FINDING)
    arena = [
        model
        for model in variables.get("OPENWEBUI_ARENA_MODELS") or []
        if model.get("id") == ARENA_ID
    ]
    if not arena or PUBLIC_READ not in (arena[0]["meta"].get("access_grants") or []):
        found.append(ARENA_GRANT_FINDING)
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

    def test_a_missing_or_network_gated_end_session_endpoint_is_caught(self) -> None:
        key = "OPENID_END_SESSION_ENDPOINT"
        line = f"{key}={OIDC_ENV[key]}\n"
        finding = [f"{key} is not {OIDC_ENV[key]} in the SSO block"]
        self.assertEqual(planted("env", line, ""), finding)
        self.assertEqual(
            planted(
                "env",
                line,
                "{% if (OIDC.CLIENT.ISSUER_URL | urlsplit('hostname') | network_of) == 'tor' %}\n"
                f"{line}{{% endif %}}\n",
            ),
            finding,
            "with the discovery fallback on clearnet the sign-out still fetches it from the "
            "container, and one Keycloak outage there leaves the SSO session open again",
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
        line = f"{JWT_ENV[0]}={JWT_ENV[1]}\n"
        self.assertEqual(
            planted("env", line, "JWT_EXPIRES_IN=4w\n"), [LIFETIME_FINDING]
        )
        self.assertEqual(planted("env", line, ""), [LIFETIME_FINDING])
        self.assertEqual(
            planted(
                "vars",
                "realm.sso_session_max_lifespan_seconds",
                "realm.sso_session_idle_timeout_seconds",
            ),
            [
                f"a Keycloak lifespan of {lifespan} renders JWT_EXPIRES_IN 1800"
                for lifespan, _ in RENDER_PROBES
            ],
        )
        self.assertEqual(
            planted(
                "env", line, "JWT_EXPIRES_IN={{ OPENWEBUI_JWT_EXPIRES_IN | int }}s\n"
            ),
            [LIFETIME_FINDING],
        )

    def test_a_keycloak_lifespan_above_the_stamp_renders_the_stamp(self) -> None:
        variables = load_yaml_str(role_sources()["vars"])
        self.assertEqual(rendered_lifetime(variables, 2 * STAMP_SECONDS), STAMP_SECONDS)
        self.assertEqual(
            lifetime_render_findings(variables, role_sources()["core"]), []
        )

    def test_control_a_lifetime_without_the_cap_fails_a_valid_keycloak_realm(
        self,
    ) -> None:
        self.assertEqual(
            planted("vars", CAPPED_LIFETIME, BARE_LIFETIME),
            [
                f"a Keycloak lifespan of {2 * STAMP_SECONDS} renders JWT_EXPIRES_IN {2 * STAMP_SECONDS}"
            ],
        )

    def test_control_a_stamp_other_than_open_webuis_is_caught(self) -> None:
        self.assertIn(
            STAMP_FINDING,
            planted(
                "vars",
                "OPENWEBUI_REVOCATION_STAMP_SECONDS: 2592000",
                "OPENWEBUI_REVOCATION_STAMP_SECONDS: 5184000",
            ),
        )

    def test_a_lifetime_of_zero_or_no_whole_number_fails_the_deploy(self) -> None:
        self.assertEqual(lifetime_guard_findings(role_sources()["core"]), [])

    def test_control_a_guard_without_the_lower_bound_lets_zero_through(self) -> None:
        self.assertEqual(
            planted("core", "      - OPENWEBUI_JWT_EXPIRES_IN >= 1\n", ""),
            ["JWT_EXPIRES_IN 0 is accepted", "JWT_EXPIRES_IN -1 is accepted"],
        )

    def test_control_a_guard_without_the_integer_check_lets_a_bool_through(
        self,
    ) -> None:
        self.assertEqual(
            planted("core", "      - OPENWEBUI_JWT_EXPIRES_IN is integer\n", ""),
            ["JWT_EXPIRES_IN True is accepted"],
        )

    def test_control_a_missing_guard_is_caught(self) -> None:
        core = role_sources()["core"]
        self.assertEqual(
            lifetime_guard_findings(
                core.replace("OPENWEBUI_JWT_EXPIRES_IN", "OPENWEBUI_OTHER")
            ),
            [NO_GUARD_FINDING],
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

    def test_a_model_bypass_without_the_broker_is_caught(self) -> None:
        self.assertEqual(
            planted(
                "env",
                MODEL_BYPASS_LINE,
                "BYPASS_MODEL_ACCESS_CONTROL="
                "{{ (not (OPENWEBUI_AGENT_BROKER_ENABLED | bool)) | string | lower }}",
            ),
            [MODEL_BYPASS_FINDING],
        )
        self.assertEqual(
            planted(
                "env",
                MODEL_BYPASS_LINE,
                "{% if OPENWEBUI_AGENT_BROKER_ENABLED | bool %}\n"
                f"{MODEL_BYPASS_LINE}\n{{% endif %}}",
            ),
            [MODEL_BYPASS_FINDING],
        )

    def test_an_arena_without_a_public_grant_is_caught(self) -> None:
        self.assertEqual(
            planted(
                "vars",
                "        - principal_type: user\n"
                '          principal_id: "*"\n'
                "          permission: read\n",
                "",
            ),
            [ARENA_GRANT_FINDING],
        )
        self.assertEqual(
            planted("env", f"{ARENA_ENV[0]}={ARENA_ENV[1]}\n", ""),
            [ARENA_ENV_FINDING],
        )

    def test_an_administrator_bypass_is_caught(self) -> None:
        self.assertEqual(
            planted(
                "env",
                "BYPASS_ADMIN_ACCESS_CONTROL=false",
                "BYPASS_ADMIN_ACCESS_CONTROL=true",
            ),
            ["BYPASS_ADMIN_ACCESS_CONTROL is not false in the SSO block"],
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
