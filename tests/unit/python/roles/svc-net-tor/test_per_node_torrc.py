from __future__ import annotations

import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.tor_socks import resolve_socks_endpoint
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_egress_route import _egress, render

ROLE = PROJECT_ROOT / "roles/svc-net-tor"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
CORE = load_yaml_any(str(ROLE / "tasks/00_core.yml"), default_if_missing=[])
SWARM = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/18_swarm.yml"))
APPLICATIONS = {
    "svc-net-tor": {
        "services": load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES)),
    }
}
BRIDGES = {
    "manager-1": "172.17.0.1",
    "manager-2": "172.18.0.1",
    "worker-1": "172.19.0.1",
}
ADDRESSES = {"manager-1": "10.0.0.1", "manager-2": "10.0.0.2", "worker-1": "10.0.0.3"}
GROUPS = {
    "svc-swarm-node": list(BRIDGES),
    "svc-swarm-manager": ["manager-1", "manager-2"],
    "svc-net-tor": ["manager-1", "manager-2"],
}
HOSTVARS = {
    node: {
        "ansible_facts": {
            "docker0": {"ipv4": {"address": bridge}},
            "default_ipv4": {"address": ADDRESSES[node]},
        }
    }
    for node, bridge in BRIDGES.items()
}
HIDDEN_PORTS = [{"onion_port": 80, "target": "openresty:80"}]


def evaluate(expression: str, **variables):
    environment = NativeEnvironment(undefined=jinja2.ChainableUndefined)
    environment.filters["intersect"] = lambda left, right: [
        item for item in left if item in right
    ]
    return environment.from_string(expression).render(**variables)


def _lookup(name: str, *terms: str) -> str:
    return resolve_socks_endpoint(APPLICATIONS, *terms) if name == "tor_socks" else ""


def play_context(node: str, renderer: str, swarm: bool) -> dict:
    """
    Args:
        node: the node a file is rendered for, the loop's ``tor_node``.
        renderer: the inventory host the role runs on while it renders.
        swarm: whether the inventory forms a swarm.

    Returns:
        The play variables, with ``STACK_HOST`` and ``TOR_ROUTER_NODES``
        evaluated.
    """
    play = {
        "groups": GROUPS if swarm else {},
        "hostvars": HOSTVARS,
        "inventory_hostname": renderer,
        "IS_SWARM_MODE": swarm,
        "IS_COMPOSE_MODE": not swarm,
        "application_id": "svc-net-tor",
        "tor_node": node,
    }
    play["STACK_HOST"] = evaluate(SWARM["STACK_HOST"], **play)
    play["TOR_ROUTER_NODES"] = evaluate(VARS["TOR_ROUTER_NODES"], **play)
    return play


def node_routes(
    node: str, renderer: str = "manager-1", swarm: bool = True, route: str = "onion"
) -> bool:
    """
    Args:
        node: the node a file is rendered for, the loop's ``tor_node``.
        renderer: the inventory host the role runs on while it renders.
        swarm: whether the inventory forms a swarm.
        route: the egress route.

    Returns:
        ``TOR_NODE_ROUTES`` for that node.
    """
    play = play_context(node, renderer, swarm)
    return evaluate(VARS["TOR_NODE_ROUTES"], **play, TOR_EGRESS_ROUTE=route)


def torrc(
    node: str, renderer: str = "manager-1", swarm: bool = True, route: str = "onion"
) -> str:
    """
    Args:
        node: the node the torrc is rendered for, the loop's ``tor_node``.
        renderer: the inventory host the role runs on while it renders.
        swarm: whether the inventory forms a swarm.
        route: the egress route.

    Returns:
        The rendered torrc.
    """
    play = play_context(node, renderer, swarm)
    return render(
        "torrc.j2",
        route,
        _egress(),
        lookup=_lookup,
        IS_SWARM_MODE=swarm,
        TOR_NODE_BRIDGE=evaluate(VARS["TOR_NODE_BRIDGE"], **play),
        TOR_ROUTER_NODES=play["TOR_ROUTER_NODES"],
        TOR_NODE_ROUTES=node_routes(node, renderer, swarm, route),
        TOR_HS_BACKEND_HOST=evaluate(VARS["TOR_HS_BACKEND_HOST"], **play),
        TOR_ONION_EXTRA_PORTS=HIDDEN_PORTS,
        tor_node=node,
        STACK_HOST=play["STACK_HOST"],
    )


def task_rendering(source: str) -> dict:
    (task,) = [
        task
        for task in CORE
        if (task.get("ansible.builtin.template") or {}).get("src") == source
    ]
    return task


def task_registering(name: str) -> dict:
    (task,) = [task for task in CORE if task.get("register") == name]
    return task


def router_include() -> dict:
    (task,) = [
        inner
        for task in CORE
        for inner in task.get("block") or []
        if (inner.get("include_tasks") or {}).get("file") == "router.yml"
    ]
    return task


class TestPerNodeTorrc(unittest.TestCase):
    def test_the_torrc_is_rendered_once_per_node_on_that_node(self) -> None:
        task = task_rendering("torrc.j2")
        self.assertEqual(task["loop"], "{{ query('node_hosts') }}")
        self.assertEqual(task["loop_control"], {"loop_var": "tor_node"})
        self.assertEqual(task["delegate_to"], "{{ tor_node }}")

    def test_each_node_binds_its_own_bridge_from_hostvars(self) -> None:
        for node, bridge in BRIDGES.items():
            with self.subTest(node=node):
                rendered = torrc(node)
                self.assertIn(f"SocksPort {bridge}:9050\n", rendered)
                for other in set(BRIDGES.values()) - {bridge}:
                    self.assertNotIn(other, rendered)

    def test_only_the_stack_host_publishes_the_hidden_service(self) -> None:
        publishing = [node for node in BRIDGES if "HiddenServiceDir" in torrc(node)]
        self.assertEqual(publishing, ["manager-1"])

    def test_the_second_manager_renders_the_same_torrcs(self) -> None:
        for node in BRIDGES:
            with self.subTest(node=node):
                self.assertEqual(torrc(node, renderer="manager-2"), torrc(node))

    def test_the_hidden_service_forwards_to_the_stack_host(self) -> None:
        self.assertIn(
            "HiddenServicePort 80 10.0.0.1:80\n",
            torrc("manager-1", renderer="manager-2"),
        )

    def test_egress_listeners_render_only_where_the_router_runs(self) -> None:
        routed = [node for node in BRIDGES if "TransPort" in torrc(node)]
        self.assertEqual(routed, ["manager-1", "manager-2"])
        self.assertEqual(
            router_include()["when"], "inventory_hostname in TOR_ROUTER_NODES"
        )

    def test_compose_keeps_every_listener_and_the_service_on_its_node(self) -> None:
        rendered = torrc("manager-1", renderer="manager-1", swarm=False)
        self.assertIn("SocksPort 172.17.0.1:9050\n", rendered)
        self.assertIn("TransPort 172.17.0.1:9040\n", rendered)
        self.assertIn("HiddenServicePort 80 172.17.0.1:80\n", rendered)

    def test_the_keys_and_their_directory_go_to_the_stack_host_only(self) -> None:
        keys = task_registering("_tor_hs_keys")
        (directory,) = [
            task
            for task in CORE
            if (task.get("ansible.builtin.file") or {}).get("path")
            == "{{ TOR_HS_DIR }}"
        ]
        for task in (keys, directory):
            with self.subTest(task=task["name"]):
                self.assertEqual(task["delegate_to"], "{{ STACK_HOST }}")


if __name__ == "__main__":
    unittest.main()
