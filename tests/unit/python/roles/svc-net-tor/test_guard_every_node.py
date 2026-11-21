from __future__ import annotations

import re
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.node_hosts import node_hosts
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from . import test_per_node_torrc as per_node
from .test_egress_route import _egress, _evaluate, chain, render
from .test_torrc_listeners import listeners

ROLE = PROJECT_ROOT / "roles/svc-net-tor"
VARS_PATH = ROLE / ROLE_FILE_VARS_MAIN
CORE_PATH = ROLE / "tasks/00_core.yml"
GUARD_PATH = ROLE / "tasks/guard.yml"
ROUTER_PATH = ROLE / "tasks/router.yml"
VERIFY_PATH = ROLE / "tasks/guard/verify.yml"
FRAGMENT_TASKS = "roles/svc-net-firewall/tasks/02_fragment.yml"
FIREWALL_VARS = load_yaml_any(
    str(PROJECT_ROOT / "roles/svc-net-firewall" / ROLE_FILE_VARS_MAIN)
)
LOCAL_PORTS = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["tor"]["ports"][
    "local"
]
PORTS = {
    "TOR_TRANS_PORT": LOCAL_PORTS["trans"],
    "TOR_DNS_PORT": LOCAL_PORTS["dns"],
    "TOR_SOCKS_PORT": LOCAL_PORTS["socks"],
    "TOR_DNSMASQ_PORT": 53,
}
GUARD_INCLUDE = (
    "🛡️ Bound the Tor listeners of every node the egress router does not guard"
)
TORRC_TASK = "📝 Render the torrc of every node"
COMPOSE_TASK = "🧩 For '{{ application_id }}': Load sys-svc-compose"
LOCAL_BLOCK = "🛡️ Tor guard | Bound the Tor listeners of this node"
REMOTE_BLOCK = (
    "🛡️ Tor guard | Bound the Tor listeners of every node the role does not run on"
)
REMOTE_LOAD = "🛡️ Tor guard | Load the guard of every node the role does not run on"
REMOTE_CHECK = "🛡️ Tor guard | Check the guard of every node the role does not run on"
ROUTER_BLOCK = (
    "🧅 Bring up the transparent egress router for route '{{ TOR_EGRESS_ROUTE }}'"
)
ROUTER_INCLUDE = "🧅 Wire the host-level transparent .onion egress router"
ROUTER_FIREWALL = (
    "🔀 Egress router | Route .onion traffic and bound the ports that carry no policy"
)
ROUTER_CHECK = "🛡️ Egress guard | Check the chain that bounds the ports"
_PORT_VARIABLE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")
_GUARD_RULE = re.compile(
    r"^ip saddr != @(?P<admitted>\w+) (?P<protocol>tcp|udp) dport (?P<port>\d+) drop$"
)


def _vars() -> dict:
    return load_yaml_any(str(VARS_PATH))


def _tasks(path) -> list[dict]:
    return list(_walk(load_yaml_any(str(path), default_if_missing=[])))


def _walk(tasks):
    for task in tasks or []:
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk(task.get(section))


def _named(path, name: str) -> dict:
    found = [task for task in _tasks(path) if task.get("name") == name]
    if not found:
        raise AssertionError(f"{path.name} has no task {name!r}")
    return found[0]


def _guarded_ports() -> list[dict]:
    return [
        {**entry, "port": PORTS[_PORT_VARIABLE.search(str(entry["port"])).group(1)]}
        for entry in _vars()["TOR_EGRESS_GUARDED_PORTS"]
    ]


def _fragment(routes: bool, route: str = "onion") -> str:
    return render(
        "nftables.conf.j2",
        route,
        _egress(),
        TOR_NODE_ROUTES=routes,
        TOR_EGRESS_GUARDED_PORTS=_guarded_ports(),
        **PORTS,
    )


def _guarded(ruleset: str) -> set[tuple[str, str, int]]:
    found = set()
    for rule in chain(ruleset, "guard"):
        match = _GUARD_RULE.match(rule)
        if match is not None:
            found.add((match["admitted"], match["protocol"], int(match["port"])))
    return found


def _bound(torrc: str) -> set[int]:
    return {
        int(value.rsplit(":", 1)[1])
        for keyword, values in listeners(torrc).items()
        if keyword != "ControlPort"
        for value in values
    }


def _remote_nodes(swarm: bool) -> list[str]:
    groups = per_node.GROUPS if swarm else {}
    play = {
        "groups": groups,
        "inventory_hostname": "manager-1",
        "IS_COMPOSE_MODE": not swarm,
        "application_id": "svc-net-tor",
    }
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters["difference"] = lambda left, right: [
        item for item in left if item not in right
    ]
    environment.globals["query"] = lambda name: node_hosts(play)
    return environment.from_string(_vars()["TOR_REMOTE_NODES"]).render(**play)


def _string(template: str, **variables) -> str:
    environment = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False)
    )
    environment.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    return environment.from_string(template).render(**variables)


class TestGuardEveryNode(unittest.TestCase):
    def test_every_guard_entry_declares_whether_only_the_router_binds_it(self) -> None:
        entries = _guarded_ports()
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertIsInstance(entry.get("router"), bool)
        self.assertEqual(
            [
                (entry["protocol"], entry["port"])
                for entry in entries
                if not entry["router"]
            ],
            [("tcp", PORTS["TOR_SOCKS_PORT"])],
        )

    def test_a_node_without_the_router_guards_its_socks_port_only(self) -> None:
        for route in ("none", "onion", "all"):
            with self.subTest(route=route):
                ruleset = _fragment(False, route)
                socks = PORTS["TOR_SOCKS_PORT"]
                self.assertEqual(
                    chain(ruleset, "guard"),
                    [
                        f"ip saddr != @internal tcp dport {socks} drop",
                        f"fib saddr . iif oif missing tcp dport {{ {socks} }} drop",
                    ],
                )
                self.assertEqual(chain(ruleset, "input"), ["jump guard"])
                self.assertEqual(chain(ruleset, "forward"), ["jump guard"])
                for router_part in (
                    "chain output",
                    "chain prerouting",
                    "chain egress_",
                ):
                    self.assertNotIn(router_part, ruleset)

    def test_a_router_node_keeps_every_guard_and_its_router(self) -> None:
        ruleset = _fragment(True)
        self.assertEqual(
            _guarded(ruleset),
            {
                (entry["admitted"], entry["protocol"], entry["port"])
                for entry in _guarded_ports()
            },
        )
        self.assertIn(
            "fib saddr . iif oif missing udp dport { "
            f"{PORTS['TOR_DNS_PORT']}, {PORTS['TOR_DNSMASQ_PORT']} }} drop",
            chain(ruleset, "guard"),
        )
        self.assertIn("chain output {", ruleset)
        self.assertIn("chain prerouting {", ruleset)

    def test_every_node_guards_exactly_the_tor_listeners_its_torrc_binds(self) -> None:
        for route in ("none", "onion"):
            for node in per_node.BRIDGES:
                with self.subTest(route=route, node=node):
                    routes = per_node.node_routes(node, route=route)
                    guarded = {
                        port
                        for _, _, port in _guarded(_fragment(routes, route))
                        if port != PORTS["TOR_DNSMASQ_PORT"]
                    }
                    self.assertEqual(guarded, _bound(per_node.torrc(node, route=route)))

    def test_the_remote_nodes_are_the_swarm_nodes_the_role_does_not_run_on(
        self,
    ) -> None:
        self.assertEqual(_remote_nodes(swarm=True), ["worker-1"])
        self.assertEqual(_remote_nodes(swarm=False), [])

    def test_every_host_of_the_role_gets_either_the_router_or_the_guard(self) -> None:
        local = _named(GUARD_PATH, LOCAL_BLOCK)
        self.assertEqual(local["vars"], {"tor_node": "{{ inventory_hostname }}"})
        router_block = _named(CORE_PATH, ROUTER_BLOCK)
        router_include = _named(CORE_PATH, ROUTER_INCLUDE)
        for swarm, hosts in ((True, ("manager-1", "manager-2")), (False, ("node",))):
            for route in ("none", "onion", "all"):
                for host in hosts:
                    with self.subTest(swarm=swarm, route=route, host=host):
                        play = per_node.play_context(host, host, swarm)
                        context = {
                            "TOR_EGRESS_ROUTE": route,
                            "inventory_hostname": host,
                            "TOR_ROUTER_NODES": play["TOR_ROUTER_NODES"],
                        }
                        router = all(
                            _evaluate(condition, context, conditional=True)
                            for condition in (
                                router_block["when"],
                                router_include["when"],
                            )
                        )
                        guard = _evaluate(
                            local["when"],
                            {
                                "TOR_NODE_ROUTES": per_node.node_routes(
                                    host, renderer=host, swarm=swarm, route=route
                                )
                            },
                            conditional=True,
                        )
                        self.assertNotEqual(router, guard)

    def test_the_guard_reaches_every_node_before_tor_starts(self) -> None:
        names = [task.get("name") for task in _tasks(CORE_PATH)]
        include = _named(CORE_PATH, GUARD_INCLUDE)
        self.assertEqual(include["ansible.builtin.include_tasks"], "guard.yml")
        self.assertLess(names.index(TORRC_TASK), names.index(GUARD_INCLUDE))
        self.assertLess(names.index(GUARD_INCLUDE), names.index(COMPOSE_TASK))

        local = _named(GUARD_PATH, LOCAL_BLOCK)
        self.assertEqual(local["when"], "not TOR_NODE_ROUTES")
        self.assertEqual(
            local["block"][0]["ansible.builtin.include_role"]["name"],
            "svc-net-firewall",
        )
        self.assertEqual(
            local["block"][1]["ansible.builtin.include_tasks"], "guard/verify.yml"
        )

        remote = _named(GUARD_PATH, REMOTE_BLOCK)
        self.assertEqual(remote["when"], "TOR_REMOTE_NODES | length > 0")
        self.assertTrue((PROJECT_ROOT / FRAGMENT_TASKS).is_file())
        for name, file in (
            (REMOTE_LOAD, f"{{{{ lookup('path_absolute', '{FRAGMENT_TASKS}') }}}}"),
            (REMOTE_CHECK, "guard/verify.yml"),
        ):
            with self.subTest(task=name):
                task = _named(GUARD_PATH, name)
                self.assertEqual(task["ansible.builtin.include_tasks"]["file"], file)
                self.assertEqual(
                    task["ansible.builtin.include_tasks"]["apply"],
                    {"delegate_to": "{{ tor_node }}"},
                )
                self.assertEqual(task["loop"], "{{ TOR_REMOTE_NODES }}")
                self.assertEqual(task["loop_control"], {"loop_var": "tor_node"})
                self.assertIs(task["run_once"], True)

    def test_a_remote_guard_replaces_the_table_the_router_would_load(self) -> None:
        load = _named(GUARD_PATH, REMOTE_LOAD)
        self.assertEqual(load["vars"]["FIREWALL_FRAGMENT_ROLE"], "{{ application_id }}")
        self.assertEqual(
            load["vars"]["FIREWALL_TABLE"], "{{ tor_guard_firewall.FIREWALL_TABLE }}"
        )
        self.assertEqual(
            _string(
                FIREWALL_VARS["FIREWALL_TABLE"], FIREWALL_FRAGMENT_ROLE="svc-net-tor"
            ),
            _string(_vars()["TOR_EGRESS_NFT_TABLE"], application_id="svc-net-tor"),
        )

    def test_the_router_renders_its_fragment_for_its_own_node(self) -> None:
        for name in (ROUTER_FIREWALL, ROUTER_CHECK):
            with self.subTest(task=name):
                self.assertEqual(
                    _named(ROUTER_PATH, name)["vars"],
                    {"tor_node": "{{ inventory_hostname }}"},
                )
        self.assertEqual(
            _named(ROUTER_PATH, ROUTER_CHECK)["ansible.builtin.include_tasks"],
            "guard/verify.yml",
        )

    def test_a_guard_that_drops_nothing_is_refused(self) -> None:
        (read, refuse) = load_yaml_any(str(VERIFY_PATH))
        self.assertEqual(
            read["ansible.builtin.command"]["argv"],
            ["nft", "list", "chain", "inet", "{{ firewall_loaded_table }}", "guard"],
        )
        that = refuse["ansible.builtin.assert"]["that"][0]
        for listing, passes in (
            ("chain guard {\n\tip saddr != @internal tcp dport 9050 drop\n}", True),
            ("chain guard {\n}", False),
        ):
            with self.subTest(passes=passes):
                self.assertEqual(
                    _evaluate(
                        that,
                        {"tor_guard_chain": {"stdout": listing}},
                        conditional=True,
                    ),
                    passes,
                )


if __name__ == "__main__":
    unittest.main()
