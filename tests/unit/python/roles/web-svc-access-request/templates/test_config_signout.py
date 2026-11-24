from __future__ import annotations

import json
import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATE = "roles/web-svc-access-request/templates/config.json.j2"
SIGNOUT_URL = (
    "/oauth2/sign_out?rd=https%3A//auth.example.org/realms/realm"
    "/protocol/openid-connect/logout"
)
SERVICE_TEXTS = {
    "en": {"signin_action": "Sign in", "dir": "ltr"},
    "de": {"signin_action": "Anmelden", "dir": "ltr"},
    "fr": {"signin_action": "Se connecter", "dir": "ltr"},
}
LOGOUT_TEXTS = {
    "en": {"choice_device": "Log out on this device", "dir": "ltr"},
    "de": {"choice_device": "Auf diesem Geraet abmelden", "dir": "ltr"},
    "ar": {"choice_device": "ar:choice_device", "dir": "rtl"},
}


def render_config() -> dict:
    """
    Returns:
        The JSON object the template renders.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        trim_blocks=True,
        autoescape=select_autoescape(),
    )
    env.filters.update(CoreFilters().filters())
    rendered = env.get_template(TEMPLATE).render(
        ACCESS_REQUEST_URL="https://access.example.org",
        ACCESS_REQUEST_SIGNOUT_URL=SIGNOUT_URL,
        ACCESS_REQUEST_FOUR_EYES=False,
        ACCESS_REQUEST_PLATFORM_GROUP="/roles/web-svc-access-request/administrator",
        ACCESS_REQUEST_APPROVER_EMAILS=["admin@example.org"],
        ACCESS_REQUEST_CA_FILE="",
        ACCESS_REQUEST_CATALOGUE={},
        ACCESS_REQUEST_I18N=SERVICE_TEXTS,
        ACCESS_REQUEST_LOGOUT_I18N=LOGOUT_TEXTS,
        ACCESS_REQUEST_RBAC_I18N={"en": {}},
        OIDC={"URL": "https://auth.example.org", "CLIENT": {"REALM": "realm"}},
        ACCESS_REQUEST_EMAIL={
            "host": "mail.example.org",
            "port": 465,
            "tls": True,
            "start_tls": False,
            "auth": True,
            "username": "access-request",
            "from": "access-request@example.org",
        },
        ACCESS_REQUEST_ZAMMAD_URL="",
        ACCESS_REQUEST_ZAMMAD_GROUP="Users",
    )
    return json.loads(rendered)


class TestConfigSignout(unittest.TestCase):
    def test_the_service_gets_the_gate_sign_out_url(self) -> None:
        self.assertEqual(SIGNOUT_URL, render_config()["signout_url"])

    def test_each_service_language_labels_the_sign_out_with_the_logout_text(
        self,
    ) -> None:
        i18n = render_config()["i18n"]

        self.assertEqual("Log out on this device", i18n["en"]["signout_action"])
        self.assertEqual("Auf diesem Geraet abmelden", i18n["de"]["signout_action"])
        self.assertEqual("Anmelden", i18n["de"]["signin_action"])

    def test_the_logout_text_adds_no_language_the_service_lacks(self) -> None:
        i18n = render_config()["i18n"]

        self.assertEqual({"en", "de", "fr"}, set(i18n))
        self.assertNotIn(
            "signout_action",
            i18n["fr"],
            "a language without a logout translation falls back to the English "
            "label per key, so it must not carry a label of its own",
        )


if __name__ == "__main__":
    unittest.main()
