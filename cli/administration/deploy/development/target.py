"""Reset the shared ``target`` service to a bare systemd and sshd machine."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.env.handlers.infinito.target_ip import address_in

from .common import make_compose
from .coredns import CoreDNSCorefileRenderer

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from .compose import Compose

SERVICE = "target"
RESOLVER = "target-resolver"
COREFILE_TEMPLATE = "compose/target/Corefile.tmpl"
COREFILE = "compose/target/Corefile"
PROBE_LABEL = "target-probe"
SYSTEMD_TRIES = 40
SYSTEMD_DELAY_S = 3
RESOLVER_TRIES = 30
RESOLVER_DELAY_S = 2
SSH_TRIES = 30
SSH_DELAY_S = 2
HOSTNAME_TRIES = 15
HOSTNAME_DELAY_S = 2


class StackHolder:
    """The stack's ``infinito`` container, which reaches the target on the stack network.

    Args:
        compose: the development stack the container belongs to.
        address: the target's address on the stack network.
    """

    def __init__(self, compose: Compose, address: str) -> None:
        self.compose = compose
        self.address = address
        self.name = "the infinito container"

    def run(
        self, argv: list[str], *, capture: bool, check: bool
    ) -> subprocess.CompletedProcess:
        return self.compose.exec(argv, check=check, capture=capture, tty=False)


class NodeHolder:
    """A swarm node container, which reaches the target on the lab network.

    Args:
        container: the node's container name on the outer daemon.
        address: the target's address on the lab network.
    """

    def __init__(self, container: str, address: str) -> None:
        self.container = container
        self.address = address
        self.name = container

    def run(
        self, argv: list[str], *, capture: bool, check: bool
    ) -> subprocess.CompletedProcess:
        cmd = ["docker", "exec", self.container, *argv]
        result = subprocess.run(cmd, capture_output=capture, text=True, check=False)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, output=result.stdout, stderr=result.stderr
            )
        return result


Holder = StackHolder | NodeHolder


@dataclass(frozen=True)
class Lab:
    """The swarm lab network a swarm round joins the target to.

    Args:
        network: the lab network's name.
        address: the target's address on it.
    """

    network: str
    address: str


def lab_on(network: str) -> Lab:
    """Place the target on the lab network the way it sits on the stack network.

    Args:
        network: the lab network's name.

    Returns:
        The lab, with the target at host ``.20`` of its IPv4 subnet.
    """
    subnets = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            network,
            "--format",
            "{{range .IPAM.Config}}{{.Subnet}} {{end}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    ipv4 = [subnet for subnet in subnets if ":" not in subnet]
    if len(ipv4) != 1:
        raise RuntimeError(
            f"{network} carries the IPv4 subnets {ipv4}; the target needs exactly one"
        )
    return Lab(network=network, address=address_in(ipv4[0]))


def _in_target(
    compose: Compose, *cmd: str, capture: bool, check: bool
) -> subprocess.CompletedProcess:
    return compose.run(["exec", "-T", SERVICE, *cmd], capture=capture, check=check)


def _join_lab(compose: Compose, lab: Lab) -> None:
    container = compose.run(["ps", "-q", SERVICE], capture=True).stdout.strip()
    if not container:
        raise RuntimeError(
            f"compose reports no {SERVICE} container to join {lab.network}"
        )
    subprocess.run(
        [
            "docker",
            "network",
            "connect",
            "--ip",
            lab.address,
            "--alias",
            SERVICE,
            lab.network,
            container,
        ],
        check=True,
    )


def _await_systemd(compose: Compose) -> None:
    state = ""
    for _ in range(SYSTEMD_TRIES):
        result = _in_target(
            compose, "systemctl", "is-system-running", capture=True, check=False
        )
        state = result.stdout.strip()
        if state in ("running", "degraded"):
            return
        time.sleep(SYSTEMD_DELAY_S)
    raise RuntimeError(f"systemd never came up in the target (last state: {state!r})")


def _answer_the_domain_itself(
    compose: Compose, address: str, resolver: str, domain: str
) -> None:
    _in_target(
        compose,
        "sh",
        "-c",
        'printf "nameserver %s\\n" "$1" >/etc/resolv.conf',
        "sh",
        resolver,
        capture=False,
        check=True,
    )
    probe = f"{PROBE_LABEL}.{domain}"
    seen = ""
    for _ in range(RESOLVER_TRIES):
        result = _in_target(
            compose, "getent", "hosts", probe, capture=True, check=False
        )
        fields = result.stdout.split()
        seen = fields[0] if fields else ""
        if seen == address:
            return
        time.sleep(RESOLVER_DELAY_S)
    raise RuntimeError(
        f"the target resolves {probe} to {seen!r} instead of its own {address}"
    )


def _issue_key(holder: Holder, key: str) -> str:
    holder.run(
        [
            "sh",
            "-c",
            (
                'install -d -m 700 "$(dirname "$1")"'
                ' && rm -f "$1" "$1.pub" "$1.known_hosts" "$1.address"'
                ' && ssh-keygen -q -t ed25519 -N "" -C infinito-target -f "$1"'
            ),
            "sh",
            key,
        ],
        capture=False,
        check=True,
    )
    return holder.run(["cat", f"{key}.pub"], capture=True, check=True).stdout.strip()


def _authorize(compose: Compose, public_keys: list[str]) -> None:
    _in_target(
        compose,
        "sh",
        "-c",
        "install -d -m 700 /root/.ssh"
        ' && printf "%s\\n" "$@" >/root/.ssh/authorized_keys'
        " && chmod 600 /root/.ssh/authorized_keys",
        "sh",
        *public_keys,
        capture=False,
        check=True,
    )


def known_hosts(host_keys: str, address: str) -> str:
    """Pin the target's host keys under its address and its hostname.

    Args:
        host_keys: the target's ``/etc/ssh/ssh_host_*_key.pub`` lines.
        address: the target's address on the holder's network.

    Returns:
        ``known_hosts`` lines naming both the address and ``SERVICE``.
    """
    pinned = []
    for line in host_keys.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        pinned.append(f"{address},{SERVICE} {fields[0]} {fields[1]}\n")
    if not pinned:
        raise RuntimeError("the target generated no SSH host key to pin")
    return "".join(pinned)


def _write(holder: Holder, path: str, content: str) -> None:
    holder.run(
        ["sh", "-c", 'printf "%s" "$2" >"$1"', "sh", path, content],
        capture=False,
        check=True,
    )


def _pin_host_keys(holder: Holder, key: str, host_keys: str) -> None:
    _write(holder, f"{key}.known_hosts", known_hosts(host_keys, holder.address))
    _write(holder, f"{key}.address", f"{holder.address}\n")


def _await_hostname(holder: Holder) -> None:
    seen = ""
    for _ in range(HOSTNAME_TRIES):
        result = holder.run(["getent", "hosts", SERVICE], capture=True, check=False)
        fields = result.stdout.split()
        seen = fields[0] if fields else ""
        if seen == holder.address:
            return
        time.sleep(HOSTNAME_DELAY_S)
    raise RuntimeError(
        f"{holder.name} resolves {SERVICE} to {seen!r} instead of {holder.address}"
    )


def _await_ssh(holder: Holder, key: str) -> None:
    last = ""
    for _ in range(SSH_TRIES):
        result = holder.run(
            [
                "ssh",
                "-i",
                key,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={key}.known_hosts",
                f"root@{holder.address}",
                "true",
            ],
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return
        last = result.stderr.strip()
        time.sleep(SSH_DELAY_S)
    raise RuntimeError(
        f"sshd on the target never let {holder.name} in with {key} at {holder.address}: {last}"
    )


def reset_target(compose: Compose, holders: Sequence[Holder], lab: Lab | None) -> None:
    """Recreate the target bare and hand every holder a fresh key.

    Args:
        compose: the development stack the target belongs to.
        holders: the containers that reach root on the target afterwards, each
            with a key of its own at ``INFINITO_TARGET_KEY``.
        lab: the swarm lab network the target joins under the alias
            ``SERVICE``, or ``None`` for a compose round.
    """
    address = os.environ["INFINITO_TARGET_IP"]
    resolver = os.environ["INFINITO_TARGET_RESOLVER_IP"]
    key = os.environ["INFINITO_TARGET_KEY"]
    domain = os.environ["INFINITO_DOMAIN"]
    prefix = os.environ["INFINITO_RUNNER_PREFIX"]

    print(">>> Resetting the shared target to a bare systemd and sshd machine")
    CoreDNSCorefileRenderer(repo_root=compose.repo_root).render(show_preview=False)
    CoreDNSCorefileRenderer(
        repo_root=compose.repo_root,
        template_relpath=COREFILE_TEMPLATE,
        output_relpath=COREFILE,
    ).render(show_preview=False)
    compose.run(["rm", "--stop", "--force", "--volumes", SERVICE, RESOLVER])
    subprocess.run(
        ["docker", "volume", "rm", "--force", f"{prefix}-target-docker"],
        check=True,
    )
    compose.run(["up", "-d", "--build", SERVICE, RESOLVER])
    if lab is not None:
        _join_lab(compose, lab)

    _await_systemd(compose)
    _answer_the_domain_itself(compose, address, resolver, domain)
    _authorize(compose, [_issue_key(holder, key) for holder in holders])
    host_keys = _in_target(
        compose,
        "sh",
        "-c",
        "cat /etc/ssh/ssh_host_*_key.pub",
        capture=True,
        check=True,
    ).stdout
    for holder in holders:
        _pin_host_keys(holder, key, host_keys)
        if lab is not None:
            _await_hostname(holder)
        _await_ssh(holder, key)
        print(
            f">>> Target ready at {holder.address} (hostname {SERVICE});"
            f" {holder.name} reaches root there with {key}"
        )


def reset_stack_target(compose: Compose) -> None:
    """Reset the target for a compose round, held by the ``infinito`` container.

    Args:
        compose: the development stack the target belongs to.
    """
    reset_target(
        compose, [StackHolder(compose, os.environ["INFINITO_TARGET_IP"])], None
    )


def reset_lab_target(compose: Compose, network: str, nodes: Sequence[str]) -> None:
    """Reset the target for a swarm round, held by the named swarm nodes.

    Args:
        compose: the development stack the target belongs to.
        network: the swarm lab network the target joins.
        nodes: the node containers that each receive a key of their own.
    """
    lab = lab_on(network)
    reset_target(compose, [NodeHolder(node, lab.address) for node in nodes], lab)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "target-reset",
        help="Reset the shared target to a bare systemd and sshd machine.",
    )
    p.add_argument(
        "--lab",
        help=(
            "Swarm lab network the target joins; the --node containers then hold"
            " its key instead of the infinito container."
        ),
    )
    p.add_argument(
        "--node",
        dest="nodes",
        action="append",
        help="Swarm node container that receives a key of its own; repeat per node.",
    )
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    if bool(args.lab) != bool(args.nodes):
        raise SystemExit(
            "target-reset: --lab and --node are given together or not at all"
        )
    compose = make_compose()
    if args.lab:
        reset_lab_target(compose, args.lab, args.nodes)
    else:
        reset_stack_target(compose)
    return 0
