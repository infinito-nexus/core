from __future__ import annotations

import posixpath
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

_TEMPLATE = "roles/svc-ai-litellm/templates/env.j2"
_REDIRECT = "AUTO_REDIRECT_UI_LOGIN_TO_SSO"
_OIDC = {
    "CLIENT": {
        "ID": "litellm",
        "SECRET": "fixture",
        "AUTHORIZE_URL": "https://auth.example/auth",
        "TOKEN_URL": "https://auth.example/token",
        "USER_INFO_URL": "https://auth.example/userinfo",
    },
    "ATTRIBUTES": {
        "USERNAME": "preferred_username",
        "EMAIL": "email",
        "NAME": "name",
        "GIVEN_NAME": "given_name",
        "FAMILY_NAME": "family_name",
    },
}


def _lookup(kind: str, *terms: str) -> object:
    """
    Args:
      kind: lookup plugin name the template calls.
      terms: positional terms of that lookup.

    Returns:
      a user record for "users", else a fixture string naming the call.
    """
    if kind == "users":
        return {"username": "administrator"}
    return "-".join((kind, *terms))


def _render(sso: bool) -> dict[str, str]:
    """
    Args:
      sso: value of LITELLM_UI_SSO.

    Returns:
      the rendered gateway dotenv as a key to value mapping.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["dirname"] = posixpath.dirname
    env.filters["dotenv_quote"] = str
    text = env.get_template(_TEMPLATE).render(
        application_id="svc-ai-litellm",
        lookup=_lookup,
        HOST_TIMEZONE="UTC",
        LITELLM_CONFIG_PATH_DOCKER="/app/config/config.yaml",
        LITELLM_MASTER_KEY="fixture",
        LITELLM_KEYED_PROVIDERS=[],
        LITELLM_PROVIDER_KEYS={},
        LITELLM_UI_SSO=sso,
        LITELLM_UI_ORIGIN="https://llm.example",
        LITELLM_UI_ADMIN="administrator",
        OIDC=_OIDC,
    )
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


class TestEnvSsoRedirect(unittest.TestCase):
    def test_sso_login_sends_the_ui_login_straight_to_keycloak(self) -> None:
        self.assertEqual(_render(True).get(_REDIRECT), "true")

    def test_without_sso_the_ui_keeps_its_own_password_form(self) -> None:
        self.assertNotIn(_REDIRECT, _render(False))


if __name__ == "__main__":
    unittest.main()
