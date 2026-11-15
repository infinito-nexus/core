from __future__ import annotations

import hashlib
import json
import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from plugins.filter.backchannel_gate import logout_gate_apps
from plugins.filter.dotenv import dotenv_quote, dotenv_unquote
from utils.cache.files import read_text
from utils.networks.instances import labelled
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

APP = "web-svc-logout"
ROLE = PROJECT_ROOT / "roles" / APP
GATED = "web-app-xwiki"
OPEN = "web-app-wordpress"
CLIENT_ID = "xwiki"
RECEIVER_PATH = "/oidc/authenticator/backchannel_logout"
GATE_KEY = "k" * 48
LOGOUT_ORIGIN = "https://logout.example.test"
CERTS = "https://auth.example.test/realms/main/protocol/openid-connect/certs"
OIDC = {
    "CLIENT": {
        "ISSUER_URL": "https://auth.example.test/realms/main",
        "CERTS": CERTS,
    }
}
SEAL = "roles/web-svc-logout/templates/backchannel-seal.conf.j2"
SERVER_HOOK = "roles/sys-front-inj-all/templates/server.conf.j2"
HTML_LOCATION = "roles/sys-svc-proxy/templates/location/html.conf.j2"
HTML_LOCATION_STUB = (
    "location {{ location }} {\n"
    "sso={{ sso_proxy_enabled }}\n"
    "{{ webserver_location_extra_configuration }}\n"
    "}\n"
)

APPLICATIONS = {
    GATED: {"services": {"sso": {"oidc": {"backchannel_logout_gate": True}}}},
    OPEN: {"services": {"sso": {"oidc": {}}}},
}
CONFIG = {
    (GATED, "services.sso.oidc.backchannel_logout_gate"): True,
    (GATED, "services.sso.oidc.clients.web"): CLIENT_ID,
    (GATED, "services.sso.oidc.backchannel_logout_path"): RECEIVER_PATH,
    (GATED, "secrets.credentials.logout_gate_key"): GATE_KEY,
}


def lookup(name, *terms, **kwargs):
    """Answer the lookups of the gate templates for one gated and one open app.

    Args:
        name: the lookup plugin.
        terms: its positional terms; the third term of a config lookup is its default.
        kwargs: its keyword arguments.
    """
    if name == "applications":
        return APPLICATIONS
    if name == "tls":
        return LOGOUT_ORIGIN if terms[0] == APP else f"https://{terms[0]}.example.test"
    if name == "network_urls":
        return [terms[0], terms[0].replace(".example.test", ".example.onion")]
    if name == "config":
        if (terms[0], terms[1]) in CONFIG:
            return CONFIG[(terms[0], terms[1])]
        if len(terms) > 2:
            return terms[2]
        raise AssertionError(f"unexpected strict config lookup: {terms}")
    raise AssertionError(f"unexpected lookup: {name} {terms} {kwargs}")


def environment(overrides: dict[str, str]) -> Environment:
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        loader=ChoiceLoader(
            [DictLoader(overrides), FileSystemLoader(str(PROJECT_ROOT))]
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
    )
    env.filters.update(
        bool=bool,
        dotenv_quote=dotenv_quote,
        hash=lambda value, algorithm: hashlib.new(
            algorithm, value.encode()
        ).hexdigest(),
        labelled=labelled,
        logout_domains=lambda *_args: [],
        logout_gate_apps=logout_gate_apps,
        to_json=json.dumps,
    )
    env.globals["lookup"] = lookup
    return env


def env_values(rendered: str) -> dict[str, str]:
    return dict(
        row.split("=", 1) for row in rendered.splitlines() if re.match(r"[A-Z_]+=", row)
    )


def render_env(gate_apps: list[str]) -> dict[str, str]:
    return env_values(
        environment({})
        .get_template("roles/web-svc-logout/templates/env.j2")
        .render(
            container_port=8080,
            HOST_TIMEZONE="UTC",
            OIDC=OIDC,
            LOGOUT_GATE_APPS=gate_apps,
        )
    )


def render_seal(application_id: str) -> str:
    return (
        environment({HTML_LOCATION: HTML_LOCATION_STUB})
        .get_template(SEAL)
        .render(logout_consumer_id=application_id)
    )


def compose_onion_peers(gate_apps: list[str]) -> list:
    """Return what the compose file hands ``container_extra_hosts`` as onion peers.

    Args:
        gate_apps: the value of ``LOGOUT_GATE_APPS``.
    """
    seen = []

    def recording(name, *terms, **kwargs):
        if name == "container_extra_hosts":
            seen.append(kwargs["onion_peers"])
            return ""
        if name in ("applications", "domains"):
            return {}
        if name == "tls":
            return lookup(name, *terms)
        return ""

    env = environment(
        {
            "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
            "roles/sys-svc-container/templates/base.yml.j2": "",
        }
    )
    env.globals["lookup"] = recording
    env.from_string(read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))).render(
        application_id=APP,
        group_names=[APP, *gate_apps],
        LOGOUT_INSTANCES=[{"label": "", "network": "clearnet"}],
        LOGOUT_GATE_APPS=gate_apps,
        LOGOUT_CONTAINER="logout",
        DOCKER_BIND_HOST="127.0.0.1",
        OIDC=OIDC,
    )
    return seen


def playwright_targets(group_names: list[str]) -> list[dict]:
    lines = read_text(str(ROLE / "templates" / "playwright.env.j2")).splitlines()
    start = next(
        i
        for i, row in enumerate(lines)
        if row.startswith("{% set logout_matrix_deployed")
    )
    end = next(
        i for i, row in enumerate(lines) if row.startswith("BACKCHANNEL_TARGETS_JSON=")
    )
    source = "\n".join(lines[start : end + 1])
    rendered = environment({}).from_string(source).render(group_names=group_names)
    value = env_values(rendered)["BACKCHANNEL_TARGETS_JSON"]
    return json.loads(dotenv_unquote(value))


class TestGateClients(unittest.TestCase):
    def test_each_gated_app_hands_the_gate_its_audience_receiver_and_key(self) -> None:
        values = render_env([GATED])
        self.assertEqual(
            json.loads(dotenv_unquote(values["LOGOUT_GATE_CLIENTS"])),
            {
                GATED: {
                    "audience": CLIENT_ID,
                    "receiver": f"https://{GATED}.example.test{RECEIVER_PATH}",
                    "key": GATE_KEY,
                }
            },
        )

    def test_the_gate_trusts_the_realm_issuer_and_its_public_keys(self) -> None:
        values = render_env([GATED])
        self.assertEqual(
            dotenv_unquote(values["LOGOUT_GATE_ISSUER"]), OIDC["CLIENT"]["ISSUER_URL"]
        )
        self.assertEqual(dotenv_unquote(values["LOGOUT_GATE_JWKS_URL"]), CERTS)

    def test_a_host_without_a_gated_app_switches_the_gate_off(self) -> None:
        self.assertEqual(
            json.loads(dotenv_unquote(render_env([])["LOGOUT_GATE_CLIENTS"])), {}
        )


class TestGateReachesItsPeers(unittest.TestCase):
    def test_the_jwks_and_every_receiver_origin_are_onion_peers(self) -> None:
        self.assertEqual(
            compose_onion_peers([GATED]), [[CERTS, f"https://{GATED}.example.test"]]
        )

    def test_a_host_without_a_gated_app_pins_no_peer(self) -> None:
        self.assertEqual(compose_onion_peers([]), [[]])


class TestReceiverSeal(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = render_seal(GATED)

    def test_the_receiver_is_an_exact_location_off_the_sso_proxy(self) -> None:
        self.assertIn(f"location = {RECEIVER_PATH} {{", self.rendered)
        self.assertIn("sso=False", self.rendered)
        self.assertRegex(self.rendered, r"limit_except POST \{\s*deny all;\s*\}")

    def test_only_the_digest_of_the_gate_key_opens_the_receiver(self) -> None:
        digest = hashlib.sha256(GATE_KEY.encode()).hexdigest()
        self.assertIn(f'~= "{digest}" then', self.rendered)
        self.assertNotIn(GATE_KEY, self.rendered)
        self.assertEqual(self.rendered.count("return ngx.exit(ngx.HTTP_FORBIDDEN)"), 2)

    def test_the_gate_key_never_reaches_the_app(self) -> None:
        self.assertIn('proxy_set_header X-Logout-Gate-Key "";', self.rendered)

    def test_an_app_outside_the_gate_gets_no_seal(self) -> None:
        self.assertEqual(render_seal(OPEN).strip(), "")

    def test_every_vhost_hook_renders_the_seal_outside_any_branch(self) -> None:
        include = f"{{% include '{SEAL}' %}}"
        text = read_text(str(PROJECT_ROOT / SERVER_HOOK))
        self.assertIn(
            f"{{% with logout_consumer_id = application_id %}}\n{include}\n", text
        )
        before = text.split(include, 1)[0]
        self.assertEqual(
            len(re.findall(r"\{%-?\s*if\b", before)),
            len(re.findall(r"\{%-?\s*endif\b", before)),
        )


class TestPlaywrightGateTargets(unittest.TestCase):
    def test_a_gated_app_is_probed_at_the_gate_and_its_receiver(self) -> None:
        self.assertEqual(
            playwright_targets([APP, GATED, OPEN]),
            [
                {
                    "id": GATED,
                    "url": f"{LOGOUT_ORIGIN}/backchannel/{GATED}",
                    "client_id": CLIENT_ID,
                    "sealed_url": f"https://{GATED}.example.test{RECEIVER_PATH}",
                    "app_urls": [
                        f"https://{GATED}.example.test",
                        f"https://{GATED}.example.onion",
                    ],
                }
            ],
        )

    def test_an_undeployed_gated_app_is_not_probed(self) -> None:
        self.assertEqual(playwright_targets([APP, OPEN]), [])


if __name__ == "__main__":
    unittest.main()
