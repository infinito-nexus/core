from __future__ import annotations

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from urllib.parse import urlsplit

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from jinja2 import Environment, select_autoescape

from plugins.lookup.node_hosts import SWARM_GROUP
from plugins.lookup.node_hosts import LookupModule as NodeHosts
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from .test_export_config import EMAIL, VARS, stubbed, templar

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
WORKSPACE_PY = ROLE / "files" / "python" / "workspace.py"
TEMPLATES = ROLE / "templates" / "workspace"
PLAYWRIGHT_ENV = ROLE / "templates" / "playwright.env.j2"
HOST_ADDRESSES = "SEMAPHORE_WORKSPACE_HOST_ADDRESSES_JSON"
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
HOSTS_FILE = VOLUMES["semaphore_egress_hosts"]["mounts"][0]["target"]
PLATFORM = [
    {"host": "semaphore.example.org", "port": 443},
    {"host": "git.example.org", "port": 2201},
]
CLOSED = ["127.0.0.0/8", "169.254.0.0/16", "fe80::/10", "192.0.2.1"]
PUBLIC = "93.184.216.34"
NODES = {
    "manager": {
        "all_ipv4_addresses": ["192.0.2.10", "172.17.0.1"],
        "all_ipv6_addresses": ["2001:db8::10"],
    },
    "worker": {
        "all_ipv4_addresses": ["192.0.2.20", "172.17.0.1"],
        "all_ipv6_addresses": ["2001:db8::20"],
    },
}


def load(path, name):
    spec = spec_from_file_location(name, str(path))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def render(name, targets, platform=PLATFORM):
    """Args:
    name: ``squid.conf`` or ``hosts``.
    targets: the pinned targets.
    platform: the platform services the proxy lets through.

    Returns:
        The rendered file.
    """
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    return environment.from_string(read_text(str(TEMPLATES / f"{name}.j2"))).render(
        semaphore_workspace_platform=platform,
        semaphore_workspace_targets=targets,
        semaphore_workspace_closed=CLOSED,
        SEMAPHORE_EGRESS_HOSTS_FILE=HOSTS_FILE,
    )


def export_egress(declared=None):
    """Args:
    declared: ``SEMAPHORE_EXPORT_EGRESS`` as declared, that of ``vars/main.yml`` when None.

    Returns:
        ``(egress, variables)``: the rendered egress list of the export runner
        as ``(host, port)`` pairs and the rendered ``SEMAPHORE_EXPORT_VARIABLES``.
    """
    engine, stubs = templar()
    with stubbed(stubs):
        egress = engine.template(
            engine.available_variables["SEMAPHORE_EXPORT_EGRESS"]
            if declared is None
            else declared
        )
        variables = engine.template(
            engine.available_variables["SEMAPHORE_EXPORT_VARIABLES"]
        )
    return [(pair["host"], int(pair["port"])) for pair in egress], variables


def export_egress_findings(egress, variables):
    """Args:
    egress: the egress list of the export runner as ``(host, port)`` pairs.
    variables: the rendered ``SEMAPHORE_EXPORT_VARIABLES``.

    Returns:
        Every service of OpenBao, Keycloak, the S3 endpoint and the mail relay
        the list lacks, and every pair it names beyond them.
    """
    services = {
        "OpenBao": variables["BAO_ADDR"],
        "Keycloak": variables["EXPORT_KEYCLOAK_URL"],
        "the S3 endpoint": variables["EXPORT_S3_ENDPOINT"],
    }
    allowed = {
        name: (parts.hostname, parts.port or 443)
        for name, parts in ((n, urlsplit(url)) for n, url in services.items())
    }
    allowed["the mail relay"] = (
        variables["EXPORT_MAIL_HOST"],
        int(variables["EXPORT_MAIL_PORT"]),
    )
    findings = [
        f"{name} is missing" for name, pair in allowed.items() if pair not in egress
    ]
    findings += [
        f"{host}:{port} is no export service"
        for host, port in egress
        if (host, port) not in allowed.values()
    ]
    return findings


def export_proxy(declared=None):
    """Args:
    declared: ``SEMAPHORE_EXPORT_PROXY`` as declared, that of ``vars/main.yml`` when None.

    Returns:
        ``(pairs, allowed)``: the rendered proxy list of the export runner and
        the five pairs it must hold, the four task endpoints of
        ``SEMAPHORE_EXPORT_EGRESS`` and the Semaphore server at
        ``SEMAPHORE_WEB_ROOT``, each as ``(host, port)``.
    """
    engine, stubs = templar()
    variables = engine.available_variables
    with stubbed(stubs):
        pairs = engine.template(
            variables["SEMAPHORE_EXPORT_PROXY"]
            if declared is None
            else trust_as_template(declared)
        )
        server = urlsplit(engine.template(variables["SEMAPHORE_WEB_ROOT"]))
    egress, _ = export_egress()
    allowed = [*egress, (server.hostname, server.port or 443)]
    return [(pair["host"], int(pair["port"])) for pair in pairs], allowed


def export_proxy_findings(pairs, allowed):
    """Args:
    pairs: see :func:`export_proxy`.
    allowed: see :func:`export_proxy`.

    Returns:
        Every allowed pair the list lacks and every pair it names beyond them.
    """
    return [
        f"{host}:{port} is missing"
        for host, port in allowed
        if (host, port) not in pairs
    ] + [
        f"{host}:{port} is no export or server pair"
        for host, port in pairs
        if (host, port) not in allowed
    ]


def egress_closed(host, nodes, declared=None):
    """Args:
    host: the inventory host the render runs on.
    nodes: the hosts of the swarm group, none outside swarm.
    declared: ``SEMAPHORE_EGRESS_CLOSED`` as declared, that of ``vars/main.yml`` when None.

    Returns:
        The closed list the egress proxy of a workspace or of the export runner
        gets when *host* renders it.
    """
    engine, stubs = templar()
    variables = {
        **engine.available_variables,
        "inventory_hostname": host,
        "groups": {SWARM_GROUP: list(nodes)} if nodes else {},
        "hostvars": {name: {"ansible_facts": facts} for name, facts in NODES.items()},
        "ansible_facts": NODES[host],
    }
    engine = Templar(loader=DataLoader(), variables=variables)
    with stubbed({**stubs, "node_hosts": NodeHosts()}):
        return engine.template(
            variables["SEMAPHORE_EGRESS_CLOSED"]
            if declared is None
            else trust_as_template(declared)
        )


def host_addresses_line():
    """Returns:
    The ``HOST_ADDRESSES`` line of ``templates/playwright.env.j2``.
    """
    return next(
        entry
        for entry in read_text(str(PLAYWRIGHT_ENV)).splitlines()
        if entry.startswith(f"{HOST_ADDRESSES}=")
    )


def host_address_findings(line=None):
    """Args:
    line: the env line to render, that of ``templates/playwright.env.j2`` when None.

    Returns:
        Every address of ``NODES`` a render on one node of the two-node swarm
        leaves unprobed, every probed address the egress proxy leaves open,
        and every render that probes an address twice.
    """
    addresses = {
        address
        for facts in NODES.values()
        for family in ("all_ipv4_addresses", "all_ipv6_addresses")
        for address in facts[family]
    }
    findings = []
    for host in NODES:
        probed = probed_host_addresses(host, line=line)
        findings += [
            f"a render on {host} leaves {address} unprobed"
            for address in sorted(addresses - set(probed))
        ]
        findings += [
            f"a render on {host} probes {address}, which the proxy leaves open"
            for address in sorted(set(probed) - set(egress_closed(host, NODES)))
        ]
        if len(probed) != len(set(probed)):
            findings.append(f"a render on {host} probes an address twice")
    return findings


def probed_host_addresses(host, enabled=True, line=None):
    """Args:
    host: the inventory host the Playwright env renders on.
    enabled: ``SEMAPHORE_WORKSPACES_ENABLED``.
    line: the env line to render, that of ``templates/playwright.env.j2`` when None.

    Returns:
        The host addresses the egress spec probes as closed, rendered on a
        node of the two-node swarm of ``NODES``.
    """
    if line is None:
        line = host_addresses_line()
    expression = line.partition("=")[2].removesuffix(" | to_json | dotenv_quote }}")
    variables = {
        "inventory_hostname": host,
        "groups": {SWARM_GROUP: list(NODES)},
        "hostvars": {name: {"ansible_facts": facts} for name, facts in NODES.items()},
        "SEMAPHORE_WORKSPACES_ENABLED": enabled,
    }
    engine = Templar(loader=DataLoader(), variables=variables)
    with stubbed({"node_hosts": NodeHosts()}):
        return engine.template(trust_as_template(f"{expression} }}}}"))


def closed_findings(declared=None):
    """Args:
    declared: see :func:`egress_closed`.

    Returns:
        Every node address a render on one node of a two-node swarm leaves
        open, and every closed range of ``SEMAPHORE_WORKSPACE_CLOSED`` it drops.
    """
    ranges = templar()[0].available_variables["SEMAPHORE_WORKSPACE_CLOSED"]
    addresses = {
        address
        for facts in NODES.values()
        for family in ("all_ipv4_addresses", "all_ipv6_addresses")
        for address in facts[family]
    }
    findings = []
    for host in NODES:
        closed = set(egress_closed(host, NODES, declared))
        findings += [
            f"a render on {host} leaves {address} open"
            for address in sorted((addresses | set(ranges)) - closed)
        ]
    return findings


def connect_pairs(config):
    """Args:
    config: a rendered ``squid.conf``.

    Returns:
        The ``(host, port)`` pairs its platform rules let through.
    """
    lines = config.splitlines()
    hosts = {
        line.split()[1]: line.split()[3]
        for line in lines
        if line.startswith("acl platform_") and " dstdomain " in line
    }
    ports = {
        line.split()[1]: int(line.split()[3])
        for line in lines
        if line.startswith("acl platform_") and " port " in line
    }
    return [
        (hosts[rule.split()[3]], ports[rule.split()[4]])
        for rule in lines
        if rule.startswith("http_access allow CONNECT platform_")
    ]


def order_findings(config):
    """Args:
    config: a rendered ``squid.conf``.

    Returns:
        Why a target could reach a closed range or an unlisted pair.
    """
    rules = [line for line in config.splitlines() if line.startswith("http_access")]
    closed = (
        rules.index("http_access deny closed")
        if "http_access deny closed" in rules
        else None
    )
    findings = []
    if closed is None:
        findings.append("no rule denies the closed ranges")
    elif any("target_" in rule for rule in rules[:closed]):
        findings.append("a target is allowed before the closed ranges are denied")
    if rules[-1:] != ["http_access deny all"]:
        findings.append("the last rule does not deny every other target")
    return findings


class TestWorkspaceEgress(unittest.TestCase):
    def setUp(self):
        self.workspace = load(WORKSPACE_PY, "semaphore_workspace_egress")

    def pin(self, address, private=()):
        return self.workspace.pin_targets(
            [("target.example.org", 22)], list(private), lambda host: address
        )

    def test_apply_pins_target_addresses(self):
        pinned = self.pin(PUBLIC)
        self.assertEqual(
            pinned, [{"host": "target.example.org", "port": 22, "address": PUBLIC}]
        )
        self.assertIn(
            f"acl target_1_address dst {PUBLIC}", render("squid.conf", pinned)
        )
        self.assertEqual(
            render("hosts", pinned).strip(), f"{PUBLIC} target.example.org"
        )

    def test_apply_refuses_a_target_in_a_closed_range(self):
        for address, private in (
            ("169.254.169.254", ["169.254.0.0/16"]),
            ("127.0.0.1", ["127.0.0.0/8"]),
            ("::1", []),
            ("10.0.0.5", []),
        ):
            with self.subTest(address), self.assertRaises(self.workspace.RefusalError):
                self.pin(address, private)

    def test_a_private_target_needs_its_network_listed(self):
        self.assertEqual(
            self.pin("10.0.0.5", ["10.0.0.0/24"])[0]["address"], "10.0.0.5"
        )

    def test_the_proxy_denies_closed_ranges_before_any_target(self):
        config = render("squid.conf", self.pin(PUBLIC))
        self.assertEqual(order_findings(config), [])
        self.assertIn(
            "acl closed dst 127.0.0.0/8 169.254.0.0/16 fe80::/10 192.0.2.1", config
        )

    def test_negative_control_a_target_before_the_closed_deny_is_reported(self):
        config = render("squid.conf", self.pin(PUBLIC))
        rules = config.splitlines()
        target = next(
            line
            for line in rules
            if line.startswith("http_access allow CONNECT target_")
        )
        rules.remove(target)
        rules.insert(rules.index("http_access deny closed"), target)
        self.assertEqual(
            order_findings("\n".join(rules)),
            ["a target is allowed before the closed ranges are denied"],
        )

    def test_the_proxy_reads_the_hosts_file_where_the_egress_mounts_it(self):
        self.assertIn(f"hosts_file {HOSTS_FILE}\n", render("squid.conf", []))

    def test_an_empty_target_list_leaves_the_platform_services_only(self):
        config = render("squid.conf", [])
        allowed = [
            line for line in config.splitlines() if line.startswith("http_access allow")
        ]
        self.assertEqual(len(allowed), len(PLATFORM))
        self.assertEqual(order_findings(config), [])

    def test_the_export_runner_egress_list(self):
        egress, variables = export_egress()
        self.assertEqual(export_egress_findings(egress, variables), [])
        self.assertEqual(len(egress), 4)
        self.assertIn((EMAIL["host"], EMAIL["port"]), egress)
        self.assertIn(("auth.example.org", 443), egress)
        config = render(
            "squid.conf", [], platform=[{"host": h, "port": p} for h, p in egress]
        )
        self.assertEqual(connect_pairs(config), egress)
        self.assertEqual(order_findings(config), [])

    def test_negative_control_an_unlisted_export_service_is_reported(self):
        declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
        gitea = declared["SEMAPHORE_WORKSPACE_PLATFORM"][1]
        self.assertIn("web-app-gitea", gitea["host"])
        egress, variables = export_egress(declared["SEMAPHORE_EXPORT_EGRESS"] + [gitea])
        self.assertEqual(
            export_egress_findings(egress, variables),
            ["web-app-gitea.example.org:443 is no export service"],
        )

    def test_negative_control_a_missing_export_service_is_reported(self):
        declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)[
            "SEMAPHORE_EXPORT_EGRESS"
        ]
        relay = [pair for pair in declared if "EXPORT_MAIL_HOST" not in pair["host"]]
        self.assertEqual(len(relay), len(declared) - 1)
        egress, variables = export_egress(relay)
        self.assertEqual(
            export_egress_findings(egress, variables), ["the mail relay is missing"]
        )

    def test_the_export_proxy_lets_through_exactly_the_tasks_and_the_server(self):
        pairs, allowed = export_proxy()
        self.assertEqual(export_proxy_findings(pairs, allowed), [])
        self.assertEqual(len(pairs), 5)
        self.assertIn(("web-app-semaphore.example.org", 443), pairs)
        config = render(
            "squid.conf", [], platform=[{"host": h, "port": p} for h, p in pairs]
        )
        self.assertEqual(connect_pairs(config), pairs)
        self.assertEqual(order_findings(config), [])

    def test_negative_control_a_sixth_proxy_pair_is_reported(self):
        declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
        planted = declared["SEMAPHORE_EXPORT_PROXY"].replace(
            "[SEMAPHORE_SERVER_EGRESS]",
            "[SEMAPHORE_SERVER_EGRESS, SEMAPHORE_WORKSPACE_PLATFORM[1]]",
        )
        self.assertNotEqual(planted, declared["SEMAPHORE_EXPORT_PROXY"])
        pairs, allowed = export_proxy(planted)
        self.assertEqual(
            export_proxy_findings(pairs, allowed),
            ["web-app-gitea.example.org:443 is no export or server pair"],
        )

    def test_negative_control_a_proxy_list_without_the_server_is_reported(self):
        pairs, allowed = export_proxy("{{ SEMAPHORE_EXPORT_EGRESS }}")
        self.assertEqual(
            export_proxy_findings(pairs, allowed),
            ["web-app-semaphore.example.org:443 is missing"],
        )

    def test_every_render_closes_the_addresses_of_every_swarm_node(self):
        self.assertEqual(closed_findings(), [])
        self.assertEqual(
            egress_closed("manager", NODES), egress_closed("worker", NODES)
        )

    def test_outside_swarm_the_render_closes_its_own_host(self):
        closed = egress_closed("manager", {})
        self.assertIn("192.0.2.10", closed)
        self.assertIn("2001:db8::10", closed)
        self.assertNotIn("192.0.2.20", closed)
        self.assertEqual(len(closed), len(set(closed)))

    def test_negative_control_the_render_hosts_own_facts_leave_a_node_open(self):
        planted = (
            "{{ SEMAPHORE_WORKSPACE_CLOSED + ansible_facts.all_ipv4_addresses"
            " + ansible_facts.all_ipv6_addresses }}"
        )
        self.assertEqual(
            closed_findings(planted),
            [
                "a render on manager leaves 192.0.2.20 open",
                "a render on manager leaves 2001:db8::20 open",
                "a render on worker leaves 192.0.2.10 open",
                "a render on worker leaves 2001:db8::10 open",
            ],
        )

    def test_the_spec_probes_every_node_address_the_proxy_closes(self):
        self.assertEqual(host_address_findings(), [])
        self.assertEqual(probed_host_addresses("manager", enabled=False), [])

    def test_negative_control_an_ipv4_only_probe_list_misses_the_ipv6_addresses(self):
        line = host_addresses_line()
        planted = line.replace("all_ipv6_addresses", "all_ipv4_addresses")
        self.assertNotEqual(planted, line)
        self.assertEqual(
            host_address_findings(planted),
            [
                "a render on manager leaves 2001:db8::10 unprobed",
                "a render on manager leaves 2001:db8::20 unprobed",
                "a render on worker leaves 2001:db8::10 unprobed",
                "a render on worker leaves 2001:db8::20 unprobed",
            ],
        )

    def test_the_templates_get_the_targets_as_pairs(self):
        filters = load(
            ROLE / "filter_plugins" / "semaphore_workspace.py", "semaphore_filters_env"
        )
        self.assertEqual(
            filters.semaphore_targets_env(
                [
                    {"host": "203.0.113.10", "port": 22},
                    {"host": "2001:db8::1", "port": 2222},
                ]
            ),
            "203.0.113.10:22,[2001:db8::1]:2222",
        )
        self.assertEqual(filters.semaphore_targets_env([]), "")


if __name__ == "__main__":
    unittest.main()
