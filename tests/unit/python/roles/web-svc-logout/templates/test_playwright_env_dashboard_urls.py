from __future__ import annotations

import json
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from plugins.filter.dotenv import dotenv_unquote
from utils.cache.files import read_text
from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

APP = "web-svc-logout"
SHOP_APP = "web-app-shop"
FORGE_APP = "web-app-forge"
CONSOLE_APP = "web-app-console"
TEMPLATE = PROJECT_ROOT / "roles" / APP / "templates" / "playwright.env.j2"
PRIMARY = default_domain_primary()
NODE = "a" * 56 + ".onion"
LOGOUT = [f"logout.{PRIMARY}", f"logout.{NODE}"]
DASHBOARD = [f"dashboard.{PRIMARY}", f"dashboard.{NODE}"]
SHOP = [f"shop.{PRIMARY}", f"shop.{NODE}"]
FORGE = [f"forge.{PRIMARY}", f"forge.{NODE}"]
CONSOLE = [f"console.{PRIMARY}", f"console.{NODE}"]
GATED_ROOT = {
    "is_proxy_gated": True,
    "oauth2_acl": {},
    "oauth2_allowed_groups": [],
}
GATED_LOGIN_ONLY = {
    "is_proxy_gated": True,
    "oauth2_acl": {"blacklist": ["/user/login"]},
    "oauth2_allowed_groups": [],
}
GATED_ADMINISTRATORS_ONLY = {
    "is_proxy_gated": True,
    "oauth2_acl": {},
    "oauth2_allowed_groups": ["/roles/web-app-console/administrator"],
}
SHOP_GATE = {SHOP_APP: (SHOP, GATED_ROOT)}
DASHBOARD_EVERY_NETWORK = [f"https://{DASHBOARD[0]}/", f"http://{DASHBOARD[1]}/"]
SHOP_EVERY_NETWORK = [f"https://{SHOP[0]}", f"http://{SHOP[1]}"]
FORGE_LOGIN_EVERY_NETWORK = [
    f"https://{FORGE[0]}/user/login",
    f"http://{FORGE[1]}/user/login",
]


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def _config(application_id, key, *_fallback):
    if (application_id, key) == ("svc-net-tor", "services.tor.node"):
        return NODE
    if (application_id, key) == ("web-app-dashboard", "services.sso.enabled"):
        return True
    if key == "networks.reachability.handover":
        return False
    raise AssertionError(f"unexpected config lookup: {application_id} {key}")


def _block(lines: list[str], first: str, last: str) -> list[str]:
    start = next(i for i, row in enumerate(lines) if row.startswith(first))
    end = next(i for i, row in enumerate(lines) if i >= start and row.startswith(last))
    return lines[start : end + 1]


def render(
    pass_domain: str, key: str, gates: dict, *blocks: tuple[str, str]
) -> list[str]:
    """Render template lines of the logout Playwright env for one pass.

    Args:
        pass_domain: the logout vhost of the pass, which ``03_run_pass.yml``
            hands to the template as ``domain``.
        key: the env key whose value is returned.
        gates: the deployed logout targets as ``{application_id: (domains,
            sso)}``: their clearnet and onion domain, and the answers of
            ``lookup('sso', application_id, <field>)`` per field.
        blocks: ``(first, last)`` line prefixes of each template block to
            render, so its ``set`` statements run as in the full template.

    Returns:
        The decoded JSON list of ``key``, resolved by Ansible's templar through
        the real ``landing_url``, ``roles_with_service``, ``tls``,
        ``network_handover``, ``network_urls`` and ``network_siblings``
        lookups over a clearnet and onion node.
    """
    lines = read_text(str(TEMPLATE)).splitlines()
    source = "\n".join(
        row for first, last in blocks for row in _block(lines, first, last)
    )
    domains = {APP: LOGOUT, "web-app-dashboard": DASHBOARD} | {
        app: hosts for app, (hosts, _sso) in gates.items()
    }
    applications = {
        app: {
            "domains": {"canonical": [hosts[0]]},
            "services": {"logout": {"enabled": True, "shared": True}},
        }
        for app, (hosts, _sso) in gates.items()
    }

    def sso(application_id, field):
        if application_id in gates and field in gates[application_id][1]:
            return gates[application_id][1][field]
        raise AssertionError(f"unexpected sso lookup: {application_id} {field}")

    stubs = {
        "domains": lambda: domains,
        "applications": lambda: applications,
        "config": _config,
        "sso": sso,
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in stubs:
            return _Stub(stubs[name])
        return real_get(name, *args, **kwargs)

    templar = Templar(
        loader=DataLoader(),
        variables={
            "application_id": APP,
            "domain": pass_domain,
            "DOMAIN_PRIMARY": PRIMARY,
            "TLS_ENABLED": True,
            "TLS_MODE": "letsencrypt",
            "group_names": ["svc-net-tor", "web-app-dashboard", *gates, APP],
        },
    )
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        rendered = templar.template(trust_as_template(source))
    value = next(
        row.removeprefix(f"{key}=")
        for row in rendered.splitlines()
        if row.startswith(f"{key}=")
    )
    return json.loads(dotenv_unquote(value))


def dashboard_urls(pass_domain: str) -> list[str]:
    return render(
        pass_domain,
        "DASHBOARD_URLS_JSON",
        SHOP_GATE,
        ("{% set logout_dashboard_deployed", "DASHBOARD_URLS_JSON="),
    )


def proxy_target_urls(pass_domain: str, gates: dict) -> list[str]:
    return render(
        pass_domain,
        "PROXY_TARGET_URLS_JSON",
        gates,
        ("{% set logout_targets", "LOGOUT_TARGET_ROLES_JSON="),
        ("{% set logout_proxy_target", "PROXY_TARGET_URLS_JSON="),
    )


class TestDashboardUrls(unittest.TestCase):
    def test_a_clearnet_pass_names_every_network_clearnet_first(self) -> None:
        self.assertEqual(dashboard_urls(LOGOUT[0]), DASHBOARD_EVERY_NETWORK)

    def test_an_onion_pass_names_every_network_clearnet_first(self) -> None:
        self.assertEqual(
            dashboard_urls(LOGOUT[1]),
            DASHBOARD_EVERY_NETWORK,
            "the everywhere link of the logout page leads to the clearnet "
            "dashboard and the specs sign in on dashboardUrls[0], so an onion "
            "pass must get the same list as a clearnet one",
        )


class TestProxyTargetUrls(unittest.TestCase):
    def test_a_clearnet_pass_names_every_network_clearnet_first(self) -> None:
        self.assertEqual(proxy_target_urls(LOGOUT[0], SHOP_GATE), SHOP_EVERY_NETWORK)

    def test_an_onion_pass_names_every_network_clearnet_first(self) -> None:
        self.assertEqual(
            proxy_target_urls(LOGOUT[1], SHOP_GATE),
            SHOP_EVERY_NETWORK,
            "logout_targets resolves the proxy target in the pass network, so "
            "an onion pass hands network_urls the onion sibling; the list must "
            "still name both networks or the cross-network logout specs skip",
        )

    def test_a_blacklist_gate_names_the_location_it_gates(self) -> None:
        self.assertEqual(
            proxy_target_urls(
                LOGOUT[1],
                {FORGE_APP: (FORGE, GATED_LOGIN_ONLY), SHOP_APP: (SHOP, GATED_ROOT)},
            ),
            FORGE_LOGIN_EVERY_NETWORK,
            "a blacklist ACL leaves the root of the app outside oauth2-proxy, "
            "so its root never asks for the Keycloak login and the cross-network "
            "logout spec must probe the location the gate covers",
        )

    def test_a_gate_that_admits_only_some_groups_is_passed_over(self) -> None:
        self.assertEqual(
            proxy_target_urls(
                LOGOUT[1],
                {
                    CONSOLE_APP: (CONSOLE, GATED_ADMINISTRATORS_ONLY),
                    SHOP_APP: (SHOP, GATED_ROOT),
                },
            ),
            SHOP_EVERY_NETWORK,
            "biber holds no group of a group-restricted gate, so no proxy "
            "session of biber can exist there for the logout to end",
        )

    def test_no_gate_biber_can_pass_names_no_target(self) -> None:
        self.assertEqual(
            proxy_target_urls(
                LOGOUT[1], {CONSOLE_APP: (CONSOLE, GATED_ADMINISTRATORS_ONLY)}
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
