import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.network_of import FilterModule as NetworkFilters
from plugins.filter.timeout_start_sec_for_domains import FilterModule as TimeoutFilters
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "sys-ctl-hlth-csp" / "tasks" / "00_core.yml"
TOR_SOCKS = "127.0.0.1:9050"
ONION_TIMEOUT_MS = 90000
ONION_DOMAIN_SECONDS = 600
ONION = "a" * 56 + ".onion"
VARIABLES = {
    "system_service_script_exec": "/usr/bin/python3 /opt/csp/script.py",
    "HEALTH_CSP_IMAGE": "csp-checker:1",
    "HEALTH_CSP_CLEARNET_TIMEOUT_MS": 20000,
    "HEALTH_CSP_CONCURRENCY": 4,
    "HEALTH_CSP_ALWAYS_PULL": False,
    "HEALTH_CSP_IGNORE_NETWORK_BLOCKS_FROM": [],
    "HEALTH_CSP_SKIP_DOMAINS": [],
    "HEALTH_CSP_ACCEPT_STATUS": [],
    "HEALTH_CSP_ONION_TIMEOUT_MS": ONION_TIMEOUT_MS,
    "HEALTH_CSP_TOR_PROXY_BYPASS": [".example.org"],
    "HEALTH_CSP_TOR_CONFINE_ALLOW": ["auth.example.org"],
    "HEALTH_CSP_ONION_DOMAIN_SECONDS": ONION_DOMAIN_SECONDS,
}


def render(key: str, tor_node: str = "", **variables) -> str:
    """
    Args:
        key: a var the role hands to sys-service.
        tor_node: what ``services.tor.node`` of svc-net-tor answers.
        variables: further play variables.

    Returns:
        The rendered value.
    """
    (task,) = [
        task
        for task in load_yaml_any(str(TASKS))
        if task.get("include_role", {}).get("name") == "sys-service"
    ]

    def lookup(name, *terms):
        if name == "nginx":
            return "/etc/nginx/conf.d/servers"
        if name == "tor_socks":
            return TOR_SOCKS
        if name == "config" and terms[:2] == ("svc-net-tor", "services.tor.node"):
            return tor_node
        raise AssertionError(f"unexpected lookup {name!r} {terms!r}")

    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(CoreFilters().filters())
    env.filters.update(NetworkFilters().filters())
    env.filters.update(TimeoutFilters().filters())
    return env.from_string(task["vars"][key]).render(
        lookup=lookup, **VARIABLES, **variables
    )


class TestOnionTimeoutIsPassed(unittest.TestCase):
    def test_the_tor_branch_also_carries_the_onion_budget(self) -> None:
        words = render("system_service_tpl_exec_start", tor_node="tor-node").split()
        self.assertIn(f"--tor-proxy=socks5://{TOR_SOCKS}", words)
        self.assertIn(
            f"--onion-timeout={ONION_TIMEOUT_MS}",
            words,
            "the service reaches onion vhosts over Tor, where the checker's own "
            "20 s navigation budget expires before a heavy page finishes; pass "
            "--onion-timeout wherever --tor-proxy is passed",
        )

    def test_a_host_without_tor_passes_neither_tor_flag(self) -> None:
        words = render("system_service_tpl_exec_start").split()
        self.assertEqual(
            [word for word in words if word.startswith(("--tor-", "--onion-"))], []
        )

    def test_the_unit_start_budget_knows_the_onion_rate(self) -> None:
        domains = {"web-app-x": [f"x.{ONION}"]}
        budget = TimeoutFilters().timeout_start_sec_for_domains
        rendered = int(
            render(
                "system_service_tpl_timeout_start_sec",
                CURRENT_PLAY_DOMAINS_ALL=domains,
            )
        )
        self.assertEqual(
            rendered, budget(domains, onion_per_domain_seconds=ONION_DOMAIN_SECONDS)
        )
        self.assertGreater(
            rendered,
            budget(domains),
            "TimeoutStartSec defaults to 25 s per domain, which an onion vhost "
            "with a multiplied navigation budget outlasts; systemd then kills "
            "the check mid-run instead of letting it report",
        )


if __name__ == "__main__":
    unittest.main()
