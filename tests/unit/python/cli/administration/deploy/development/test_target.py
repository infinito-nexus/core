from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development import target
from cli.administration.deploy.development.coredns import CoreDNSCorefileRenderer
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

DOMAIN = default_domain_primary()
DNS_IP = "172.30.0.53"
TARGET_IP = "172.30.0.20"
RESOLVER_IP = "172.30.0.21"
KEY = "/root/.infinito-target/id_ed25519"
HOST_KEY = "ssh-ed25519 AAAAhost root@target"
PUBLIC_KEY = "ssh-ed25519 AAAAuser infinito-target"
CONTAINER_ID = "0123456789ab"
LAB = "web-app-docs-swarm-lab"
LAB_SUBNET = "192.168.244.0/24"
LAB_IP = "192.168.244.20"
NODES = ("web-app-docs-swarm-mgr-01", "web-app-docs-swarm-wrk-01")
STACK_COREFILE_TEMPLATE = "compose/coredns/Corefile.tmpl"
ENVIRONMENT = {
    "INFINITO_DOMAIN": DOMAIN,
    "INFINITO_TARGET_IP": TARGET_IP,
    "INFINITO_TARGET_KEY": KEY,
    "INFINITO_TARGET_RESOLVER_IP": RESOLVER_IP,
    "INFINITO_RUNNER_PREFIX": "infinito-test",
}


def _stack(root: Path) -> None:
    (root / ".env").write_text(
        f"INFINITO_DNS_IP={DNS_IP}\n"
        f"INFINITO_DOMAIN={DOMAIN}\n"
        f"INFINITO_TARGET_IP={TARGET_IP}\n"
        f"INFINITO_TARGET_RESOLVER_IP={RESOLVER_IP}\n",
        encoding="utf-8",
    )
    for relpath in (target.COREFILE_TEMPLATE, STACK_COREFILE_TEMPLATE):
        template = root / relpath
        template.parent.mkdir(parents=True)
        template.write_text(read_text(str(PROJECT_ROOT / relpath)), encoding="utf-8")


def _node_key(node: str) -> str:
    return f"ssh-ed25519 AAAA{node} infinito-target"


class _Stack:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run(self, args: list[str], **_: object) -> subprocess.CompletedProcess:
        self.calls.append(("run", tuple(args)))
        stdout = ""
        if args == ["ps", "-q", target.SERVICE]:
            stdout = f"{CONTAINER_ID}\n"
        elif args[:3] == ["exec", "-T", target.SERVICE]:
            command = args[3:]
            if command == ["systemctl", "is-system-running"]:
                stdout = "running\n"
            elif command[:2] == ["getent", "hosts"]:
                stdout = f"{TARGET_IP}  {command[2]}\n"
            elif command[-1] == "cat /etc/ssh/ssh_host_*_key.pub":
                stdout = f"{HOST_KEY}\n"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def exec(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        self.calls.append(("exec", tuple(cmd)))
        stdout = f"{PUBLIC_KEY}\n" if cmd[0] == "cat" else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")


class _OuterDaemon:
    def __init__(self, subnets: str) -> None:
        self.subnets = subnets
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        self.calls.append(tuple(cmd))
        stdout = ""
        if cmd[:3] == ["docker", "network", "inspect"]:
            stdout = self.subnets
        elif cmd[:2] == ["docker", "exec"]:
            node, command = cmd[2], cmd[3:]
            if command[0] == "cat":
                stdout = f"{_node_key(node)}\n"
            elif command == ["getent", "hosts", target.SERVICE]:
                stdout = f"{LAB_IP}  {target.SERVICE}\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")


def _written(calls: list[tuple[str, ...]], path: str) -> list[str]:
    return [
        call[-1]
        for call in calls
        if call[-5:-1] == ("-c", 'printf "%s" "$2" >"$1"', "sh", path)
    ]


class TestTargetCorefile(unittest.TestCase):
    def test_the_domain_answers_with_the_target_and_the_rest_goes_upstream(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _stack(root)
            out = CoreDNSCorefileRenderer(
                repo_root=root,
                template_relpath=target.COREFILE_TEMPLATE,
                output_relpath=target.COREFILE,
            ).render(show_preview=False)
            corefile = read_text(str(out))
        self.assertNotIn("${", corefile)
        self.assertIn(f"{DOMAIN}:53 {{", corefile)
        self.assertIn(f'answer "{{{{ .Name }}}} 60 IN A {TARGET_IP}"', corefile)
        self.assertIn(f"forward . {DNS_IP}", corefile)

    def test_the_resolver_listens_on_its_own_address(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _stack(root)
            out = CoreDNSCorefileRenderer(
                repo_root=root,
                template_relpath=target.COREFILE_TEMPLATE,
                output_relpath=target.COREFILE,
            ).render(show_preview=False)
            corefile = read_text(str(out))
        binds = [
            line.split()[1:]
            for line in corefile.splitlines()
            if line.split()[:1] == ["bind"]
        ]
        self.assertEqual(binds, [[RESOLVER_IP], [RESOLVER_IP]])


class TestResolverAddress(unittest.TestCase):
    def test_the_resolver_holds_its_own_address_off_the_targets_port_53(
        self,
    ) -> None:
        services = load_yaml_any(str(PROJECT_ROOT / "compose.yml"))["services"]
        resolver = services[target.RESOLVER]
        self.assertNotIn("network_mode", resolver)
        self.assertEqual(
            resolver["networks"]["default"]["ipv4_address"],
            "${INFINITO_TARGET_RESOLVER_IP:?Run 'make dotenv' to generate the .env single source of truth}",
        )


class TestKnownHosts(unittest.TestCase):
    def test_pins_every_host_key_under_the_address_and_the_hostname(self) -> None:
        pinned = target.known_hosts(
            "ssh-ed25519 AAAAed root@target\nssh-rsa AAAArsa root@target\n",
            TARGET_IP,
        )
        self.assertEqual(
            pinned,
            f"{TARGET_IP},target ssh-ed25519 AAAAed\n"
            f"{TARGET_IP},target ssh-rsa AAAArsa\n",
        )

    def test_a_target_without_host_keys_is_a_failure(self) -> None:
        with self.assertRaises(RuntimeError):
            target.known_hosts("", TARGET_IP)


class TestLabOn(unittest.TestCase):
    def test_the_target_takes_the_same_host_on_the_lab_as_on_the_stack(self) -> None:
        daemon = _OuterDaemon(f"{LAB_SUBNET} ")
        with patch.object(target.subprocess, "run", daemon):
            lab = target.lab_on(LAB)
        self.assertEqual(lab, target.Lab(network=LAB, address=LAB_IP))
        self.assertEqual(daemon.calls[0][:4], ("docker", "network", "inspect", LAB))

    def test_a_lab_without_exactly_one_ipv4_subnet_is_a_failure(self) -> None:
        for subnets in ("", "192.168.244.0/24 10.160.3.0/24 ", "fd00::/64 "):
            with (
                self.subTest(subnets=subnets),
                patch.object(target.subprocess, "run", _OuterDaemon(subnets)),
                self.assertRaises(RuntimeError),
            ):
                target.lab_on(LAB)


class TestResetForCompose(unittest.TestCase):
    def test_recreates_the_target_then_hands_out_a_strictly_pinned_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _stack(root)
            stack = _Stack(root)
            daemon = _OuterDaemon("")
            with (
                patch.dict(os.environ, ENVIRONMENT),
                patch.object(target.subprocess, "run", daemon),
            ):
                target.reset_stack_target(stack)
            self.assertTrue((root / target.COREFILE).is_file())
            self.assertTrue((root / "compose/coredns/Corefile").is_file())

        self.assertEqual(
            daemon.calls,
            [("docker", "volume", "rm", "--force", "infinito-test-target-docker")],
        )
        services = (target.SERVICE, target.RESOLVER)
        self.assertEqual(
            stack.calls[:2],
            [
                ("run", ("rm", "--stop", "--force", "--volumes", *services)),
                ("run", ("up", "-d", "--build", *services)),
            ],
        )
        self.assertNotIn(("run", ("ps", "-q", target.SERVICE)), stack.calls)
        nameservers = [
            args[-1]
            for kind, args in stack.calls
            if kind == "run" and "/etc/resolv.conf" in " ".join(args)
        ]
        self.assertEqual(nameservers, [RESOLVER_IP])
        authorized = [
            args
            for kind, args in stack.calls
            if kind == "run" and "/root/.ssh/authorized_keys" in " ".join(args)
        ]
        self.assertEqual(len(authorized), 1)
        self.assertEqual(authorized[0][-1], PUBLIC_KEY)
        execs = [args for kind, args in stack.calls if kind == "exec"]
        self.assertEqual(
            _written(execs, f"{KEY}.known_hosts"),
            [f"{TARGET_IP},target ssh-ed25519 AAAAhost\n"],
        )
        self.assertEqual(_written(execs, f"{KEY}.address"), [f"{TARGET_IP}\n"])
        probe = stack.calls[-1]
        self.assertEqual(probe[0], "exec")
        self.assertIn("StrictHostKeyChecking=yes", probe[1])
        self.assertIn(f"UserKnownHostsFile={KEY}.known_hosts", probe[1])
        self.assertIn(f"root@{TARGET_IP}", probe[1])


class TestResetForSwarm(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _stack(root)
        self.stack = _Stack(root)
        self.daemon = _OuterDaemon(f"{LAB_SUBNET} ")
        with (
            patch.dict(os.environ, ENVIRONMENT),
            patch.object(target.subprocess, "run", self.daemon),
        ):
            target.reset_lab_target(self.stack, LAB, NODES)

    def _in_node(self, node: str) -> list[tuple[str, ...]]:
        return [
            call[3:]
            for call in self.daemon.calls
            if call[:3] == ("docker", "exec", node)
        ]

    def test_joins_the_recreated_target_to_the_lab_under_its_hostname(self) -> None:
        self.assertIn(
            (
                "docker",
                "network",
                "connect",
                "--ip",
                LAB_IP,
                "--alias",
                target.SERVICE,
                LAB,
                CONTAINER_ID,
            ),
            self.daemon.calls,
        )
        up = self.stack.calls.index(
            ("run", ("up", "-d", "--build", target.SERVICE, target.RESOLVER))
        )
        self.assertEqual(
            self.stack.calls[up + 1], ("run", ("ps", "-q", target.SERVICE))
        )

    def test_every_node_holds_a_key_of_its_own_and_the_infinito_container_none(
        self,
    ) -> None:
        self.assertEqual([kind for kind, _ in self.stack.calls if kind == "exec"], [])
        authorized = [
            args
            for kind, args in self.stack.calls
            if kind == "run" and "/root/.ssh/authorized_keys" in " ".join(args)
        ]
        self.assertEqual(len(authorized), 1)
        self.assertEqual(authorized[0][-2:], tuple(_node_key(node) for node in NODES))

    def test_every_node_reaches_the_target_on_the_lab(self) -> None:
        for node in NODES:
            with self.subTest(node=node):
                calls = self._in_node(node)
                self.assertEqual(
                    _written(calls, f"{KEY}.known_hosts"),
                    [f"{LAB_IP},target ssh-ed25519 AAAAhost\n"],
                )
                self.assertEqual(_written(calls, f"{KEY}.address"), [f"{LAB_IP}\n"])
                self.assertIn(("getent", "hosts", target.SERVICE), calls)
                probe = calls[-1]
                self.assertEqual(probe[0], "ssh")
                self.assertIn("StrictHostKeyChecking=yes", probe)
                self.assertIn(f"root@{LAB_IP}", probe)


class TestHandler(unittest.TestCase):
    def test_lab_and_nodes_come_together(self) -> None:
        for lab, nodes in ((LAB, None), (None, list(NODES))):
            with self.subTest(lab=lab, nodes=nodes), self.assertRaises(SystemExit):
                target.handler(argparse.Namespace(lab=lab, nodes=nodes))

    def test_without_a_lab_the_stack_resets_its_own_target(self) -> None:
        with (
            patch.object(target, "make_compose") as make_compose,
            patch.object(target, "reset_stack_target") as reset_stack_target,
        ):
            self.assertEqual(
                target.handler(argparse.Namespace(lab=None, nodes=None)), 0
            )
        reset_stack_target.assert_called_once_with(make_compose.return_value)

    def test_with_a_lab_the_named_nodes_hold_the_key(self) -> None:
        with (
            patch.object(target, "make_compose") as make_compose,
            patch.object(target, "reset_lab_target") as reset_lab_target,
        ):
            target.handler(argparse.Namespace(lab=LAB, nodes=list(NODES)))
        reset_lab_target.assert_called_once_with(
            make_compose.return_value, LAB, list(NODES)
        )


if __name__ == "__main__":
    unittest.main()
