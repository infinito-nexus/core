from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

APP = "web-app-weblate"
CLEARNET = "web.translate.example.com"
ONION = "web.translate." + "a" * 56 + ".onion"
SERVICE_NAME = "weblate"
PLACEHOLDER = "x"
NETWORKS_VARS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "group_vars/all/08_networks.yml"))
)
LOOPBACK_HOSTS = [
    NETWORKS_VARS["NETWORK_LOOPBACK_IPV4"],
    NETWORKS_VARS["NETWORK_LOOPBACK_IPV6"],
    NETWORKS_VARS["NETWORK_LOOPBACK_NAME"],
]


def render_env(siblings: list[str]) -> dict[str, str]:
    """Render the role's env.j2 for a node serving Weblate under ``siblings``.

    Args:
        siblings: what ``lookup('network_siblings', <clearnet domain>)`` returns.

    Returns:
        The rendered KEY=VALUE pairs.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        keep_trailing_newline=True,
    )
    user = {"username": "administrator", "email": "administrator@example.com"}

    def lookup(name: str, *terms: str):
        answers = {
            "domain": CLEARNET,
            "tls": True,
            "users": user,
            "engine": "",
        }
        if name == "network_siblings":
            if terms != (CLEARNET,):
                raise AssertionError(f"network_siblings asked for {terms}")
            return siblings
        if name in answers:
            return answers[name]
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = lambda value: value
    env.filters["ternary"] = lambda value, yes, no: yes if value else no
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        WEBLATE_SITE_TITLE="Translations",
        WEBLATE_REGISTRATION_OPEN=False,
        WEBLATE_ADMIN_PASSWORD=PLACEHOLDER,
        WEBLATE_DATABASE_HOST="db",
        WEBLATE_DATABASE_PORT=5432,
        WEBLATE_DATABASE_USER="weblate",
        WEBLATE_DATABASE_PASSWORD=PLACEHOLDER,
        WEBLATE_DATABASE_NAME="weblate",
        WEBLATE_OIDC_ENABLED=False,
        WEBLATE_EMAIL_ENABLED=False,
        WEBLATE_CONTAINER=SERVICE_NAME,
        NETWORK_LOOPBACK_HOSTS=LOOPBACK_HOSTS,
    )
    return dict(
        line.split("=", 1)
        for line in rendered.splitlines()
        if "=" in line and not line.startswith("#")
    )


class TestWeblateAllowedHosts(unittest.TestCase):
    def test_every_network_sibling_is_admitted(self) -> None:
        hosts = render_env([CLEARNET, ONION])["WEBLATE_ALLOWED_HOSTS"].split(",")
        self.assertIn(CLEARNET, hosts)
        self.assertIn(
            ONION,
            hosts,
            "the onion vhost forwards its own Host header, and the origin "
            "middleware validates it against ALLOWED_HOSTS on every request",
        )

    def test_the_gateway_and_the_healthcheck_are_admitted(self) -> None:
        hosts = render_env([CLEARNET])["WEBLATE_ALLOWED_HOSTS"].split(",")
        self.assertIn(
            SERVICE_NAME,
            hosts,
            "web-svc-translate reads the memory at http://weblate:8080",
        )
        for loopback in LOOPBACK_HOSTS:
            self.assertIn(
                loopback, hosts, "the container healthcheck GETs the loopback"
            )

    def test_the_site_domain_stays_the_clearnet_domain(self) -> None:
        values = render_env([CLEARNET, ONION])
        self.assertEqual(values["WEBLATE_SITE_DOMAIN"], CLEARNET)
        self.assertEqual(values["WEBLATE_ENABLE_HTTPS"], "1")


if __name__ == "__main__":
    unittest.main()
