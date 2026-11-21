from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.port_bands import load_port_bands
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT
from . import test_per_node_torrc as per_node
from .test_egress_route import _egress, chain, render

ROLE = PROJECT_ROOT / "roles/svc-net-tor"
SCRIPT = ROLE / "files/shell/chutney.sh"
DOCKERFILE = ROLE / "files/Dockerfile"
ENTRYPOINT = ROLE / "files/shell/entrypoint.sh"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
TORRC = ROLE / "templates/torrc.j2"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
TOR = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["tor"]
CHUTNEY = TOR["chutney"]
LOOPBACK = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/08_networks.yml"))[
    "NETWORK_LOOPBACK_IPV4"
]
UPSTREAM_BASES = {
    "orport": 5100,
    "dirport": 7100,
    "controlport": 8000,
    "socksport": 9000,
    "extorport": 9500,
    "ptport": 9900,
    "dnsport": 10000,
}
EPHEMERAL_START = 32768
_BUILD_ARG = re.compile(r'^\s+(TOR_\w+):\s+"\{\{ (\w+) \}\}"$', re.MULTILINE)
_DOCKER_ARG = re.compile(r"^ARG (\w+)$", re.MULTILINE)
_INCLUDE = re.compile(r"^%include (\S+)$", re.MULTILINE)
_SPOOF_RULE = re.compile(
    r"^fib saddr \. iif oif missing (?P<protocol>tcp|udp) dport \{ (?P<ports>.+) \} drop$"
)
FAKE_CHUTNEY = """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

root = pathlib.Path.cwd()
spec = json.loads((root / "fake.json").read_text())
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps([sys.argv[1:], os.environ.get("CHUTNEY_LISTEN_ADDRESS")]) + "\\n")
if sys.argv[1] == "init":
    (root / "net").mkdir()
    (root / "net/address").write_text(os.environ["CHUTNEY_LISTEN_ADDRESS"])
if sys.argv[1] == "configure":
    address = (root / "net/address").read_text()
    authorities = [
        f"DirAuthority test{n:03d}a orport={5100 + n} {address}:{7100 + n} FP{n}"
        for n in range(spec["authorities"])
    ]
    for n in range(spec["nodes"]):
        node = root / "net/nodes" / f"{n:03d}a"
        node.mkdir(parents=True)
        lines = ["TestingTorNetwork 1", f"DataDirectory {node}", *authorities]
        (node / "torrc").write_text("\\n".join(lines) + "\\n")
if sys.argv[1] == "start":
    running = []
    for pidfile in sorted((root / "net/nodes").glob("*/pid")):
        try:
            os.kill(int(pidfile.read_text()), 0)
        except OSError:
            continue
        running.append(pidfile.parent.name)
    (root / "running.json").write_text(json.dumps(running))
"""


def _tornet(bases: dict[str, int]) -> str:
    lines = [f"        self.{name}_base: int = {port}" for name, port in bases.items()]
    return "class Network:\n    def __init__(self) -> None:\n" + "\n".join(lines) + "\n"


def _checkout(root: Path, nodes: int, authorities: int, bases=UPSTREAM_BASES) -> Path:
    checkout = root / "chutney"
    (checkout / "lib/chutney").mkdir(parents=True)
    (checkout / "lib/chutney/TorNet.py").write_text(_tornet(bases))
    (checkout / "chutney").write_text(FAKE_CHUTNEY)
    (checkout / "chutney").chmod(0o755)
    (checkout / "fake.json").write_text(
        json.dumps({"nodes": nodes, "authorities": authorities})
    )
    return checkout


def _scratch(path: Path) -> str:
    return path.read_text()  # nocheck: cache-read tempdir checkout


def _calls(checkout: Path) -> list[list]:
    lines = _scratch(checkout / "calls.jsonl").splitlines()
    return [json.loads(line) for line in lines]


def _script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def _evaluate(name: str, swarm: bool = True, **variables):
    return per_node.evaluate(
        VARS[name],
        **per_node.play_context("manager-1", "manager-1", swarm),
        TOR_CHUTNEY_BASES=CHUTNEY["port_bases"],
        TOR_CHUTNEY_PORT_SPAN=CHUTNEY["port_span"],
        NETWORK_LOOPBACK_IPV4=LOOPBACK,
        **variables,
    )


def _build(checkout: Path, address: str = "10.0.0.1"):
    return _script(
        "build",
        str(checkout),
        CHUTNEY["net"],
        address,
        _evaluate("TOR_CHUTNEY_PORT_BASES"),
        str(CHUTNEY["port_span"]),
    )


def _windows() -> list[range]:
    return [
        range(base, base + CHUTNEY["port_span"])
        for base in CHUTNEY["port_bases"].values()
    ]


def _overlaps(window: range, start: int, end: int) -> bool:
    return window.start <= end and start < window.stop


def _guard(flavor: str, routes: bool) -> list[str]:
    window = _evaluate("TOR_CHUTNEY_PORT_RANGE")
    ports = _evaluate(
        "TOR_CHUTNEY_GUARDED_PORTS", TOR_FLAVOR=flavor, TOR_CHUTNEY_PORT_RANGE=window
    )
    ruleset = render(
        "nftables.conf.j2",
        "onion",
        _egress(),
        TOR_NODE_ROUTES=routes,
        TOR_CHUTNEY_GUARDED_PORTS=ports,
    )
    return chain(ruleset, "guard")


class TestChutneyClusterNet(unittest.TestCase):
    def test_the_build_moves_every_declared_base_and_bakes_the_net(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkout = _checkout(Path(root), nodes=9, authorities=4)
            built = _build(checkout)
            self.assertEqual(built.returncode, 0, built.stderr)
            tornet = _scratch(checkout / "lib/chutney/TorNet.py")
            self.assertEqual(
                tornet, _tornet({**UPSTREAM_BASES, **CHUTNEY["port_bases"]})
            )
            (init, configure) = _calls(checkout)
            self.assertEqual(init, [["init", "--net", CHUTNEY["net"]], "10.0.0.1"])
            self.assertEqual(configure[0], ["configure"])
            torrcs = sorted((checkout / "net/nodes").glob("*/torrc"))
            self.assertEqual(len(torrcs), 9)
            for torrc in torrcs:
                self.assertTrue(_scratch(torrc).endswith("NumCPUs 1\n"))
            conf = _scratch(checkout / "chutney-net.conf").splitlines()
            self.assertEqual(conf, sorted(set(conf)))
            self.assertEqual(conf[4:], ["TestingTorNetwork 1"])
            for line in conf[:4]:
                self.assertRegex(line, r"^DirAuthority \S+ orport=\d+ 10\.0\.0\.1:\d+ ")

    def test_the_build_refuses_what_would_leak_or_collide(self) -> None:
        cases = {
            "a base chutney no longer sets": {
                "nodes": 9,
                "authorities": 4,
                "bases": {k: v for k, v in UPSTREAM_BASES.items() if k != "dnsport"},
            },
            "more nodes than one base hands out": {
                "nodes": CHUTNEY["port_span"] + 1,
                "authorities": 4,
            },
            "no authority, so the public network": {"nodes": 9, "authorities": 0},
        }
        for case, spec in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                built = _build(_checkout(Path(root), **spec))
                self.assertNotEqual(built.returncode, 0)
                self.assertIn("[tor-chutney] ERROR:", built.stderr)

    def test_only_the_node_holding_the_address_starts_the_net(self) -> None:
        for address, starts in ((LOOPBACK, True), ("192.0.2.1", False)):
            with self.subTest(address=address), tempfile.TemporaryDirectory() as root:
                checkout = _checkout(Path(root), nodes=9, authorities=4)
                self.assertEqual(_build(checkout, address).returncode, 0)
                conf = Path(root) / "run/tor/chutney-net.conf"
                ran = _script("run", str(checkout), address, str(conf))
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertEqual(
                    _scratch(conf), _scratch(checkout / "chutney-net.conf")
                )
                started = [call[0] for call in _calls(checkout)[2:]]
                self.assertEqual(
                    started, [["start"], ["wait_for_bootstrap"]] if starts else []
                )

    def test_a_restarted_owner_starts_every_node_again(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkout = _checkout(Path(root), nodes=9, authorities=4)
            self.assertEqual(_build(checkout, LOOPBACK).returncode, 0)
            for node in (checkout / "net/nodes").iterdir():
                (node / "pid").write_text(str(os.getpid()))
            conf = Path(root) / "run/tor/chutney-net.conf"
            ran = _script("run", str(checkout), LOOPBACK, str(conf))
            self.assertEqual(ran.returncode, 0, ran.stderr)
            running = json.loads(_scratch(checkout / "running.json"))
            self.assertEqual(running, [])

    def test_a_node_without_the_baked_net_does_not_start_tor(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkout = _checkout(Path(root), nodes=9, authorities=4)
            conf = Path(root) / "run/tor/chutney-net.conf"
            ran = _script("run", str(checkout), LOOPBACK, str(conf))
            self.assertNotEqual(ran.returncode, 0)
            self.assertFalse(conf.exists())
            self.assertFalse((checkout / "calls.jsonl").exists())

    def test_the_image_bakes_the_net_and_every_node_runs_it(self) -> None:
        dockerfile = read_text(str(DOCKERFILE))
        self.assertIn("COPY chutney.sh ${TOR_CHUTNEY_SCRIPT_PATH}", dockerfile)
        self.assertRegex(
            dockerfile,
            r'"\$\{TOR_CHUTNEY_SCRIPT_PATH\}" build /opt/chutney "\$\{TOR_CHUTNEY_NET\}" '
            r'\\\s+"\$\{TOR_CHUTNEY_ADDRESS\}" "\$\{TOR_CHUTNEY_PORT_BASES\}" '
            r'"\$\{TOR_CHUTNEY_PORT_SPAN\}"',
        )
        for name in ("TOR_CHUTNEY_ADDRESS", "TOR_CHUTNEY_SCRIPT_PATH"):
            with self.subTest(env=name):
                self.assertIn(f"ENV {name}=${{{name}}}", dockerfile)
        (include,) = _INCLUDE.findall(read_text(str(TORRC)))
        self.assertIn(
            f'"${{TOR_CHUTNEY_SCRIPT_PATH}}" run /opt/chutney '
            f'"${{TOR_CHUTNEY_ADDRESS}}" {include}\n',
            read_text(str(ENTRYPOINT)),
        )

    def test_the_compose_build_passes_exactly_the_args_the_image_declares(
        self,
    ) -> None:
        passed = dict(_BUILD_ARG.findall(read_text(str(COMPOSE))))
        self.assertEqual(
            set(passed), set(_DOCKER_ARG.findall(read_text(str(DOCKERFILE))))
        )
        chutney = {arg: var for arg, var in passed.items() if "CHUTNEY" in arg}
        self.assertEqual(len(chutney), 5)
        for arg, var in chutney.items():
            with self.subTest(arg=arg):
                self.assertEqual(var, arg)
                self.assertIn(var, VARS)

    def test_the_net_listens_on_the_stack_host_in_swarm_and_loopback_in_compose(
        self,
    ) -> None:
        self.assertEqual(
            _evaluate("TOR_CHUTNEY_ADDRESS"), per_node.ADDRESSES["manager-1"]
        )
        self.assertEqual(_evaluate("TOR_CHUTNEY_ADDRESS", swarm=False), LOOPBACK)

    def test_the_port_block_clears_every_band_and_the_tor_listeners(self) -> None:
        windows = _windows()
        bands = [
            (f"{scope}.{category}", band)
            for scope, categories in load_port_bands().items()
            for category, band in categories.items()
        ]
        for index, window in enumerate(windows):
            with self.subTest(window=window):
                for other in windows[index + 1 :]:
                    self.assertFalse(_overlaps(window, other.start, other.stop - 1))
                self.assertLess(window.stop, EPHEMERAL_START)
                for name, band in bands:
                    self.assertFalse(
                        _overlaps(window, band["start"], band["end"]), name
                    )
                for port in TOR["ports"]["local"].values():
                    self.assertNotIn(port, window)
        start, end = map(int, _evaluate("TOR_CHUTNEY_PORT_RANGE").split("-"))
        self.assertEqual(
            set(range(start, end + 1)), {port for w in windows for port in w}
        )

    def test_every_node_admits_only_internal_sources_to_the_chutney_ports(
        self,
    ) -> None:
        window = _evaluate("TOR_CHUTNEY_PORT_RANGE")
        for routes in (True, False):
            with self.subTest(routes=routes):
                guard = _guard("chutney", routes)
                for protocol in ("tcp", "udp"):
                    self.assertIn(
                        f"ip saddr != @internal {protocol} dport {window} drop", guard
                    )
                    (spoofed,) = [
                        match["ports"].split(", ")
                        for match in map(_SPOOF_RULE.match, guard)
                        if match is not None and match["protocol"] == protocol
                    ]
                    self.assertIn(window, spoofed)
                public = _guard("public", routes)
                self.assertFalse([rule for rule in public if window in rule])


if __name__ == "__main__":
    unittest.main()
