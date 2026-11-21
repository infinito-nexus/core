from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

OIDC_TASKS = PROJECT_ROOT / "roles/web-app-openbao/tasks/utils/oidc.yml"
REALM = PROJECT_ROOT / "roles/web-app-keycloak/templates/import/realm.json.j2"
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def seconds(duration: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", duration)
    if match is None:
        raise AssertionError(f"unparsable OpenBao duration {duration!r}")
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


def oidc_role_token_parameters() -> dict[str, str]:
    scripts = [
        str(task.get("ansible.builtin.shell", ""))
        for task in load_yaml_any(str(OIDC_TASKS))
        if "auth/oidc/role/" in str(task.get("ansible.builtin.shell", ""))
    ]
    if len(scripts) != 1:
        raise AssertionError(
            f"expected one task writing the OIDC role, found {len(scripts)}"
        )
    return dict(re.findall(r"\b(token_(?:max_)?ttl)=(\S+)", scripts[0]))


def realm_seconds(setting: str) -> int:
    match = re.search(rf'"{setting}": (\d+),', read_text(str(REALM)))
    if match is None:
        raise AssertionError(f"{setting} is missing from {REALM}")
    return int(match.group(1))


class TestOidcTokenTtl(unittest.TestCase):
    def test_an_idle_ui_token_expires_with_the_idle_sso_session(self):
        parameters = oidc_role_token_parameters()
        self.assertIn("token_ttl", parameters)
        self.assertEqual(
            seconds(parameters["token_ttl"]), realm_seconds("ssoSessionIdleTimeout")
        )

    def test_no_ui_token_outlives_the_longest_sso_session(self):
        parameters = oidc_role_token_parameters()
        self.assertIn("token_max_ttl", parameters)
        self.assertEqual(
            seconds(parameters["token_max_ttl"]), realm_seconds("ssoSessionMaxLifespan")
        )
