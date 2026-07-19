#!/usr/bin/env python3
"""SPOT rescue diagnostics, called ONLY by the CI workflows on failure (never
from Ansible ``rescue:`` blocks; the lint forbids those).

Captures a full failure snapshot on the current level (all containers with
their logs and inspect, all swarm services with ps and logs, the systemd
journal, host resources), then RECURSES: it copies itself into every running
container that carries python3 and a container runtime (DiD) and repeats the
capture there, pulling each nested snapshot back under
``containers/<name>/nested/`` - from the outermost caller down to the deepest
runtime (bounded by ``RESCUE_MAX_DEPTH``, default 3).

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
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_EXEC_TIMEOUT = 120
_NESTED_TIMEOUT = 600
_TAR_TIMEOUT = 300
_SELF_IN_CONTAINER = "/tmp/rescue-self.py"  # noqa: S108 - fixed staging path inside the inspected container
_LOCAL_DUMPS_DIR = "/tmp/infinito-rescue-diagnostics"  # noqa: S108 - SPOT: group_vars/all/05_paths.yml DIR_RESCUE_DIAGNOSTICS, where in-play role dumps (pg_hba, xwiki) land


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
    except OSError:
        pass


def capture(
    out: Path, name: str, cmd: list[str], *, timeout: int = _EXEC_TIMEOUT
) -> None:
    result = run(cmd, timeout=timeout)
    write(out / name, result.stdout + result.stderr)


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
        ("free.txt", ["free", "-m"]),
        ("uptime.txt", ["uptime"]),
        ("journal.txt", ["journalctl", "-n", "10000", "--no-pager"]),
        (
            "journal-warnings.txt",
            ["journalctl", "-b", "-p", "warning", "--since", "-6h", "--no-pager"],
        ),
        ("systemctl.txt", ["systemctl", "list-units", "--all", "--no-pager"]),
    ):
        capture(out, name, cmd)
    dmesg = run(["dmesg", "-T"]).stdout.decode(errors="replace")
    write(out / "dmesg.txt", dmesg.encode())
    oom = [
        line
        for line in dmesg.splitlines()
        if re.search(r"oom|kill|memory", line, re.IGNORECASE)
    ]
    write(out / "dmesg-oom.txt", "\n".join(oom).encode())


def collect_local_dumps(out: Path) -> None:
    """Copy the in-play role dumps next to the snapshot.

    ``out`` itself lives under the dump dir (both derive from
    INFINITO_RESCUE_DIAGNOSTICS_DIR), so the walk must skip its own
    output subtree or copytree recurses into the growing destination
    until ENAMETOOLONG."""
    src = Path(_LOCAL_DUMPS_DIR)
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


def collect_runtime(out: Path, rt: str) -> tuple[list[str], list[str]]:
    capture(out, "runtime.txt", [rt, "info"])
    capture(out, "stats.txt", [rt, "stats", "--no-stream", "--no-trunc"])
    capture(out, "containers.txt", [rt, "ps", "-a"])
    containers = list_lines([rt, "ps", "-a", "--format", "{{.Names}}"])
    for name in containers:
        safe = sanitize(name)
        capture(out / "containers", f"{safe}.log", [rt, "logs", name])
        capture(out / "containers", f"{safe}.inspect.json", [rt, "inspect", name])
        capture(
            out / "containers",
            f"{safe}.systemctl.txt",
            [rt, "exec", name, "systemctl", "status", "--all", "--no-pager"],
        )
        capture(
            out / "containers",
            f"{safe}.journal.txt",
            [rt, "exec", name, "journalctl", "-n", "1000", "--no-pager"],
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
            capture(
                out / "containers",
                f"{safe}.pg_connections.txt",
                [
                    rt,
                    "exec",
                    name,
                    "psql",
                    "-U",
                    "postgres",
                    "-c",
                    "SELECT usename, datname, state, count(*) FROM pg_stat_activity GROUP BY 1, 2, 3 ORDER BY 4 DESC;",
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
    max_depth: int,
    stamp: str,
) -> int:
    self_path = Path(__file__).resolve()
    if depth >= max_depth or not self_path.is_file():
        return 0
    nested_n = 0
    nested_out = f"/tmp/rescue-nested-{stamp}-{os.getpid()}"  # noqa: S108 - staging dir inside the inspected container, removed after the tar pull
    for name in list_lines([rt, "ps", "--format", "{{.Names}}"]):
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
                f"RESCUE_MAX_DEPTH={max_depth}",
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
    max_depth = int(os.environ.get("RESCUE_MAX_DEPTH", "3"))
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
        nested_n = recurse(out, rt, app_id, context, depth, max_depth, stamp)

    print(
        f"🩺 Rescue diagnostics for '{app_id}'" + (f" ({context})" if context else "")
    )
    print(f"   snapshot: {out}")
    print(
        f"   captured: {len(containers)} container(s), {len(services)} service(s), "
        f"{nested_n} nested runtime(s) at depth {depth}, journal + host resources"
    )
    print("   full detail in the uploaded rescue-diagnostics artifact")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
