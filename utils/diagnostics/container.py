#!/usr/bin/env python3
"""SPOT rescue diagnostics, called ONLY by the CI workflows on failure (never
from Ansible ``rescue:`` blocks; the lint forbids those).

Captures a full failure snapshot on the current level (all containers with
their logs and inspect, all swarm services with ps and logs, the systemd
journal, host resources), then RECURSES: it copies itself into every running
container that carries python3 and a container runtime (DiD) and repeats the
capture there, pulling each nested snapshot back under
``containers/<name>/nested/`` - from the outermost caller down to the deepest
runtime, however deep the nesting goes. ``RESCUE_SEEN`` carries the ids already
entered, so a runtime that lists itself is cut as a cycle.

Every collector is best-effort: a missing source must never abort the
capture. ``INFINITO_RESCUE_DIAGNOSTICS_DIR`` (SPOT:
``group_vars/all/05_paths.yml`` ``DIR_RESCUE_DIAGNOSTICS``) is the required
output root; it is never defaulted here so there is one source. Prints one
condensed summary and ALWAYS exits 1 so a failing pipeline stays failing.

Usage:
    container.py [APP_ID] [CONTEXT]
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_EXEC_TIMEOUT = 120
_PROBE_TIMEOUT = 30

_JOURNAL_TIMEOUT = 600
_NESTED_TIMEOUT = 600
_TAR_TIMEOUT = 300
_SELF_IN_CONTAINER = "/tmp/rescue-self.py"  # noqa: S108 - fixed staging path inside the inspected container
_LOCAL_DUMPS_ENV = "INFINITO_RESCUE_LOCAL_DUMPS_DIR"
_PROBE_HOSTS = ("deb.debian.org", "ghcr.io", "repo.packagist.org")


def runtime_bin() -> str | None:
    return shutil.which("container") or shutil.which("docker")


def run(
    cmd: list[str], *, timeout: int = _EXEC_TIMEOUT, stdin: bytes | None = None
) -> subprocess.CompletedProcess:
    """Best-effort subprocess wrapper: never raises, captures everything."""
    try:
        return subprocess.run(
            cmd, input=stdin, capture_output=True, timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return subprocess.CompletedProcess(cmd, 124, b"", str(exc).encode())


def write(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        print(f"rescue: cannot write {path}: {exc}", file=sys.stderr)


def capture(
    out: Path, name: str, cmd: list[str], *, timeout: int = _EXEC_TIMEOUT
) -> None:
    result = run(cmd, timeout=timeout)
    body = result.stdout + result.stderr
    if not body.strip():
        body = f"[no output, exit {result.returncode}]\n".encode()
    write(out / name, body)


def source_name(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.strip("/")) + ".txt"


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def list_lines(cmd: list[str]) -> list[str]:
    result = run(cmd)
    if result.returncode != 0:
        return []
    return [
        line
        for line in result.stdout.decode(errors="replace").splitlines()
        if line.strip()
    ]


def collect_host(out: Path, app_id: str, context: str, stamp: str) -> None:
    hostname = run(["hostname"]).stdout.decode(errors="replace").strip()
    write(
        out / "meta.txt",
        f"application_id: {app_id}\ncontext: {context}\ncaptured_utc: {stamp}\nhost: {hostname}\n".encode(),
    )
    capture(out, "system.txt", ["uname", "-a"])
    for name, cmd in (
        ("df.txt", ["df", "-h"]),
        ("df-inodes.txt", ["df", "-i"]),
        ("free.txt", ["free", "-m"]),
        ("uptime.txt", ["uptime"]),
        ("systemctl.txt", ["systemctl", "list-units", "--all", "--no-pager"]),
        ("ip-addr.txt", ["ip", "-4", "addr"]),
        ("ip-route.txt", ["ip", "-4", "route"]),
        ("ip-neigh.txt", ["ip", "-4", "neigh"]),
        ("firewall-rules.txt", ["iptables-save"]),
        ("sockets-udp.txt", ["ss", "-lunp"]),
        ("sockets-tcp.txt", ["ss", "-lntp"]),
        ("processes.txt", ["ps", "-eo", "pid,ppid,stat,etimes,rss,comm"]),
        ("dnsmasq-conf-d.txt", ["grep", "-rH", ".", "/etc/dnsmasq.d"]),
        ("zfs-dev.txt", ["ls", "-l", "/dev/zfs"]),
        ("zfs-version.txt", ["zfs", "version"]),
    ):
        capture(out, name, cmd)
    collect_resolver_probes(out)
    collect_dnsmasq_introspection(out)
    for path in (
        "/etc/os-release",
        "/etc/resolv.conf",
        "/etc/nsswitch.conf",
        "/etc/hosts",
        "/etc/dnsmasq.conf",
        "/etc/docker/daemon.json",
        "/proc/modules",
        "/proc/devices",
        "/proc/misc",
        "/proc/net/udp",
        "/proc/net/tcp",
        "/proc/net/udp6",
        "/proc/net/tcp6",
        "/proc/net/snmp",
        "/proc/net/netstat",
        "/proc/net/stat/nf_conntrack",
    ):
        capture(out, source_name(path), ["cat", path])
    capture(out, "dmesg.txt", ["dmesg", "-T"])
    for name, cmd in (
        ("journal.txt", ["journalctl", "-b", "--no-pager"]),
        ("journal-warnings.txt", ["journalctl", "-b", "-p", "warning", "--no-pager"]),
        ("journal-errors.txt", ["journalctl", "-b", "-p", "err", "--no-pager"]),
    ):
        capture(out, name, cmd, timeout=_JOURNAL_TIMEOUT)
    collect_service_state(out)


def collect_dnsmasq_introspection(out: Path) -> None:
    """fd table and rlimits of every live dnsmasq process.

    Run 32118850138 caught dnsmasq alive with zero sockets and nothing in
    the journal; the socket table alone cannot separate closed listeners
    from an exhausted fd table or a lost netlink watch, the fd list can.
    """
    for pid in " ".join(list_lines(["pidof", "dnsmasq"])).split():
        capture(out, f"dnsmasq-{pid}-fd.txt", ["ls", "-l", f"/proc/{pid}/fd"])
        capture(out, f"dnsmasq-{pid}-limits.txt", ["cat", f"/proc/{pid}/limits"])


def daemon_json_dns() -> list[str]:
    """Nameservers pinned under the ``dns`` key of /etc/docker/daemon.json.

    A Tor node's resolv.conf names only the local dnsmasq, so probing its
    entries alone cannot say whether the pinned upstream was still alive when
    that dnsmasq went silent. Anything unreadable or keyless yields [].
    """
    proc = run(["cat", "/etc/docker/daemon.json"])
    if proc.returncode != 0:
        return []
    try:
        dns = json.loads(proc.stdout.decode(errors="replace")).get("dns")
    except ValueError:
        return []
    if not isinstance(dns, list):
        return []
    return [str(server) for server in dns]


def collect_resolver_probes(out: Path) -> None:
    """Resolve each probed name, once through the stack and once per nameserver.

    ``getent`` honours nsswitch and cannot address a server, so on its own it
    cannot say which of the resolvers in resolv.conf refused. Where the distro
    ships a query tool, ask every nameserver directly; where it does not, the
    per-name verdicts still stand on their own.
    """
    tool = next(
        (
            argv
            for argv in (
                ["dig", "+time=3", "+tries=1"],
                ["nslookup", "-timeout=3"],
            )
            if shutil.which(argv[0])
        ),
        None,
    )
    servers = [
        parts[1]
        for parts in (line.split() for line in list_lines(["cat", "/etc/resolv.conf"]))
        if parts[:1] == ["nameserver"] and len(parts) > 1
    ]
    servers += [server for server in daemon_json_dns() if server not in servers]
    for host in _PROBE_HOSTS:
        capture(out, f"resolve-{source_name(host)}", ["getent", "hosts", host])
        if not tool:
            continue
        for server in servers:
            argv = (
                [*tool, f"@{server}", host, "A"]
                if tool[0] == "dig"
                else [*tool, host, server]
            )
            capture(out, f"resolve-{source_name(f'{host}-via-{server}')}", argv)


def collect_service_state(out: Path) -> None:
    """Dump per-service liveness for every loaded service unit.

    ``systemctl list-units`` reports a forking unit as active/running while its
    guessed main process is gone, and the containers carry no ``ps``, so the
    unit table alone cannot answer whether a daemon is still there. MainPID and
    NRestarts can.
    """
    units = [
        line.split()[0]
        for line in list_lines(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager"]
        )
        if line.split() and line.split()[0].endswith(".service")
    ]
    if not units:
        return
    capture(
        out,
        "service-state.txt",
        [
            "systemctl",
            "show",
            "--property=Id,ActiveState,SubState,MainPID,NRestarts,ExecMainStatus,ExecMainStartTimestamp",
            *units,
        ],
    )


def collect_local_dumps(out: Path) -> None:
    """Copy the in-play role dumps next to the snapshot.

    ``out`` itself lives under the dump dir (both derive from
    INFINITO_RESCUE_DIAGNOSTICS_DIR), so the walk must skip its own
    output subtree or copytree recurses into the growing destination
    until ENAMETOOLONG."""
    configured = os.environ.get(_LOCAL_DUMPS_ENV)
    if not configured:
        return
    src = Path(configured)
    if not src.is_dir():
        return
    out_resolved = out.resolve()

    def _skip_own_output(dirpath: str, names: list[str]) -> list[str]:
        skipped = []
        for entry in names:
            p = (Path(dirpath) / entry).resolve()
            if p == out_resolved or out_resolved.is_relative_to(p):
                skipped.append(entry)
        return skipped

    with contextlib.suppress(OSError):
        shutil.copytree(
            src, out / "local-dumps", dirs_exist_ok=True, ignore=_skip_own_output
        )


def collect_networks(out: Path, rt: str) -> None:
    """Dump the network definitions behind every container's resolver.

    A container resolves through the runtime's embedded server on 127.0.0.11,
    which forwards to whatever the network was created with, so ``inspect`` on
    the container shows the address but never the forwarder behind it.
    """
    capture(out, "networks.txt", [rt, "network", "ls"])
    for net in list_lines([rt, "network", "ls", "--format", "{{.Name}}"]):
        capture(
            out / "networks",
            f"{sanitize(net)}.inspect.json",
            [rt, "network", "inspect", net],
        )


def collect_runtime(out: Path, rt: str) -> tuple[list[str], list[str]]:
    capture(out, "runtime.txt", [rt, "info"])
    capture(out, "stats.txt", [rt, "stats", "--no-stream", "--no-trunc"])
    capture(out, "containers.txt", [rt, "ps", "-a"])
    capture(out, "runtime-df.txt", [rt, "system", "df", "-v"])
    capture(out, "volumes.txt", [rt, "volume", "ls"])
    capture(out, "images.txt", [rt, "image", "ls", "--digests", "--no-trunc"])
    capture(out, "nodes.txt", [rt, "node", "ls"])
    collect_networks(out, rt)
    capture(
        out,
        "journal-daemon.txt",
        ["journalctl", "-b", "-u", "docker", "-u", "containerd", "--no-pager"],
        timeout=_JOURNAL_TIMEOUT,
    )
    capture(
        out,
        "journal-kill-markers.txt",
        ["journalctl", "-b", "-t", "infinito-kill", "--no-pager"],
        timeout=_JOURNAL_TIMEOUT,
    )
    capture(
        out / "containers",
        "_events.txt",
        ["timeout", "15", rt, "events", "--since", "6h"],
        timeout=40,
    )
    containers = list_lines([rt, "ps", "-a", "--format", "{{.Names}}"])
    for name in containers:
        safe = sanitize(name)
        capture(out / "containers", f"{safe}.log", [rt, "logs", name])
        capture(out / "containers", f"{safe}.inspect.json", [rt, "inspect", name])
        capture(
            out / "containers",
            f"{safe}.resolv-conf.txt",
            [rt, "exec", name, "cat", "/etc/resolv.conf"],
            timeout=_PROBE_TIMEOUT,
        )
        capture(
            out / "containers",
            f"{safe}.systemctl.txt",
            [rt, "exec", name, "systemctl", "status", "--all", "--no-pager"],
            timeout=_PROBE_TIMEOUT,
        )
        capture(
            out / "containers",
            f"{safe}.journal.txt",
            [rt, "exec", name, "journalctl", "-b", "--no-pager"],
        )
        if "postgres" in name:
            capture(
                out / "containers",
                f"{safe}.pg_stat_activity.txt",
                [
                    rt,
                    "exec",
                    name,
                    "psql",
                    "-U",
                    "postgres",
                    "-c",
                    "SELECT pid, usename, datname, state, wait_event_type, backend_start, query_start, left(query, 120) AS query FROM pg_stat_activity ORDER BY backend_start;",
                ],
            )
    capture(out, "services.txt", [rt, "service", "ls"])
    services = list_lines([rt, "service", "ls", "--format", "{{.Name}}"])
    for svc in services:
        safe = sanitize(svc)
        capture(
            out / "services", f"{safe}.ps.txt", [rt, "service", "ps", "--no-trunc", svc]
        )
        capture(
            out / "services",
            f"{safe}.log",
            [rt, "service", "logs", "--no-task-ids", svc],
        )
    return containers, services


def _container_can_recurse(rt: str, name: str) -> bool:
    probe = run(
        [
            rt,
            "exec",
            name,
            "sh",
            "-c",
            "command -v python3 >/dev/null 2>&1 && { command -v docker >/dev/null 2>&1 || command -v container >/dev/null 2>&1; }",
        ]
    )
    return probe.returncode == 0


def recurse(
    out: Path,
    rt: str,
    app_id: str,
    context: str,
    depth: int,
    seen: list[str],
    stamp: str,
) -> int:
    self_path = Path(__file__).resolve()
    if not self_path.is_file():
        return 0
    nested_n = 0
    nested_out = f"/tmp/rescue-nested-{stamp}-{os.getpid()}"  # noqa: S108 - staging dir inside the inspected container, removed after the tar pull
    for name in list_lines([rt, "ps", "--format", "{{.Names}}"]):
        cid = "".join(list_lines([rt, "inspect", "--format", "{{.Id}}", name]))
        if not cid or cid in seen:
            continue
        if not _container_can_recurse(rt, name):
            continue
        copied = run(
            [rt, "exec", "-i", name, "sh", "-c", f"cat > {_SELF_IN_CONTAINER}"],
            stdin=self_path.read_bytes(),  # nocheck: cache-read - one-shot self-copy into the container; binary-safe and never re-read
        )
        if copied.returncode != 0:
            continue
        run(
            [
                rt,
                "exec",
                "-e",
                f"INFINITO_RESCUE_DIAGNOSTICS_DIR={nested_out}",
                "-e",
                f"RESCUE_DEPTH={depth + 1}",
                "-e",
                "RESCUE_SEEN=" + ",".join([*seen, cid] if cid else seen),
                "-e",
                f"{_LOCAL_DUMPS_ENV}={os.environ.get(_LOCAL_DUMPS_ENV, '')}",
                name,
                "python3",
                _SELF_IN_CONTAINER,
                app_id,
                f"nested in {name}" + (f"; {context}" if context else ""),
            ],
            timeout=_NESTED_TIMEOUT,
        )
        dest = out / "containers" / sanitize(name) / "nested"
        dest.mkdir(parents=True, exist_ok=True)
        tar = run(
            [rt, "exec", name, "tar", "-C", nested_out, "-cf", "-", "."],
            timeout=_TAR_TIMEOUT,
        )
        if tar.returncode == 0 and tar.stdout:
            run(
                ["tar", "-C", str(dest), "-xf", "-"],
                stdin=tar.stdout,
                timeout=_TAR_TIMEOUT,
            )
        run([rt, "exec", name, "rm", "-rf", nested_out, _SELF_IN_CONTAINER])
        nested_n += 1
    return nested_n


def main(argv: list[str]) -> int:
    app_id = argv[1] if len(argv) > 1 else "unknown"
    context = argv[2] if len(argv) > 2 else ""
    out_base = os.environ.get("INFINITO_RESCUE_DIAGNOSTICS_DIR")
    if not out_base:
        print(
            "INFINITO_RESCUE_DIAGNOSTICS_DIR not set (SPOT: group_vars/all/05_paths.yml)",
            file=sys.stderr,
        )
        return 1
    depth = int(os.environ.get("RESCUE_DEPTH", "0"))
    seen = [cid for cid in os.environ.get("RESCUE_SEEN", "").split(",") if cid]
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%SZ")
    out = Path(out_base) / f"{app_id}-{stamp}-{os.getpid()}"
    out.mkdir(parents=True, exist_ok=True)

    collect_host(out, app_id, context, stamp)
    collect_local_dumps(out)
    rt = runtime_bin()
    containers: list[str] = []
    services: list[str] = []
    nested_n = 0
    if rt:
        containers, services = collect_runtime(out, rt)
        nested_n = recurse(out, rt, app_id, context, depth, seen, stamp)

    print(
        f"🩺 Rescue diagnostics for '{app_id}'" + (f" ({context})" if context else "")
    )
    print(f"   snapshot: {out}")
    print(
        f"   captured: {len(containers)} container(s), {len(services)} service(s), "
        f"{nested_n} nested runtime(s) at depth {depth}, journal + host resources"
    )
    if not os.environ.get(_LOCAL_DUMPS_ENV):
        print(f"   {_LOCAL_DUMPS_ENV} unset: in-play role dumps were not collected")
    print("   full detail in the uploaded rescue-diagnostics artifact")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
