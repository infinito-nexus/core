from __future__ import annotations

import copy
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

OPENBAO_DIR = PROJECT_ROOT / "roles/web-app-openbao"
KEYCLOAK_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
OIDC_TASKS = OPENBAO_DIR / "tasks/utils/oidc.yml"
REALM = KEYCLOAK_DIR / "templates/import/realm.json.j2"
OPENBAO_VARS = load_yaml_any(str(OPENBAO_DIR / ROLE_FILE_VARS_MAIN))
KEYCLOAK_VARS = load_yaml_any(str(KEYCLOAK_DIR / ROLE_FILE_VARS_MAIN))
KEYCLOAK_SERVICES = load_yaml_any(str(KEYCLOAK_DIR / ROLE_FILE_META_SERVICES))
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}
PAIRS = {
    "token_ttl": ("ssoSessionIdleTimeout", "sso_session_idle_timeout_seconds"),
    "token_max_ttl": ("ssoSessionMaxLifespan", "sso_session_max_lifespan_seconds"),
}
LIFETIMES = ("OPENBAO_OIDC_TOKEN_TTL", "OPENBAO_OIDC_TOKEN_MAX_TTL")
VALID = {"OPENBAO_OIDC_TOKEN_TTL": 1800, "OPENBAO_OIDC_TOKEN_MAX_TTL": 36000}
PROBES = (
    (1800, True),
    (36000, True),
    (0, False),
    (-1, False),
    ("thirty minutes", False),
    (True, False),
)
NO_GUARD = "no assert guards the OIDC token lifetimes before the role write"
COERCED = "the OIDC role write coerces a lifetime with | int"


def environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )


def seconds(duration: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", duration)
    if match is None:
        raise AssertionError(f"unparsable OpenBao duration {duration!r}")
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


def resolver(realm: dict):
    """Args:
        realm: the ``services.keycloak.realm`` mapping of web-app-keycloak.

    Returns:
        A ``lookup`` that answers config paths of web-app-keycloak only.
    """
    services = copy.deepcopy(KEYCLOAK_SERVICES)
    services["keycloak"]["realm"] = realm

    def lookup(name, application_id, path):
        assert (name, application_id) == ("config", "web-app-keycloak"), (
            name,
            application_id,
        )
        value = {"services": services}
        for part in path.split("."):
            value = value[part]
        return value

    return lookup


def resolved(declared: dict, realm: dict) -> dict:
    env = environment()
    lookup = resolver(realm)
    return {
        name: env.compile_expression(
            str(expression).strip().removeprefix("{{").removesuffix("}}")
        )(lookup=lookup, application_id="web-app-keycloak")
        for name, expression in declared.items()
        if isinstance(expression, str)
        and "services.keycloak.realm.sso_session" in expression
    }


def oidc_role_lines() -> list[str]:
    scripts = [
        str(task.get("ansible.builtin.shell", ""))
        for task in load_yaml_any(str(OIDC_TASKS))
        if "auth/oidc/role/" in str(task.get("ansible.builtin.shell", ""))
    ]
    if len(scripts) != 1:
        raise AssertionError(
            f"expected one task writing the OIDC role, found {len(scripts)}"
        )
    return re.findall(r"\btoken_(?:max_)?ttl=(?:\{\{[^}]*\}\}|[^\s{])+", scripts[0])


def openbao_seconds(lines: list[str], realm: dict) -> dict[str, int]:
    """Args:
        lines: the ``token_*`` parameters of the OIDC role write.
        realm: the ``services.keycloak.realm`` mapping both roles read.

    Returns:
        Seconds per token parameter as OpenBao receives them.
    """
    env = environment()
    context = resolved(OPENBAO_VARS, realm)
    rendered = [env.from_string(line).render(context) for line in lines]
    return {
        name: seconds(value)
        for name, value in (line.split("=", 1) for line in rendered)
        if name in PAIRS
    }


def realm_seconds(realm: dict) -> dict[str, int]:
    env = environment()
    context = resolved(KEYCLOAK_VARS, realm)
    source = read_text(str(REALM))
    found = {}
    for field, _ in PAIRS.values():
        match = re.search(rf'"{field}": ([^,\n]+),', source)
        if match is None:
            raise AssertionError(f"{field} is missing from {REALM}")
        found[field] = int(env.from_string(match.group(1)).render(context))
    return found


def shipped_realm() -> dict:
    return copy.deepcopy(KEYCLOAK_SERVICES["keycloak"]["realm"])


def accepts(checks: list, values: dict) -> bool:
    try:
        return all(check(**values) for check in checks)
    except TypeError:
        return False


def guard_findings(source: str) -> list[str]:
    """
    Args:
        source: the text of ``tasks/utils/oidc.yml``.

    Returns:
        Every lifetime the guard before the OIDC role write lets through
        although OpenBao would fall back to its default for it, every valid one
        it refuses, and a role write that coerces a lifetime instead.
    """
    tasks = load_yaml_str(source)
    write = next(
        index
        for index, task in enumerate(tasks)
        if "auth/oidc/role/" in str(task.get("ansible.builtin.shell", ""))
    )
    found = [COERCED] if "| int" in str(tasks[write]["ansible.builtin.shell"]) else []
    guard = next(
        (
            task
            for task in tasks[:write]
            if LIFETIMES[0] in str(task.get("ansible.builtin.assert"))
        ),
        None,
    )
    if guard is None:
        return [*found, NO_GUARD]
    checks = [
        environment().compile_expression(that)
        for that in guard["ansible.builtin.assert"]["that"]
    ]
    found.extend(
        f"{name} {value!r} is {'refused' if valid else 'accepted'}"
        for name in LIFETIMES
        for value, valid in PROBES
        if accepts(checks, {**VALID, name: value}) != valid
    )
    return found


class TestOidcTokenTtl(unittest.TestCase):
    def assert_tokens_follow_the_sso_session(self, realm: dict) -> None:
        tokens = openbao_seconds(oidc_role_lines(), realm)
        sessions = realm_seconds(realm)
        self.assertEqual(sorted(tokens), sorted(PAIRS))
        for parameter, (field, key) in PAIRS.items():
            with self.subTest(parameter=parameter):
                self.assertEqual(tokens[parameter], realm[key])
                self.assertEqual(tokens[parameter], sessions[field])

    def test_ui_tokens_live_as_long_as_the_shipped_sso_session(self):
        self.assert_tokens_follow_the_sso_session(shipped_realm())

    def test_ui_tokens_follow_a_changed_sso_session(self):
        realm = shipped_realm()
        realm["sso_session_idle_timeout_seconds"] = 900
        realm["sso_session_max_lifespan_seconds"] = 7200
        self.assert_tokens_follow_the_sso_session(realm)

    def test_a_hard_coded_ttl_does_not_follow_a_changed_sso_session(self):
        realm = shipped_realm()
        realm["sso_session_idle_timeout_seconds"] = 900
        tokens = openbao_seconds(["token_ttl=30m", "token_max_ttl=10h"], realm)
        self.assertNotEqual(
            tokens["token_ttl"], realm_seconds(realm)["ssoSessionIdleTimeout"]
        )

    def test_a_lifetime_of_zero_or_no_whole_number_fails_the_deploy(self):
        self.assertEqual(guard_findings(read_text(str(OIDC_TASKS))), [])

    def test_control_a_guard_without_a_lower_bound_lets_zero_through(self):
        source = read_text(str(OIDC_TASKS)).replace(
            "      - OPENBAO_OIDC_TOKEN_TTL >= 1\n", ""
        )
        self.assertEqual(
            guard_findings(source),
            [
                "OPENBAO_OIDC_TOKEN_TTL 0 is accepted",
                "OPENBAO_OIDC_TOKEN_TTL -1 is accepted",
            ],
        )

    def test_control_a_missing_guard_or_a_coerced_lifetime_is_caught(self):
        source = read_text(str(OIDC_TASKS))
        self.assertEqual(
            guard_findings(source.replace(LIFETIMES[0], "OPENBAO_OTHER_TTL")),
            [NO_GUARD],
        )
        self.assertEqual(
            guard_findings(
                source.replace(
                    "token_ttl={{ OPENBAO_OIDC_TOKEN_TTL }}s",
                    "token_ttl={{ OPENBAO_OIDC_TOKEN_TTL | int }}s",
                )
            ),
            [COERCED],
        )
