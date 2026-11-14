"""What each egress route renders into torrc, the dnsmasq drop-in, the nft table,
the host resolver, systemd-resolved and the compose file.

``none`` leaves egress alone, ``onion`` is the old ``egress.enabled: true``
render, and ``all`` fails closed: every filter chain it owns ends in a ``drop``,
established traffic passes only in the reply direction or when this table
admitted the flow, every unlisted TCP flow is redirected to the TransPort, and
DNS reaches only the resolvers the node runs itself.

The container set comes from the real ``tor_egress_clients`` lookup over the
repository's network declarations, because the pools it returns are exactly
what a DNS guard built on them would wrongly admit.
"""

from __future__ import annotations

import base64
import importlib.util
import ipaddress
import re
import sys
import unittest
import unittest.mock as mock

import jinja2
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.networks.tor_egress import plan
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

TEMPLATES = PROJECT_ROOT / "roles/svc-net-tor/templates"
ROUTER = PROJECT_ROOT / "roles/svc-net-tor/tasks/router.yml"
PREFLIGHT = PROJECT_ROOT / "roles/svc-net-tor/tasks/router/preflight.yml"
RESOLVERS = PROJECT_ROOT / "roles/svc-net-tor/tasks/router/resolvers.yml"
CORE = PROJECT_ROOT / "roles/svc-net-tor/tasks/00_core.yml"
REFUSE_NONE = PROJECT_ROOT / "roles/svc-net-tor/tasks/router/refuse_none.yml"
NETWORKS = PROJECT_ROOT / "group_vars/all/08_networks.yml"
TABLE = "infinito_svc_net_tor"
UPSTREAM = "198.51.100.53"
LAN_RESOLVER = "172.30.0.53"
GID = 9050
MARK = "0x544f5200"
DNSMASQ_UID = 977
DNS_PORTS = "{ 53, 853 }"


def _role_subnet(role: str) -> str:
    return load_yaml_any(str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_NETWORKS))[
        "local"
    ]["subnet"]


def _real_client_cidrs() -> list[str]:
    path = PROJECT_ROOT / "roles/svc-net-tor/lookup_plugins/tor_egress_clients.py"
    spec = importlib.util.spec_from_file_location("tor_egress_clients_for_routes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    variables = load_yaml_any(str(NETWORKS))

    class _Templar:
        def template(self, value):
            return (
                jinja2.Environment(
                    autoescape=jinja2.select_autoescape(default_for_string=False)
                )
                .from_string(str(value))
                .render(**variables)
            )

    lookup = module.LookupModule()
    lookup._templar = _Templar()
    lookup._loader = mock.MagicMock()
    with mock.patch.object(module, "lookup_loader") as loader:
        loader.get.return_value = mock.MagicMock(
            run=mock.MagicMock(return_value=[[_role_subnet("web-app-bigbluebutton")]])
        )
        return lookup.run([], variables=variables)[0]


CLIENT_CIDRS = _real_client_cidrs()
RESOLVER_CIDRS = ["127.0.0.0/8", "172.17.0.1", _role_subnet("svc-net-tor")]


def _egress(tor=(), tor_except=(), direct=(), direct_except=()):
    return {
        "tor": {"include": list(tor), "except": list(tor_except)},
        "direct": {"include": list(direct), "except": list(direct_except)},
    }


def _variables(route: str, egress: dict, **overrides) -> dict:
    variables = {
        "SOFTWARE_NAME": "Infinito.Nexus",
        "lookup": lambda *args, **kwargs: "",
        "NETWORK_INTERNAL_CIDRS": [
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ],
        "NETWORK_LOOPBACK_IPV4": "127.0.0.1",
        "TOR_USE_ENTRY_GUARDS": True,
        "TOR_FLAVOR": "public",
        "IS_SWARM_MODE": False,
        "TOR_EGRESS_ROUTE": route,
        "TOR_EGRESS_PLAN": plan(egress, route),
        "TOR_EGRESS_VIRTUAL_NET_IPV4": "10.240.0.0/12",
        "TOR_EGRESS_NFT_TABLE": TABLE,
        "TOR_EGRESS_SOCKET_UID": 0,
        "TOR_EGRESS_SOCKET_GID": GID,
        "TOR_EGRESS_CT_MARK": MARK,
        "TOR_EGRESS_NFTSET_TIMEOUT": "1h",
        "TOR_EGRESS_DNS_MAX_CACHE_TTL": 300,
        "TOR_EGRESS_RESOLVER_PORTS": [53, 853],
        "TOR_EGRESS_RESOLVER_CIDRS": RESOLVER_CIDRS,
        "TOR_EGRESS_NONROUTABLE_IPV4": [
            "169.254.0.0/16",
            "224.0.0.0/4",
            "255.255.255.255",
        ],
        "TOR_EGRESS_LOCAL_IPV6": ["::1", "fe80::/10", "fc00::/7", "ff00::/8"],
        "TOR_DNSMASQ_USER": "dnsmasq",
        "TOR_DNSMASQ_UID": DNSMASQ_UID,
        "TOR_TRANS_PORT": 9040,
        "TOR_DNS_PORT": 9053,
        "TOR_SOCKS_PORT": 9050,
        "TOR_DNSMASQ_PORT": 53,
        "TOR_CONTAINER_DNS_HOST": "172.17.0.1",
        "TOR_NODE_BRIDGE": "172.17.0.1",
        "tor_node": "node",
        "STACK_HOST": "node",
        "TOR_ROUTER_NODES": ["node"],
        "TOR_NODE_ROUTES": route != "none",
        "TOR_ONION_EXTRA_PORTS": [],
        "TOR_HS_BACKEND_HOST": "172.17.0.1",
        "TOR_DNSMASQ_OWNS_LISTENER": True,
        "TOR_NODE_ONION": "",
        "TOR_DNS_UPSTREAMS": [UPSTREAM],
        "FIREWALL_TABLE": TABLE,
        "TOR_EGRESS_CLIENT_CIDRS": CLIENT_CIDRS,
        "TOR_EGRESS_GUARDED_PORTS": [
            {"port": 9040, "protocol": "tcp", "admitted": "containers", "router": True}
        ],
        "TOR_CHUTNEY_GUARDED_PORTS": [],
        "networks": {"internet": {"dns": UPSTREAM}},
        "TOR_CONTAINER": "tor",
        "TOR_IMAGE": "debian",
        "TOR_VERSION": "13.7-slim",
        "TOR_ENTRYPOINT_PATH": "/entrypoint",
        "TOR_HEALTHCHECK_PATH": "/healthcheck",
        "application_id": "svc-net-tor",
    }
    variables.update(overrides)
    return variables


class _NoIncludes(jinja2.BaseLoader):
    def get_source(self, environment, template):
        return "", template, lambda: True


def render(name: str, route: str, egress: dict, **overrides) -> str:
    environment = jinja2.Environment(
        loader=_NoIncludes(),
        trim_blocks=True,
        lstrip_blocks=name == "compose.yml.j2",
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = boolean
    return environment.from_string(read_text(str(TEMPLATES / name))).render(
        **_variables(route, egress, **overrides)
    )


def chain(ruleset: str, name: str) -> list[str]:
    """The rule lines of one chain, hook line and closing brace excluded."""
    lines = ruleset.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == f"chain {name} {{"]
    if not starts:
        raise AssertionError(f"the ruleset declares no chain {name}")
    body = []
    for line in lines[starts[0] + 1 :]:
        if line.strip() == "}":
            break
        body.append(line.strip())
    return [line for line in body if line and not line.startswith("type ")]


def at(rules: list[str], rule: str) -> int:
    """The position of *rule*, failing the test rather than erroring when absent."""
    if rule not in rules:
        raise AssertionError(f"missing rule {rule!r} in {rules}")
    return rules.index(rule)


def set_elements(ruleset: str, name: str) -> list[str]:
    match = re.search(
        rf"set {name} \{{(?P<body>[^}}]*?)(elements = \{{ (?P<elements>[^}}]*) \}})?\s*\}}",
        ruleset,
    )
    if match is None:
        raise AssertionError(f"the ruleset declares no set {name}")
    elements = match.group("elements")
    return [element.strip() for element in elements.split(",")] if elements else []


def covered(address: str, elements: list[str]) -> bool:
    parsed = ipaddress.ip_address(address)
    return any(
        parsed.version == network.version and parsed in network
        for network in (ipaddress.ip_network(e, strict=False) for e in elements)
    )


def assert_none_leaves_egress_alone(case: unittest.TestCase, torrc: str) -> None:
    case.assertNotIn("TransPort", torrc)
    case.assertNotIn("DNSPort", torrc)
    case.assertNotIn("AutomapHostsOnResolve", torrc)


def assert_onion_maps_only_onion(
    case: unittest.TestCase, torrc: str, dnsmasq: str, ruleset: str
) -> None:
    case.assertIn("AutomapHostsSuffixes .onion\n", torrc)
    case.assertNotIn("nftset=", dnsmasq)
    case.assertIn(f"server={UPSTREAM}\n", dnsmasq)
    case.assertNotIn("chain egress_output", ruleset)
    case.assertNotIn("set direct_v4", ruleset)


def assert_chain_fails_closed(case: unittest.TestCase, ruleset: str, name: str) -> None:
    rules = chain(ruleset, name)
    case.assertEqual(
        rules[-1],
        "drop",
        f"{name}: an unlisted destination must meet a drop, not the accept policy",
    )
    case.assertEqual(
        rules[0],
        "ct direction reply accept",
        f"{name}: only replies may skip the rules",
    )
    case.assertFalse(
        [rule for rule in rules if rule.startswith("ct state established")],
        f"{name}: an established original-direction flow from before route all would keep leaving directly",
    )
    accepts = [rule for rule in rules if rule.endswith(" accept")]
    for rule in accepts:
        named = (
            " daddr " in rule
            or "skgid" in rule
            or rule.startswith(
                (
                    "ct direction reply",
                    "ct state related",
                    f"ct mark {MARK}",
                    "fib daddr",
                    "icmpv6 type",
                )
            )
        )
        case.assertTrue(
            named,
            f"{name}: every accept must name a destination, a socket or a flow: {rule}",
        )


def assert_all_fails_closed(case: unittest.TestCase, ruleset: str) -> None:
    assert_chain_fails_closed(case, ruleset, "egress_output")
    assert_chain_fails_closed(case, ruleset, "egress_forward")
    case.assertIn(
        f"meta skuid 0 meta skgid {GID} accept", chain(ruleset, "egress_output")
    )
    nat = chain(ruleset, "output")
    case.assertEqual(nat[-1], "meta nfproto ipv4 meta l4proto tcp redirect to :9040")
    exemption = f"meta skuid 0 meta skgid {GID} return"
    case.assertIn(exemption, nat)
    case.assertLess(
        at(nat, exemption),
        at(nat, "ip daddr @tor_v4 meta l4proto tcp redirect to :9040"),
    )
    case.assertEqual(
        chain(ruleset, "egress_prerouting")[-1],
        "meta nfproto ipv4 meta l4proto tcp dnat ip to 172.17.0.1:9040",
    )


def assert_dns_guard_refuses_lan_resolvers(
    case: unittest.TestCase, ruleset: str
) -> None:
    for name in ("egress_output", "egress_forward"):
        rules = chain(ruleset, name)
        guards = [
            r
            for r in rules
            if r.endswith(f"th dport {DNS_PORTS} drop") and "daddr != @" in r
        ]
        case.assertEqual(
            len(guards), 1, f"{name} needs exactly one IPv4 DNS guard: {rules}"
        )
        guarded_set = re.search(r"daddr != @(\w+)", guards[0]).group(1)
        admitted = set_elements(ruleset, guarded_set)
        case.assertFalse(
            covered(LAN_RESOLVER, admitted),
            f"{name}: the DNS guard admits {LAN_RESOLVER} through @{guarded_set} ({admitted}), "
            "so a LAN resolver answers names Tor should resolve",
        )
        case.assertTrue(
            covered("127.0.0.1", admitted),
            f"{name}: the local dnsmasq must stay reachable",
        )
        case.assertLess(at(rules, guards[0]), at(rules, "ip daddr @internal accept"))
    nat = chain(ruleset, "output")
    case.assertLess(
        at(nat, f"meta l4proto tcp th dport {DNS_PORTS} return"),
        at(nat, "meta nfproto ipv4 meta l4proto tcp redirect to :9040"),
        "TCP DNS to a clearnet resolver must reach the filter's drop, not the TransPort",
    )


def assert_all_resolves_through_tor(
    case: unittest.TestCase, dnsmasq: str, resolv: str
) -> None:
    servers = [
        line
        for line in dnsmasq.splitlines()
        if line.startswith("server=") and "/" not in line
    ]
    case.assertEqual(
        servers,
        ["server=127.0.0.1#9053"],
        "the default upstream must be Tor's DNSPort only",
    )
    case.assertNotIn(
        f"nameserver {UPSTREAM}",
        resolv,
        "a clearnet fallback in resolv.conf bypasses Tor",
    )


def _walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk(task.get(section))


def _task(path, name: str) -> dict:
    tasks = list(_walk(load_yaml_str(read_text(str(path)))))
    found = [task for task in tasks if task.get("name") == name]
    if not found:
        raise AssertionError(f"{path.name} has no task {name!r}")
    return found[0]


class TestNone(unittest.TestCase):
    def test_none_renders_no_router(self) -> None:
        assert_none_leaves_egress_alone(self, render("torrc.j2", "none", _egress()))

    def test_none_keeps_the_compose_user(self) -> None:
        self.assertNotIn("user:", render("compose.yml.j2", "none", _egress()))

    def test_none_is_refused_only_while_the_dnsmasq_drop_in_exists(self) -> None:
        include = _task(
            CORE, "🧹 Refuse route none while an earlier route's resolver is installed"
        )
        self.assertEqual(
            include["ansible.builtin.include_tasks"], "router/refuse_none.yml"
        )
        self.assertEqual(
            include["when"],
            [
                "TOR_EGRESS_ROUTE == 'none'",
                "inventory_hostname in TOR_ROUTER_NODES",
            ],
        )
        fragment = f"{_role_vars('svc-net-firewall')['FIREWALL_FRAGMENT_DIR']}/svc-net-tor.conf"
        dropin = _role_vars("svc-net-tor")["TOR_DNSMASQ_CONF"]
        router = render("nftables.conf.j2", "onion", _egress())
        guard = render("nftables.conf.j2", "none", _egress())
        resolver = render("dnsmasq-tor-onion.conf.j2", "onion", _egress())
        for state, refused in (
            ({}, False),
            ({fragment: guard}, False),
            ({fragment: router}, False),
            ({dropin: resolver}, True),
            ({fragment: guard, dropin: resolver}, True),
            ({fragment: router, dropin: resolver}, True),
        ):
            with self.subTest(
                files=sorted(state), router_fragment=state.get(fragment) == router
            ):
                self.assertEqual(_refuses(state), refused)

    def test_none_swaps_the_router_table_for_the_guard_in_one_load(self) -> None:
        guard = [
            line.strip()
            for line in render("nftables.conf.j2", "none", _egress()).splitlines()
            if line.strip()
        ]
        self.assertEqual(
            guard[:3],
            [
                f"table inet {TABLE}",
                f"delete table inet {TABLE}",
                f"table inet {TABLE} {{",
            ],
        )
        self.assertNotIn("chain output {", guard)


class TestOnion(unittest.TestCase):
    def test_onion_with_only_direct_defaults_is_the_old_router(self) -> None:
        egress = _egress(
            direct=["deb.debian.org", "docker.io", "acme-v02.api.letsencrypt.org"]
        )
        assert_onion_maps_only_onion(
            self,
            render("torrc.j2", "onion", egress),
            render("dnsmasq-tor-onion.conf.j2", "onion", egress),
            render("nftables.conf.j2", "onion", egress),
        )

    def test_onion_keeps_the_clearnet_fallback_resolver(self) -> None:
        self.assertIn(
            f"nameserver {UPSTREAM}", render("resolv.conf.j2", "onion", _egress())
        )

    def test_a_tor_listed_name_resolves_through_tor_and_maps_virtually(self) -> None:
        egress = _egress(tor=["*.example.org"], tor_except=["cdn.example.org"])
        dnsmasq = render("dnsmasq-tor-onion.conf.j2", "onion", egress)
        self.assertIn("server=/example.org/127.0.0.1#9053\n", dnsmasq)
        self.assertIn("server=/cdn.example.org/#\n", dnsmasq)
        self.assertIn("AutomapHostsSuffixes .\n", render("torrc.j2", "onion", egress))

    def test_a_tor_listed_address_is_redirected_and_its_other_protocols_dropped(
        self,
    ) -> None:
        egress = _egress(tor=["198.51.100.0/24"])
        ruleset = render("nftables.conf.j2", "onion", egress)
        self.assertIn("elements = { 198.51.100.0/24 }", ruleset)
        self.assertIn(
            "ip daddr @tor_v4 meta l4proto tcp redirect to :9040",
            chain(ruleset, "output"),
        )
        rules = chain(ruleset, "egress_output")
        self.assertIn("ip daddr @tor_v4 drop", rules)
        self.assertEqual(rules[0], "ct direction reply accept")
        self.assertNotEqual(rules[-1], "drop", "onion does not drop the rest")


class TestAll(unittest.TestCase):
    EGRESS = _egress(
        direct=["*.docker.io", "192.0.2.10"],
        direct_except=["evil.docker.io", "203.0.113.7"],
        tor=["192.0.2.0/24", "secret.docker.io"],
    )

    def ruleset(self) -> str:
        return render("nftables.conf.j2", "all", self.EGRESS)

    def test_all_maps_every_name_virtually(self) -> None:
        self.assertIn(
            "AutomapHostsSuffixes .\n", render("torrc.j2", "all", self.EGRESS)
        )

    def test_all_resolves_unlisted_names_only_through_tor(self) -> None:
        assert_all_resolves_through_tor(
            self,
            render("dnsmasq-tor-onion.conf.j2", "all", self.EGRESS),
            render("resolv.conf.j2", "all", self.EGRESS),
        )

    def test_dnsmasq_drops_to_its_own_user_and_bounds_its_cache(self) -> None:
        dnsmasq = render("dnsmasq-tor-onion.conf.j2", "all", self.EGRESS)
        self.assertIn("user=dnsmasq\n", dnsmasq)
        self.assertIn("max-cache-ttl=300\n", dnsmasq)

    def test_listed_names_fill_the_expiring_sets(self) -> None:
        dnsmasq = render("dnsmasq-tor-onion.conf.j2", "all", self.EGRESS)
        self.assertIn(f"server=/docker.io/{UPSTREAM}\n", dnsmasq)
        self.assertIn(
            f"nftset=/docker.io/4#inet#{TABLE}#direct_dns_v4,6#inet#{TABLE}#direct_dns_v6\n",
            dnsmasq,
        )
        self.assertIn("server=/evil.docker.io/127.0.0.1#9053\n", dnsmasq)
        self.assertIn(
            f"nftset=/evil.docker.io/4#inet#{TABLE}#tor_dns_v4,6#inet#{TABLE}#tor_dns_v6\n",
            dnsmasq,
            "dnsmasq picks the longest nftset match on its own, so a carve-out "
            "without one would land in the direct set of its parent",
        )
        ruleset = self.ruleset()
        for name in ("direct_dns_v4", "tor_dns_v4"):
            body = re.search(rf"set {name} \{{([^}}]*)\}}", ruleset).group(1)
            self.assertIn("flags timeout", body)
            self.assertIn("timeout 1h", body)

    def test_all_fails_closed(self) -> None:
        assert_all_fails_closed(self, self.ruleset())

    def test_the_dns_guard_refuses_lan_resolvers_inside_the_pools(self) -> None:
        self.assertTrue(
            covered(LAN_RESOLVER, CLIENT_CIDRS),
            "the fixture must sit inside a real client pool",
        )
        assert_dns_guard_refuses_lan_resolvers(self, self.ruleset())

    def test_only_flows_this_table_admitted_skip_the_rules(self) -> None:
        for name in ("egress_output", "egress_forward"):
            rules = chain(self.ruleset(), name)
            self.assertIn(f"ct mark {MARK} accept", rules)
            self.assertIn(f"ip daddr @direct_dns_v4 ct mark set {MARK} accept", rules)
            self.assertLess(
                at(rules, "ip daddr @tor_v4 drop"), at(rules, f"ct mark {MARK} accept")
            )

    def test_forwarded_ipv6_and_foreign_sources_meet_the_drop(self) -> None:
        rules = chain(self.ruleset(), "egress_forward")
        self.assertIn("ip6 daddr @local_v6 accept", rules)
        self.assertLess(
            at(rules, "ip6 daddr @direct_dns_v6 ct mark set 0x544f5200 accept"),
            len(rules) - 1,
        )
        self.assertFalse([r for r in rules if r.startswith("ip saddr != @containers")])
        self.assertFalse(
            [r for r in rules if "jump" in r],
            "a jump returns into a chain without a drop",
        )

    def test_tor_wins_over_direct_for_an_address_in_both(self) -> None:
        ruleset = self.ruleset()
        rules = chain(ruleset, "egress_output")
        self.assertLess(
            at(rules, "ip daddr @tor_v4 drop"), at(rules, "ip daddr @direct_v4 accept")
        )
        nat = chain(ruleset, "output")
        self.assertLess(
            at(nat, "ip daddr @tor_v4 meta l4proto tcp redirect to :9040"),
            at(nat, "ip daddr @direct_v4 return"),
        )

    def test_an_address_except_also_removes_resolved_direct_addresses(self) -> None:
        ruleset = self.ruleset()
        self.assertEqual(set_elements(ruleset, "direct_except_v4"), ["203.0.113.7"])
        for name in ("egress_output", "egress_forward"):
            rules = chain(ruleset, name)
            self.assertLess(
                at(rules, "ip daddr @direct_except_v4 drop"),
                at(rules, "ip daddr @direct_v4 accept"),
            )
            self.assertLess(
                at(rules, "ip daddr @direct_except_v4 drop"),
                at(rules, f"ip daddr @direct_dns_v4 ct mark set {MARK} accept"),
            )
        nat = chain(ruleset, "output")
        self.assertLess(
            at(nat, "ip daddr @direct_except_v4 meta l4proto tcp redirect to :9040"),
            at(nat, "ip daddr @direct_dns_v4 return"),
        )

    def test_dns_leaves_only_from_dnsmasq_to_its_upstream(self) -> None:
        rules = chain(self.ruleset(), "egress_output")
        upstream = f"meta skuid {DNSMASQ_UID} ip daddr {UPSTREAM} meta l4proto {{ tcp, udp }} th dport 53 accept"
        dns_drop = f"ip daddr != @resolvers meta l4proto {{ tcp, udp }} th dport {DNS_PORTS} drop"
        self.assertLess(at(rules, upstream), at(rules, dns_drop))

    def test_neighbour_discovery_keeps_working(self) -> None:
        rules = chain(self.ruleset(), "egress_output")
        self.assertIn(
            "icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } accept",
            rules,
        )

    def test_all_gives_tor_its_own_group(self) -> None:
        self.assertIn(f'user: "0:{GID}"', render("compose.yml.j2", "all", self.EGRESS))


class TestResolvedUnderAll(unittest.TestCase):
    def test_resolved_forwards_to_dnsmasq_without_fallback(self) -> None:
        dropin = render("resolved-tor-egress.conf.j2", "all", _egress())
        self.assertIn("DNS=127.0.0.1\n", dropin)
        self.assertIn("FallbackDNS=\n", dropin)
        self.assertIn("Domains=~.\n", dropin)

    def test_nsswitch_loses_resolve_under_all(self) -> None:
        task = _task(
            RESOLVERS,
            "🔀 Egress router | Take systemd-resolved out of host name lookups",
        )
        spec = task["ansible.builtin.lineinfile"]
        pattern = re.compile(spec["regexp"])
        cases = {
            "hosts: mymachines resolve [SUCCESS=return NOTFOUND=continue TRYAGAIN=return] files myhostname dns": (
                "hosts: mymachines files myhostname dns"
            ),
            "hosts: files resolve dns": "hosts: files dns",
            "hosts: files dns resolve": "hosts: files dns",
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                match = pattern.match(line)
                self.assertIsNotNone(match)
                self.assertEqual(match.expand(spec["line"]), expected)
        self.assertIsNone(
            pattern.match("hosts: files dns"), "a second run must change nothing"
        )
        block = _task(
            ROUTER, "🔀 Egress router | Keep systemd-resolved from resolving beside Tor"
        )
        self.assertEqual(block["when"], "TOR_EGRESS_ROUTE == 'all'")


def _evaluate(expression: str, variables: dict, conditional: bool):
    templar = Templar(loader=DataLoader(), variables=variables)
    trusted = _trust_as_template(expression)
    return (
        templar.evaluate_conditional(trusted)
        if conditional
        else templar.template(trusted)
    )


def _slurped(text: str) -> dict:
    return {"content": base64.b64encode(text.encode()).decode()}


def _role_filters() -> dict:
    path = PROJECT_ROOT / "roles/svc-net-tor/filter_plugins/tor_egress.py"
    spec = importlib.util.spec_from_file_location("tor_egress_filters_for_routes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def _that(path, name: str) -> str:
    return _task(path, name)["ansible.builtin.assert"]["that"][0]


_PATH_ABSOLUTE = re.compile(r"lookup\('path_absolute', '([^']+)'\)")


def _role_vars(role: str) -> dict:
    return load_yaml_any(str(PROJECT_ROOT / "roles" / role / ROLE_FILE_VARS_MAIN))


def _conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else when


def _stat(task: dict, variables: dict, state: dict[str, str]) -> dict:
    if "loop" not in task:
        path = _evaluate(task["ansible.builtin.stat"]["path"], variables, False)
        return {"stat": {"exists": path in state}}
    items = [_evaluate(item, variables, False) for item in task["loop"]]
    return {
        "results": [{"item": item, "stat": {"exists": item in state}} for item in items]
    }


def _slurp(task: dict, variables: dict, state: dict[str, str]) -> dict:
    return _slurped(
        state[_evaluate(task["ansible.builtin.slurp"]["src"], variables, False)]
    )


def _include_vars(task: dict, variables: dict, state: dict[str, str]) -> dict:
    path = _PATH_ABSOLUTE.search(task["ansible.builtin.include_vars"]["file"])
    return load_yaml_any(str(PROJECT_ROOT / path.group(1)))


_PLAYED = {
    "ansible.builtin.stat": _stat,
    "ansible.builtin.slurp": _slurp,
    "ansible.builtin.include_vars": _include_vars,
}


def _register(task: dict) -> str:
    if "ansible.builtin.include_vars" in task:
        return task["ansible.builtin.include_vars"]["name"]
    return task["register"]


def _holds(task: dict, variables: dict) -> bool:
    scope = {
        **variables,
        **{
            name: _evaluate(value, variables, False)
            for name, value in (task.get("vars") or {}).items()
        },
    }
    return all(
        _evaluate(condition, scope, conditional=True)
        for condition in task["ansible.builtin.assert"]["that"]
    )


def _refuses(state: dict[str, str]) -> bool:
    """
    Args:
        state: the files on the node, each path mapped to its content.

    Returns:
        Whether ``router/refuse_none.yml``, played against that node, refuses
        route none.
    """
    variables = {
        "application_id": "svc-net-tor",
        "TOR_DNSMASQ_CONF": _role_vars("svc-net-tor")["TOR_DNSMASQ_CONF"],
    }
    for task in load_yaml_str(read_text(str(REFUSE_NONE))):
        if not all(_evaluate(c, variables, True) for c in _conditions(task)):
            if "register" in task:
                variables[task["register"]] = {"skipped": True}
        elif "ansible.builtin.assert" in task:
            if not _holds(task, variables):
                return True
        else:
            (module,) = set(task) & set(_PLAYED)
            variables[_register(task)] = _PLAYED[module](task, variables, state)
    return False


class TestRouteAllPreflight(unittest.TestCase):
    def test_the_preflight_runs_under_route_all_only(self) -> None:
        include = _task(
            ROUTER,
            "✅ Egress router | Check what route all depends on before touching dnsmasq",
        )
        self.assertEqual(
            include["ansible.builtin.include_tasks"]["file"], "router/preflight.yml"
        )
        self.assertEqual(include["when"], "TOR_EGRESS_ROUTE == 'all'")

    def test_only_a_dnsmasq_without_foreign_drop_ins_is_ours(self) -> None:
        derive = _task(
            ROUTER, "🔧 Egress router | Decide whether this dnsmasq is ours to reshape"
        )["ansible.builtin.set_fact"]["TOR_DNSMASQ_OWNS_LISTENER"]
        for matched, owns in ((0, True), (1, False), (3, False)):
            with self.subTest(matched=matched):
                self.assertEqual(
                    _evaluate(
                        derive,
                        {"_tor_dnsmasq_foreign": {"matched": matched}},
                        conditional=False,
                    ),
                    owns,
                )

    def test_a_dnsmasq_other_drop_ins_shape_is_refused(self) -> None:
        that = _that(
            PREFLIGHT,
            "✅ Egress router | Refuse route all on a dnsmasq another drop-in shapes",
        )
        for owns, passes in ((True, True), (False, False)):
            with self.subTest(owns=owns):
                self.assertEqual(
                    _evaluate(
                        that, {"TOR_DNSMASQ_OWNS_LISTENER": owns}, conditional=True
                    ),
                    passes,
                )

    def test_a_tor_group_the_host_already_knows_is_refused(self) -> None:
        lookup = _task(
            PREFLIGHT, "🔎 Egress router | Look up the group Tor's sockets carry"
        )
        self.assertEqual(lookup["failed_when"], "_tor_egress_gid.rc not in [0, 2]")
        that = _that(
            PREFLIGHT,
            "✅ Egress router | Refuse a Tor group the host already hands out",
        )
        for rc, passes in ((2, True), (0, False)):
            with self.subTest(rc=rc):
                self.assertEqual(
                    _evaluate(that, {"_tor_egress_gid": {"rc": rc}}, conditional=True),
                    passes,
                )

    def test_a_clearnet_upstream_inside_the_resolver_set_is_refused(self) -> None:
        that = _that(
            PREFLIGHT,
            "✅ Egress router | Refuse a clearnet resolver every process may reach",
        )
        environment = jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False)
        )
        environment.filters.update(_role_filters())
        check = environment.compile_expression(that)
        tor_subnet_host = str(
            next(ipaddress.ip_network(_role_subnet("svc-net-tor")).hosts())
        )
        cases = {
            UPSTREAM: True,
            "127.0.0.53": False,
            "172.17.0.1": False,
            tor_subnet_host: False,
        }
        for upstream, passes in cases.items():
            with self.subTest(upstream=upstream):
                self.assertEqual(
                    check(
                        TOR_DNS_UPSTREAMS=[upstream],
                        TOR_EGRESS_RESOLVER_CIDRS=RESOLVER_CIDRS,
                    ),
                    passes,
                )

    def test_listed_host_names_need_a_dnsmasq_built_with_nftset(self) -> None:
        block = _task(
            PREFLIGHT, "🔎 Egress router | Require nftset for listed host names"
        )
        self.assertEqual(block["when"], "TOR_EGRESS_PLAN.dns | length > 0")
        self.assertTrue(plan(_egress(direct=["deb.debian.org"]), "all")["dns"])
        self.assertFalse(plan(_egress(direct=["198.51.100.0/24"]), "all")["dns"])
        that = _that(
            PREFLIGHT,
            "✅ Egress router | Refuse list rules on a dnsmasq without nftset",
        )
        options = "Compile time options: IPv6 GNU-getopt DBus i18n IDN2 DHCP conntrack ipset {} auth DNSSEC"
        cases = {
            options.format("nftset"): True,
            options.format("no-nftset"): False,
            options.format(""): False,
        }
        for stdout, passes in cases.items():
            with self.subTest(stdout=stdout):
                self.assertEqual(
                    _evaluate(
                        that,
                        {"_tor_dnsmasq_version": {"stdout": stdout}},
                        conditional=True,
                    ),
                    passes,
                )

    def test_a_dnsmasq_resolving_as_root_or_nobody_is_refused(self) -> None:
        that = _that(
            RESOLVERS,
            "✅ Egress router | Refuse a dnsmasq that resolves as root or nobody",
        )
        for uid, passes in ((DNSMASQ_UID, True), (0, False), (65534, False)):
            with self.subTest(uid=uid):
                self.assertEqual(
                    _evaluate(that, {"TOR_DNSMASQ_UID": str(uid)}, conditional=True),
                    passes,
                )

    def test_a_dnsmasq_uid_other_processes_share_is_refused(self) -> None:
        that = _that(
            RESOLVERS, "✅ Egress router | Refuse a dnsmasq UID other processes share"
        )
        cases = {
            ("4711",): True,
            ("4711", "4712"): False,
        }
        for uid_pids, passes in cases.items():
            with self.subTest(uid_pids=uid_pids):
                self.assertEqual(
                    _evaluate(
                        that,
                        {
                            "_tor_dnsmasq_uid_pids": {"stdout_lines": list(uid_pids)},
                            "_tor_dnsmasq_pids": {"stdout_lines": ["4711"]},
                        },
                        conditional=True,
                    ),
                    passes,
                )

    def test_upstreams_in_the_main_dnsmasq_configuration_are_refused(self) -> None:
        task = _task(
            PREFLIGHT,
            "✅ Egress router | Refuse upstreams the main dnsmasq configuration adds",
        )
        that = task["ansible.builtin.assert"]["that"][0]
        cases = {
            "conf-dir=/etc/dnsmasq.d/,*.conf\n#server=192.0.2.53\n": True,
            "server=192.0.2.53\n": False,
            "  resolv-file = /etc/resolv.dnsmasq\n": False,
            "servers-file=/etc/dnsmasq.servers\n": False,
            "conf-file=/etc/dnsmasq.extra\n": False,
        }
        for text, passes in cases.items():
            with self.subTest(text=text):
                self.assertEqual(
                    _evaluate(
                        that, {"_tor_dnsmasq_main": _slurped(text)}, conditional=True
                    ),
                    passes,
                )

    def test_the_effective_uid_of_dnsmasq_is_read(self) -> None:
        task = _task(RESOLVERS, "🔎 Egress router | Take the effective UID of dnsmasq")
        status = "Name:\tdnsmasq\nUid:\t0\t977\t977\t977\nGid:\t0\t977\t977\t977\n"
        uid = _evaluate(
            task["ansible.builtin.set_fact"]["TOR_DNSMASQ_UID"],
            {"_tor_dnsmasq_status": _slurped(status)},
            conditional=False,
        )
        self.assertEqual(
            str(uid),
            "977",
            "the second Uid field is the effective one dnsmasq dropped to",
        )


if __name__ == "__main__":
    unittest.main()
