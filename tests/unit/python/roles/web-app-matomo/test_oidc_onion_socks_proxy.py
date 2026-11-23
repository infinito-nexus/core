from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.lookup.tor_socks_proxy import resolve_proxy_url
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.reachability import network_of
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

APP = "web-app-matomo"
ROLE = PROJECT_ROOT / "roles" / APP
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
NETWORKS_VARS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"))
)
LOOPBACK_HOSTS = [
    NETWORKS_VARS["NETWORK_LOOPBACK_IPV4"],
    NETWORKS_VARS["NETWORK_LOOPBACK_IPV6"],
    NETWORKS_VARS["NETWORK_LOOPBACK_NAME"],
]
PROXY = resolve_proxy_url(
    {"svc-net-tor": {"services": {"tor": {"ports": {"local": {"socks": 9050}}}}}}
)
ONION_ISSUER = "http://auth." + "a" * 56 + ".onion/realms/infinito.nexus"
CLEARNET_ISSUER = "https://auth.infinito.example/realms/infinito.nexus"
PROXY_KEYS = ("http_proxy", "https_proxy", "no_proxy")
DATABASE = {
    "host": "mariadb",
    "port": 3306,
    "username": "matomo",
    "password": "x",
    "name": "matomo",
}


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        keep_trailing_newline=True,
    )
    env.filters["bool"] = lambda value: boolean(value, strict=False)
    env.filters["urlsplit"] = lambda url, part: getattr(urlsplit(url), part)
    env.filters["network_of"] = network_of
    env.filters["dotenv_quote"] = lambda value: value
    return env


def _socks_proxy(*, issuer: str, oidc_state: str) -> str:
    """
    Args:
        issuer: the OIDC issuer URL of the deployment.
        oidc_state: ``present`` while the RebelOIDC sign-in is on, else ``absent``.

    Returns:
        What ``MATOMO_OIDC_SOCKS_PROXY`` of vars/main.yml renders to.
    """
    env = _environment()

    def lookup(name: str, *terms: str) -> str:
        if name == "tor_socks_proxy" and not terms:
            return PROXY
        raise AssertionError(
            f"the proxy var renders an unexpected lookup {name}{terms}"
        )

    env.globals["lookup"] = lookup
    onion = env.from_string(VARS["MATOMO_OIDC_ONION_ISSUER"]).render(
        OIDC={"CLIENT": {"ISSUER_URL": issuer}}
    )
    return env.from_string(VARS["MATOMO_OIDC_SOCKS_PROXY"]).render(
        MATOMO_OIDC_STATE=oidc_state, MATOMO_OIDC_ONION_ISSUER=onion
    )


def _render_env(socks_proxy: str) -> dict[str, str]:
    """
    Args:
        socks_proxy: the rendered ``MATOMO_OIDC_SOCKS_PROXY``.

    Returns:
        The KEY=VALUE pairs of the Matomo container's env file.
    """
    env = _environment()

    def lookup(name: str, *terms: str):
        if name == "database" and terms[0] == APP:
            return DATABASE[terms[1]]
        if name == "proxy_excluded_hosts" and terms == (APP,):
            return LOOPBACK_HOSTS
        raise AssertionError(f"env.j2 renders an unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    rendered = env.get_template(f"roles/{APP}/templates/env.j2").render(
        application_id=APP,
        HOST_TIMEZONE="UTC",
        MATOMO_OIDC_SOCKS_PROXY=socks_proxy,
    )
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


class TestMatomoReachesAnOnionIssuerThroughTor(unittest.TestCase):
    def test_an_onion_issuer_turns_the_tor_proxy_on(self):
        self.assertEqual(
            _socks_proxy(issuer=ONION_ISSUER, oidc_state="present"),
            PROXY,
            "RebelOIDC calls the token and userinfo endpoints with plain cURL, and "
            "libcurl refuses an .onion host under RFC 7686 before /etc/hosts or the "
            "extra_hosts pin is read, so the code exchange needs the Tor proxy",
        )

    def test_a_clearnet_issuer_gets_no_proxy(self):
        self.assertEqual(_socks_proxy(issuer=CLEARNET_ISSUER, oidc_state="present"), "")

    def test_no_proxy_while_the_sso_sign_in_is_off(self):
        self.assertEqual(_socks_proxy(issuer=ONION_ISSUER, oidc_state="absent"), "")

    def test_the_proxy_hands_the_name_to_tor_to_resolve(self):
        self.assertTrue(
            PROXY.startswith("socks5h://"),
            "socks5:// resolves the .onion name locally, which libcurl refuses",
        )

    def test_the_container_routes_curl_through_tor(self):
        values = _render_env(PROXY)
        self.assertEqual(values["http_proxy"], PROXY)
        self.assertEqual(values["https_proxy"], PROXY)

    def test_the_loopback_calls_stay_direct(self):
        excluded = _render_env(PROXY)["no_proxy"].split(",")
        for host in LOOPBACK_HOSTS:
            with self.subTest(host=host):
                self.assertIn(
                    host,
                    excluded,
                    "the healthcheck and tasks/07_config.yml curl Matomo on the loopback",
                )

    def test_a_clearnet_container_carries_no_proxy(self):
        values = _render_env("")
        for key in PROXY_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(key, values)
        self.assertEqual(values["MATOMO_DATABASE_HOST"], "mariadb:3306")

    def test_the_bootstrap_container_keeps_no_proxy(self):
        bootstrap = read_text(str(ROLE / "templates" / "bootstrap.env.j2"))
        for key in (*PROXY_KEYS, "MATOMO_OIDC_SOCKS_PROXY"):
            with self.subTest(key=key):
                self.assertNotIn(
                    key,
                    bootstrap,
                    "the bootstrap reaches Matomo by its service name, which Tor cannot resolve",
                )


class TestMatomoMakesNoUpdateCallThroughTor(unittest.TestCase):
    def test_the_release_disables_the_update_check(self):
        dockerfile = read_text(str(ROLE / "files" / "Dockerfile"))
        self.assertIn(
            "printf '[General]\\nenable_auto_update = 0\\n' > "
            '"${MATOMO_RELEASE_DIR}/config/common.config.ini.php"',
            dockerfile,
            "UpdateCheck calls api.matomo.org through the env proxy with a 5 s "
            "timeout and retries on every request after a failure, which stalls "
            "each installer page behind a Tor without exits",
        )
        self.assertIn("ARG MATOMO_RELEASE_DIR", dockerfile)

    def test_the_build_passes_the_release_dir(self):
        compose = read_text(str(ROLE / "templates" / "compose.yml.j2"))
        self.assertIn('MATOMO_RELEASE_DIR: "{{ MATOMO_RELEASE_DIR }}"', compose)


if __name__ == "__main__":
    unittest.main()
