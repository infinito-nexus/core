from __future__ import annotations

import json
import re
import unittest

from jinja2 import ChainableUndefined, Environment, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT
from .test_backchannel_clients import render_fragment

ROLE = PROJECT_ROOT / "roles/web-app-zammad"
FRAGMENT = ROLE / "templates/keycloak/clients.json.j2"
AUTO_WIZARD = ROLE / "templates/auto_wizard.json.j2"
SETTINGS = ROLE / "files/ruby/apply/oidc_settings.rb"
TASKS = ROLE / "tasks/01_manager_ops/oidc.yml"
OIDC_TASK = "📌 apply OIDC settings in Zammad (post-bootstrap; idempotent)"
CREDENTIALS = "auth_openid_connect_credentials"
SHARED_SECRET = "shared-oidc-client-secret"
SECRET_READS = re.compile(r"OIDC_CLIENT_SECRET|OIDC\.CLIENT\.SECRET")
RUBY_CREDENTIALS = re.compile(
    rf'Setting\.set\("{CREDENTIALS}",\s*\{{(?P<body>.*?)\}}\)', re.DOTALL
)
RUBY_PAIR = re.compile(r'"(?P<key>\w+)"\s*=>\s*(?P<value>[^,\n]+)')
REASON = (
    "Zammad 7.1.2 builds the token request from client_options holding only the "
    "identifier and the redirect URI (lib/omni_auth/strategies/oidc_database.rb "
    "self.setup), so rack-oauth2 sends HTTP Basic with an empty secret and Keycloak "
    "answers a confidential client with invalid_client_credentials; upstream fix "
    "2bafc586e2 (#6501) keeps the strategy a public client with client_auth_method none"
)


def zammad_client_findings(client: dict) -> list[str]:
    """What keeps the Zammad client from the public PKCE client Zammad can sign in to.

    Args:
        client: the Zammad client's representation.
    """
    findings = []
    if client["publicClient"] is not True:
        findings.append("publicClient is not true")
    if "secret" in client:
        findings.append("the client carries a secret Zammad never sends")
    if client["standardFlowEnabled"] is not True:
        findings.append("the standard flow is off")
    if client["attributes"].get("pkce.code.challenge.method") != "S256":
        findings.append("PKCE S256 is not enforced")
    return findings


def credential_findings(credentials: dict) -> list[str]:
    """What keeps Zammad's OIDC credential setting off the public PKCE client.

    Args:
        credentials: the ``auth_openid_connect_credentials`` value, keys as Zammad
            stores them, values as written.
    """
    findings = []
    if "secret" in credentials:
        findings.append("the setting stores a secret the strategy ignores")
    if credentials.get("pkce") not in (True, "true"):
        findings.append("PKCE is off")
    return findings


def wizard_credentials() -> dict:
    """
    Returns:
        The OIDC credential setting the auto wizard seeds, rendered with SSO on.
    """
    env = Environment(undefined=ChainableUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    rendered = env.from_string(read_text(str(AUTO_WIZARD))).render(
        ZAMMAD_OIDC_ENABLED=True,
        ZAMMAD_LOGIN_SSO=True,
        ZAMMAD_OIDC_CLIENT_ID="zammad-web",
        OIDC={
            "BUTTON_TEXT": "SSO",
            "CLIENT": {"ISSUER_URL": "https://kc.example.com/realms/r"},
        },
    )
    settings = json.loads(rendered)["Settings"]
    return next(s["value"] for s in settings if s["name"] == CREDENTIALS)


def ruby_credentials(source: str) -> dict:
    """The keys of the credential hash ``oidc_settings.rb`` writes, with raw values.

    Args:
        source: the Ruby script.
    """
    body = RUBY_CREDENTIALS.search(source)["body"]
    return {m["key"]: m["value"].strip() for m in RUBY_PAIR.finditer(body)}


def oidc_task() -> dict:
    return next(
        task
        for task in load_yaml_str(read_text(str(TASKS)))
        if task["name"] == OIDC_TASK
    )


class TestZammadClient(unittest.TestCase):
    def setUp(self) -> None:
        (self.client,) = render_fragment(FRAGMENT)

    def test_the_zammad_client_is_a_public_pkce_client(self) -> None:
        self.assertEqual(zammad_client_findings(self.client), [], REASON)

    def test_a_confidential_zammad_client_fails_the_check(self) -> None:
        client = {
            **self.client,
            "publicClient": False,
            "secret": SHARED_SECRET,
            "attributes": {
                key: value
                for key, value in self.client["attributes"].items()
                if key != "pkce.code.challenge.method"
            },
        }
        self.assertEqual(
            zammad_client_findings(client),
            [
                "publicClient is not true",
                "the client carries a secret Zammad never sends",
                "PKCE S256 is not enforced",
            ],
        )


class TestZammadCredentialSetting(unittest.TestCase):
    def test_the_auto_wizard_seeds_pkce_without_a_secret(self) -> None:
        self.assertEqual(credential_findings(wizard_credentials()), [], REASON)

    def test_the_oidc_settings_write_pkce_without_a_secret(self) -> None:
        self.assertEqual(
            credential_findings(ruby_credentials(read_text(str(SETTINGS)))),
            [],
            REASON,
        )

    def test_the_settings_task_hands_zammad_no_client_secret(self) -> None:
        shell = oidc_task()["ansible.builtin.shell"]
        self.assertEqual(SECRET_READS.findall(shell["cmd"] + shell["stdin"]), [])

    def test_a_secret_or_a_missing_pkce_fails_the_check(self) -> None:
        source = (
            f'Setting.set("{CREDENTIALS}", {{\n'
            '  "identifier" => ENV.fetch("OIDC_CLIENT_ID"),\n'
            '  "secret"     => ENV.fetch("OIDC_CLIENT_SECRET"),\n'
            "})"
        )
        self.assertEqual(
            credential_findings(ruby_credentials(source)),
            ["the setting stores a secret the strategy ignores", "PKCE is off"],
        )
        self.assertEqual(
            credential_findings({"secret": SHARED_SECRET, "pkce": False}),
            ["the setting stores a secret the strategy ignores", "PKCE is off"],
        )


if __name__ == "__main__":
    unittest.main()
