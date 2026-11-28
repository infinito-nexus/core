from __future__ import annotations

import ipaddress
import re
import shlex
import unittest

from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import regex_search
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter import api_listener
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.port_bands import load_port_bands
from utils.meta.scan import host_bound_port_set
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._render import COMPOSE, PROXMOX, ROLE, planted, service

VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
NFTABLES_PATH = ROLE / "templates" / "nftables.conf.j2"
PROVISION = load_yaml_any(
    str(ROLE / "tasks" / "03_provision.yml"), default_if_missing=[]
)
CORE = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"), default_if_missing=[])
API_TASKS = load_yaml_any(str(ROLE / "tasks" / "api.yml"), default_if_missing=[])
TABLE = "infinito_web_app_proxmox"
LISTENER_OWNER = ("web-app-proxmox", "proxmox", "public", "api")
FIREWALL = "🛡️ Admit the API listener of {{ application_id }} from its sources only"
FLUSH = "🚿 Flush compose for {{ application_id }}"
CERTIFICATE_TASK = (
    "🔐 Serve the API listener with a certificate for {{ PROXMOX_API_HOST }}"
)
RUNNER = "10.42.0.7"
RUNNER6 = "fd42::7"
NEIGHBOUR = "10.42.0.8"
NEIGHBOUR6 = "fd42::8"
SOURCES = [RUNNER, f"{RUNNER6}/128"]
CERTIFICATE = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
FINGERPRINT = "ab" * 32


def environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(api_listener.FilterModule().filters())
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    env.filters["regex_search"] = regex_search
    env.filters["bool"] = lambda value: str(value).lower() in ("true", "yes", "1")
    return env


def evaluate(expression: str, variables: dict) -> object:
    """Args:
        expression: a ``{{ }}`` value of the role that is one expression.
        variables: the variables it reads.

    Returns:
        The value the expression computes, a list or a mapping kept as such.
    """
    inner = expression.strip()
    if inner.startswith("{{") and inner.endswith("}}"):
        inner = inner[2:-2]
    return environment().compile_expression(inner)(**variables)


def rendered(template: str, variables: dict) -> str:
    """Args:
        template: a value of the role that mixes text and ``{{ }}`` parts.
        variables: the variables it reads.

    Returns:
        The rendered text.
    """
    return environment().from_string(template).render(**variables)


def config_lookup(port: int):
    """Args:
        port: the value ``services.proxmox.ports.public.api`` holds.

    Returns:
        A ``lookup`` that answers the config lookups of the listener vars.
    """

    def lookup(name: str, application: str, path: str) -> object:
        if (name, application, path) != (
            "config",
            "web-app-proxmox",
            "services.proxmox.ports.public.api",
        ):
            raise AssertionError(f"unexpected lookup {name} {application} {path}")
        return port

    return lookup


def api_vars(sources: list, bind: str | None = None, port: int | None = None) -> dict:
    """Args:
        sources: ``services.proxmox.api.allowed_sources``.
        bind: ``services.proxmox.api.bind``, the role's default when None.
        port: ``services.proxmox.ports.public.api``, the role's when None.

    Returns:
        ``PROXMOX_API_SOURCES`` and ``PROXMOX_API_PORT`` as the role's vars
        compute them.
    """
    api = {**PROXMOX["api"], "allowed_sources": sources}
    if bind is not None:
        api["bind"] = bind
    variables = {
        "PROXMOX_API": api,
        "application_id": "web-app-proxmox",
        "lookup": config_lookup(port or PROXMOX["ports"]["public"]["api"]),
    }
    return {
        name: evaluate(VARS[name], variables)
        for name in ("PROXMOX_API_SOURCES", "PROXMOX_API_PORT")
    }


def ruleset(template: str, sources: list, port: int | None = None) -> str:
    return rendered(template, {"FIREWALL_TABLE": TABLE, **api_vars(sources, port=port)})


def _sets(text: str) -> dict[str, list]:
    sets = {}
    for name, body in re.findall(r"set (\w+) \{(.*?)\n  \}", text, re.DOTALL):
        elements = re.search(r"elements = \{(.*?)\}", body, re.DOTALL)
        sets[name] = [
            ipaddress.ip_network(item.strip(), strict=False)
            for item in (elements.group(1).split(",") if elements else [])
        ]
    return sets


def _rules(text: str, chain: str) -> list[list[str]]:
    body = re.search(rf"chain {chain} \{{(.*?)\n  \}}", text, re.DOTALL)
    if not body:
        return []
    return [
        shlex.split(line.strip())
        for line in body.group(1).splitlines()
        if line.strip() and not line.strip().startswith("type ")
    ]


def _matches(rule: list[str], packet: dict, sets: dict) -> bool:
    tokens = list(rule)
    if tokens.pop() != "drop":
        raise AssertionError(f"unexpected verdict in {rule}")
    while tokens:
        head = tokens.pop(0)
        if head == "meta" and tokens[0] == "nfproto":
            if packet["family"] != tokens[1]:
                return False
            del tokens[:2]
        elif head == "fib" and tokens[:3] == ["daddr", "type", "local"]:
            if not packet["local"]:
                return False
            del tokens[:3]
        elif head == "tcp" and tokens[0] == "dport":
            if packet["dport"] != int(tokens[1]):
                return False
            del tokens[:2]
        elif head in ("ip", "ip6") and tokens[:2] == ["saddr", "!="]:
            if packet["family"] != ("ipv4" if head == "ip" else "ipv6"):
                return False
            source = ipaddress.ip_address(packet["saddr"])
            if any(source in network for network in sets[tokens[2].lstrip("@")]):
                return False
            del tokens[:3]
        else:
            raise AssertionError(f"the simulator does not know {head} in {rule}")
    return True


def dropped(text: str, **packet) -> bool:
    """Args:
        text: a rendered ruleset.
        **packet: ``family``, ``saddr``, ``dport`` and ``local``, whether the
            packet is addressed to the host itself.

    Returns:
        Whether the prerouting chain drops the packet before Docker's DNAT.
    """
    sets = _sets(text)
    return any(_matches(rule, packet, sets) for rule in _rules(text, "prerouting"))


def findings(text: str) -> list[str]:
    """Args:
        text: a rendered ruleset.

    Returns:
        Every probe whose verdict breaks the source list.
    """
    port = api_port()
    probes = (
        ("ipv4", RUNNER, port, True, False),
        ("ipv6", RUNNER6, port, True, False),
        ("ipv4", NEIGHBOUR, port, True, True),
        ("ipv6", NEIGHBOUR6, port, True, True),
        ("ipv4", NEIGHBOUR, port, False, False),
        ("ipv4", NEIGHBOUR, 22, True, False),
    )
    return [
        f"{family} {source}:{port} local={local}"
        for family, source, port, local, drop in probes
        if dropped(text, family=family, saddr=source, dport=port, local=local) != drop
    ]


def api_port() -> int:
    return PROXMOX["ports"]["public"]["api"]


def collision_findings(host_bound: dict) -> list[str]:
    """Args:
        host_bound: ``utils.meta.scan.host_bound_port_set()`` or a variant.

    Returns:
        Why the listener port is not one registered port of its own: it is
        missing from the registry, or another registered port shares it.
    """
    port = api_port()
    owners = host_bound.get(port, [])
    if LISTENER_OWNER not in owners:
        return [f"port {port} of the API listener is not in the port registry"]
    return [
        f"port {port} is also {owner}" for owner in owners if owner != LISTENER_OWNER
    ]


def band_findings(port: int) -> list[str]:
    """Args:
        port: a host port of the API listener.

    Returns:
        Why it lies outside ``PORT_BANDS.public.api`` or inside a local band.
    """
    bands = load_port_bands()
    api = bands["public"].get("api")
    found = []
    if api is None or not api["start"] <= port <= api["end"]:
        found.append(f"{port} lies outside PORT_BANDS.public.api")
    found += [
        f"{port} lies inside PORT_BANDS.local.{category}"
        for category, band in bands["local"].items()
        if band["start"] <= port <= band["end"]
    ]
    return found


def nftables() -> str:
    return read_text(str(NFTABLES_PATH))


def _task(tasks: list, name: str) -> dict:
    return next(task for task in tasks if task.get("name") == name)


def order_findings(tasks: list) -> list[str]:
    """Args:
        tasks: the task list of ``tasks/00_core.yml``.

    Returns:
        Why the firewall would not stand before the compose flush publishes
        the listener; empty when it does.
    """
    names = [task.get("name") for task in tasks]
    if FIREWALL not in names:
        return ["no task loads the firewall fragment"]
    firewall = tasks[names.index(FIREWALL)]
    if firewall["vars"]["FIREWALL_FRAGMENT_ROLE"] != "web-app-proxmox":
        return ["the firewall task loads another role's fragment"]
    if names.index(FIREWALL) > names.index(FLUSH):
        return ["the compose flush publishes the listener before the firewall loads"]
    return []


class TestApiListener(unittest.TestCase):
    def test_the_listener_is_off_by_default_and_published_when_on(self):
        self.assertIs(PROXMOX["api"]["enabled"], False)
        self.assertEqual(PROXMOX["api"]["allowed_sources"], [])
        api = {**PROXMOX["api"], "enabled": True}
        for flavor in ("vm", "container"):
            self.assertEqual(service(flavor)["ports"], ["127.0.0.1:7992:8006"])
            self.assertEqual(
                service(flavor, PROXMOX_API=api)["ports"],
                ["127.0.0.1:7992:8006", f"{api['bind']}:{api_port()}:8006"],
            )
        self.assertIn("{'service': 'proxmox', 'protocol': 'api'", COMPOSE)
        self.assertNotIn("compose-ports-must-use-container-ports", COMPOSE)

    def test_negative_control_an_unswitched_listener_is_caught(self):
        mutant = planted(
            COMPOSE, "{% if PROXMOX_API.enabled | bool %}", "{% if true %}"
        )
        self.assertEqual(len(service("vm", mutant)["ports"]), 2)

    def test_the_listener_port_is_one_registered_port_of_its_own(self):
        self.assertEqual(collision_findings(host_bound_port_set()), [])
        self.assertEqual(band_findings(api_port()), [])
        self.assertNotIn("listen", PROXMOX["api"])

    def test_negative_control_a_shared_port_is_caught(self):
        registry = host_bound_port_set()
        taken = {
            **registry,
            api_port(): [
                *registry[api_port()],
                ("web-app-yourls", "yourls", "local", "http"),
            ],
        }
        self.assertNotEqual(collision_findings(taken), [])
        self.assertNotEqual(collision_findings({}), [])

    def test_negative_control_the_former_listener_port_is_caught(self):  # nocheck: test.text-presence -- runs band_findings on a planted port  # fmt: skip
        self.assertIn("8006 lies inside PORT_BANDS.local.http", band_findings(8006))

    def test_the_listener_publishes_the_port_pveproxy_serves(self):
        internal = PROXMOX["ports"]["internal"]
        self.assertEqual(internal["api"], internal["http"])

    def test_the_firewall_admits_only_the_allowed_sources(self):
        port = api_port()
        self.assertEqual(findings(ruleset(nftables(), SOURCES)), [])
        nobody = ruleset(nftables(), [])
        self.assertTrue(
            dropped(nobody, family="ipv4", saddr=RUNNER, dport=port, local=True)
        )
        self.assertTrue(
            dropped(nobody, family="ipv6", saddr=RUNNER6, dport=port, local=True)
        )
        moved = ruleset(nftables(), SOURCES, port=8699)
        self.assertTrue(
            dropped(moved, family="ipv6", saddr=NEIGHBOUR6, dport=8699, local=True)
        )

    def test_a_malformed_source_or_bind_fails_at_render(self):
        with self.assertRaisesRegex(
            AnsibleFilterError, "services.proxmox.api.allowed_sources"
        ):
            api_vars(["runner.example"])
        with self.assertRaisesRegex(AnsibleFilterError, "services.proxmox.api.bind"):
            api_vars(SOURCES, bind="::")
        self.assertEqual(api_vars(SOURCES, bind="[::]")["PROXMOX_API_PORT"], api_port())

    def test_negative_control_a_ruleset_without_the_ipv6_rule_is_caught(self):
        line = (
            "    meta nfproto ipv6 fib daddr type local tcp dport"
            " {{ PROXMOX_API_PORT }} ip6 saddr != @api_ipv6 drop\n"
        )
        self.assertEqual(
            findings(ruleset(planted(nftables(), line, ""), SOURCES)),
            [f"ipv6 {NEIGHBOUR6}:{api_port()} local=True"],
        )

    def test_negative_control_a_ruleset_that_drops_the_container_network_fails(self):
        mutant = nftables().replace("fib daddr type local ", "")
        self.assertIn(
            f"ipv4 {NEIGHBOUR}:{api_port()} local=False",
            findings(ruleset(mutant, SOURCES)),
        )

    def test_negative_control_an_input_hook_is_caught(self):
        mutant = planted(nftables(), "chain prerouting {", "chain input {")
        self.assertNotEqual(findings(ruleset(mutant, SOURCES)), [])

    def test_the_firewall_loads_before_the_compose_flush_publishes_the_port(self):
        self.assertEqual(order_findings(CORE), [])
        self.assertIn("PROXMOX_API.enabled | bool", _task(CORE, FIREWALL)["when"])
        self.assertNotIn(FIREWALL, [task.get("name") for task in API_TASKS])

    def test_negative_control_a_firewall_after_the_flush_is_caught(self):
        names = [task.get("name") for task in CORE]
        firewall = CORE[names.index(FIREWALL)]
        moved = [task for task in CORE if task is not firewall] + [firewall]
        self.assertNotEqual(order_findings(moved), [])


class TestApiEndpoint(unittest.TestCase):
    def endpoint(self, host: str, loopback: list) -> tuple[str, str]:
        variables = {"inventory_hostname": host, "NETWORK_LOOPBACK_HOSTS": loopback}
        variables["PROXMOX_API_HOST"] = evaluate(VARS["PROXMOX_API_HOST"], variables)
        variables["PROXMOX_API_PORT"] = api_vars([])["PROXMOX_API_PORT"]
        return (
            rendered(VARS["PROXMOX_API_ENDPOINT"], variables),
            evaluate(VARS["PROXMOX_API_SAN"], variables),
        )

    def test_the_certificate_names_the_host_the_consumers_dial(self):
        port = api_port()
        self.assertEqual(
            self.endpoint("localhost", ["localhost"]),
            (f"https://host.docker.internal:{port}", "DNS:host.docker.internal"),
        )
        self.assertEqual(
            self.endpoint("pve.example.org", ["localhost"]),
            (f"https://pve.example.org:{port}", "DNS:pve.example.org"),
        )
        self.assertEqual(
            self.endpoint("192.0.2.7", ["localhost"]),
            (f"https://192.0.2.7:{port}", "IP:192.0.2.7"),
        )

    def test_the_certificate_task_runs_inside_proxmox_ve(self):
        task = _task(API_TASKS, CERTIFICATE_TASK)
        self.assertIn(
            "PROXMOX_GUEST_EXEC + ['sh', '-s']", task["ansible.builtin.shell"]["cmd"]
        )
        self.assertEqual(
            task["environment"]["PROXMOX_API_SAN"], "{{ PROXMOX_API_SAN }}"
        )
        self.assertIn("fingerprint=", task["failed_when"])
        script = read_text(str(ROLE / "files" / "shell" / "api-certificate.sh"))
        self.assertIn('-addext "subjectAltName=$PROXMOX_API_SAN"', script)
        self.assertIn("pvenode cert set", script)
        self.assertNotIn("BEGIN PRIVATE KEY", script)


class TestProvisionRecord(unittest.TestCase):
    def record(self) -> dict:
        store = next(
            task
            for task in PROVISION
            if "kv.yml" in str(task.get("ansible.builtin.include_tasks"))
        )
        return store["vars"]["openbao_kv_data"]

    def test_the_record_pins_the_listener_certificate(self):
        data = self.record()
        self.assertEqual(data["endpoint"], "{{ PROXMOX_API_ENDPOINT }}")
        stdout = f"fingerprint={FINGERPRINT}\n{CERTIFICATE}\n"
        registered = {"proxmox_api_certificate": {"stdout": stdout}}
        self.assertEqual(rendered(data["certificate"], registered), CERTIFICATE)
        self.assertEqual(rendered(data["fingerprint"], registered), FINGERPRINT)
        include = _task(CORE, "📇 Record the provision target of {{ application_id }}")
        self.assertIn("PROXMOX_API.enabled | bool", include["when"])

    def test_negative_control_the_public_endpoint_is_caught(self):
        self.assertNotIn("url.base", str(self.record()))


if __name__ == "__main__":
    unittest.main()
