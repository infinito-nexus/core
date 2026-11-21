"""Every role's nftables fragment parses, and replaces its table instead of merging.

``nft -f`` on ``table inet x { ... }`` MERGES into an existing table: a rule
dropped from the declaration stays in the kernel, and the ruleset can only ever
grow. The three-line idiom below is what makes a fragment a replacement:

    table inet x          <- creates it when absent, so the delete cannot fail
    delete table inet x   <- removes whatever the last deploy left
    table inet x { ... }  <- the declaration, applied in the same transaction

``nft -f`` is atomic, so the table is never observed empty. Without the first
line the delete fails on a fresh host; without the second the fragment merges.

The checks run the real ``nft`` over the rendered text, so a fragment that is
valid Jinja but invalid nftables fails here rather than on the host. They render
every deploy mode, because a fragment may branch on one, and feed plausible
rather than real values: nft needs shapes, not this host's addresses.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.swarm_ingress_guard import (
    swarm_ingress_published,
    swarm_node_addresses,
)
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.tor_egress import plan as tor_egress_plan
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

FRAGMENT = "templates/nftables.conf.j2"
TABLE = "infinito_probe"

PROBE_PORTS = {
    "TOR_TRANS_PORT": "9040",
    "TOR_DNS_PORT": "9053",
    "TOR_SOCKS_PORT": "9050",
    "TOR_DNSMASQ_PORT": "53",
}

_PORT_VARIABLE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")


def _guarded_ports() -> list[dict]:
    """The role's own guard list, with its port variables filled from stand-ins.

    The shape has to come from the declaration: an entry that gains a key, a
    protocol or a whole port must reach the rendered table here, or this check
    keeps passing on a fixture the role stopped shipping.
    """
    declared = load_yaml_any(
        str(PROJECT_ROOT / "roles" / "svc-net-tor" / ROLE_FILE_VARS_MAIN)
    )["TOR_EGRESS_GUARDED_PORTS"]
    return [
        {**entry, "port": PROBE_PORTS[_PORT_VARIABLE.search(entry["port"]).group(1)]}
        for entry in declared
    ]


def _chutney_guarded_ports() -> list[dict]:
    role = PROJECT_ROOT / "roles" / "svc-net-tor"
    declared = load_yaml_any(str(role / ROLE_FILE_VARS_MAIN))
    chutney = load_yaml_any(str(role / ROLE_FILE_META_SERVICES))["tor"]["chutney"]
    environment = NativeEnvironment()
    window = environment.from_string(declared["TOR_CHUTNEY_PORT_RANGE"]).render(
        TOR_CHUTNEY_BASES=chutney["port_bases"],
        TOR_CHUTNEY_PORT_SPAN=chutney["port_span"],
    )
    return environment.from_string(declared["TOR_CHUTNEY_GUARDED_PORTS"]).render(
        TOR_FLAVOR="chutney", TOR_CHUTNEY_PORT_RANGE=window
    )


def _incus_variables() -> dict:
    """
    Returns:
        The incus fragment's inputs: the role's own network, workspace and
        listen declaration, and one stand-in API source per family shaped by
        the role's own ``incus_sources`` filter.
    """
    role = PROJECT_ROOT / "roles" / "svc-virt-incus"
    incus = load_yaml_any(str(role / ROLE_FILE_META_SERVICES))["incus"]
    spec = importlib.util.spec_from_file_location(
        "incus_workspace_filters", role / "filter_plugins" / "incus_workspace.py"
    )
    filters = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(filters)
    return {
        "INCUS_API_SOURCES": filters.incus_sources(["192.0.2.7", "2001:db8::7"]),
        "INCUS_API_PORT": filters.incus_listen_port(incus["api"]["listen"]),
        "INCUS_WORKSPACES": incus["workspaces"],
        "INCUS_NETWORK": incus["network"],
    }


COMMON = {
    "FIREWALL_TABLE": TABLE,
    "TOR_EGRESS_CLIENT_CIDRS": ["127.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
    "TOR_EGRESS_GUARDED_PORTS": _guarded_ports(),
    "TOR_CHUTNEY_GUARDED_PORTS": _chutney_guarded_ports(),
    "TOR_EGRESS_VIRTUAL_NET_IPV4": "10.192.0.0/10",
    "TOR_EGRESS_SOCKET_UID": 0,
    "TOR_EGRESS_SOCKET_GID": 9050,
    "TOR_EGRESS_CT_MARK": "0x544f5200",
    "TOR_EGRESS_NFTSET_TIMEOUT": "1h",
    "TOR_DNSMASQ_UID": 977,
    "TOR_DNS_UPSTREAMS": ["172.30.0.53"],
    "TOR_EGRESS_RESOLVER_PORTS": [53, 853],
    "TOR_EGRESS_RESOLVER_CIDRS": ["127.0.0.0/8", "172.17.0.1", "192.168.74.0/24"],
    "TOR_EGRESS_NONROUTABLE_IPV4": ["169.254.0.0/16", "224.0.0.0/4", "255.255.255.255"],
    "TOR_EGRESS_LOCAL_IPV6": ["::1", "fe80::/10", "fc00::/7", "ff00::/8"],
    **PROBE_PORTS,
    "TOR_CONTAINER_DNS_HOST": "172.17.0.1",
    "NETWORK_INTERNAL_CIDRS": [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    ],
    "SWARM_INGRESS_GUARDED_PORTS": swarm_ingress_published(
        [
            (
                '[{"Protocol":"tcp","TargetPort":5432,"PublishedPort":5432,"PublishMode":"ingress"},'
                '{"Protocol":"udp","TargetPort":3478,"PublishedPort":3478,"PublishMode":"ingress"}]'
            )
        ]
    ),
    "SWARM_INGRESS_PEER_ADDRESSES": swarm_node_addresses(["10.0.0.2"]),
    "SWARM_ONION_GUARDED_PORTS": [389, 3306],
    **_incus_variables(),
}

MODES = ("compose", "swarm")

EGRESS_LISTS = {
    "tor": {"include": ["198.51.100.0/24", "2001:db8::/32"], "except": []},
    "direct": {"include": ["docker.io", "192.0.2.0/28"], "except": ["192.0.2.10"]},
}
ROUTES = ("none", "onion", "all")


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


@lru_cache(maxsize=1)
def _nft_can_check() -> bool:
    """Whether `nft -c` works here.

    It is not a parser: it opens netlink and builds a cache against the live
    kernel first, so on a runner without CAP_NET_ADMIN it fails on a valid
    ruleset. Probing the binary's presence would make this suite red there.
    """
    if shutil.which("nft") is None:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".conf") as handle:
        handle.write("table inet infinito_capability_probe\n")
        handle.flush()
        return _run(["nft", "-c", "-f", handle.name]).returncode == 0


@contextmanager
def _network_namespace(name: str):
    """An empty namespace, so a loaded ruleset cannot reach the live one."""
    created = _run(["ip", "netns", "add", name])
    if created.returncode != 0:
        raise unittest.SkipTest(f"cannot create a network namespace: {created.stderr}")
    try:
        yield ["ip", "netns", "exec", name]
    finally:
        _run(["ip", "netns", "del", name])


def _fragments() -> list[str]:
    suffix = "/" + FRAGMENT
    return sorted(
        path
        for path in iter_project_files(extensions=(".j2",), exclude_tests=True)
        if path.endswith(suffix)
    )


def _render(path: str, mode: str = "swarm", route: str = "onion") -> str:
    environment = jinja2.Environment(
        keep_trailing_newline=True,
        trim_blocks=True,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    return environment.from_string(read_text(path)).render(
        DEPLOYMENT_MODE=mode,
        TOR_EGRESS_ROUTE=route,
        TOR_NODE_ROUTES=route != "none",
        TOR_EGRESS_PLAN=tor_egress_plan(EGRESS_LISTS, route),
        **COMMON,
    )


class TestFirewallFragments(unittest.TestCase):
    def test_at_least_one_fragment_exists(self) -> None:
        """Otherwise every assertion below passes over an empty list."""
        self.assertTrue(_fragments(), "no role declares templates/nftables.conf.j2")

    def test_each_fragment_replaces_its_table(self) -> None:
        for path in _fragments():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            with self.subTest(fragment=rel):
                lines = [
                    line.strip() for line in _render(path).splitlines() if line.strip()
                ]
                declarations = [
                    line for line in lines if re.match(r"^(delete )?table inet ", line)
                ]
                self.assertEqual(
                    declarations[:3],
                    [
                        f"table inet {TABLE}",
                        f"delete table inet {TABLE}",
                        f"table inet {TABLE} {{",
                    ],
                    f"{rel} must open with the create, delete and declare idiom, "
                    "or nft merges the new rules into the old table",
                )

    def test_each_fragment_parses(self) -> None:
        if not _nft_can_check():
            self.skipTest("nft -c needs CAP_NET_ADMIN, which this runner lacks")
        nft = shutil.which("nft")
        for path in _fragments():
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            for mode, route in ((mode, route) for mode in MODES for route in ROUTES):
                with self.subTest(fragment=rel, mode=mode, route=route):
                    with tempfile.NamedTemporaryFile("w", suffix=".conf") as handle:
                        handle.write(_render(path, mode, route))
                        handle.flush()
                        result = subprocess.run(
                            [nft, "-c", "-f", handle.name],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                    self.assertEqual(
                        result.returncode,
                        0,
                        f"{rel} is not valid nftables in {mode}:\n{result.stderr}",
                    )

    def test_each_fragment_loads_and_reloads(self) -> None:
        """A dry run cannot show what happens on the second deploy.

        Loading the same fragment twice is what proves the idiom: the second
        pass meets the table the first one left and must replace it, which is
        exactly the case ``nft -c`` never sees.
        """
        if not _nft_can_check() or shutil.which("ip") is None:
            self.skipTest("loading a ruleset needs nft with CAP_NET_ADMIN and ip")
        for index, path in enumerate(_fragments()):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            for mode, route in ((mode, route) for mode in MODES for route in ROUTES):
                with self.subTest(fragment=rel, mode=mode, route=route):
                    with (
                        tempfile.NamedTemporaryFile("w", suffix=".conf") as handle,
                        _network_namespace(f"nftprobe{os.getpid()}x{index}") as netns,
                    ):
                        handle.write(_render(path, mode, route))
                        handle.flush()
                        listings = []
                        for attempt in ("first", "second"):
                            loaded = _run([*netns, "nft", "-f", handle.name])
                            self.assertEqual(
                                loaded.returncode,
                                0,
                                f"{rel} failed to load on the {attempt} pass "
                                f"in {mode}:\n{loaded.stderr}",
                            )
                            listed = _run(
                                [*netns, "nft", "list", "table", "inet", TABLE]
                            )
                            self.assertEqual(
                                listed.returncode,
                                0,
                                f"{rel} loaded but left no table on the {attempt} "
                                f"pass in {mode}:\n{listed.stderr}",
                            )
                            listings.append(listed.stdout)
                    self.assertIn(f"table inet {TABLE}", listings[0])
                    self.assertEqual(
                        listings[0],
                        listings[1],
                        f"{rel} grew on the second pass in {mode}, so it merges "
                        "into the table it found instead of replacing it",
                    )


if __name__ == "__main__":
    unittest.main()
