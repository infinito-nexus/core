from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import PROJECT_ROOT

DEFAULT_OUTPUT = str(Path(tempfile.gettempdir()) / "infinito-runner-deploy.log")
DEFAULT_RUNNER_COUNT: int | None = None
RUNNER_ROLE = "svc-runner"


def _normalize_roles(raw_roles: list[str]) -> list[str]:
    result: list[str] = []
    for item in raw_roles:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        result.extend(parts)
    seen: set[str] = set()
    unique: list[str] = []
    for role in result:
        if role not in seen:
            seen.add(role)
            unique.append(role)
    return unique


def _prepend_runner_role(roles: list[str]) -> list[str]:
    filtered = [r for r in roles if r != RUNNER_ROLE]
    return [RUNNER_ROLE, *filtered]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinito deploy runner",
        description=(
            "Deploy an Infinito.Nexus GitHub Actions self-hosted CI runner to a dedicated server.\n\n"
            "The svc-runner role is always prepended automatically; additional roles\n"
            "passed via --roles are deployed on top of it in the order given."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "hostname",
        help="Target server hostname or IP address that will host the runner.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSH port for the target host (default: Ansible default, typically 22).",
    )
    parser.add_argument(
        "--roles",
        required=True,
        nargs="+",
        dest="roles",
        help=(
            "Roles to deploy onto the runner (space- or comma-separated). "
            "svc-runner is always prepended automatically."
        ),
    )
    parser.add_argument(
        "--distribution",
        required=True,
        help=(
            "Target OS distribution of the runner (e.g. debian, archlinux). "
            "Selects distro-specific installation tasks inside svc-runner."
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=(
            f"File path the deploy stdout/stderr stream is written to "
            f"(default: {DEFAULT_OUTPUT})."
        ),
    )
    parser.add_argument(
        "--runner-count",
        type=int,
        default=None,
        dest="runner_count",
        metavar="N",
        help=(
            "Number of parallel runner instances to provision on the target host "
            "(default: auto-computed from server vCPUs by the role). "
            "Each instance handles one CI job at a time."
        ),
    )
    parser.add_argument(
        "--owner",
        default=None,
        help=(
            "GitHub repository owner the runner registers with "
            "(default: role default 'infinito-nexus'). "
            "Override to your GitHub username when deploying for a fork."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "GitHub repository name the runner registers with "
            "(default: role default 'core'). "
            "Override when deploying for a different repository."
        ),
    )

    return parser


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _build_inventory(hostname: str, port: int | None) -> str:
    host_line = hostname
    if hostname in _LOCAL_HOSTS:
        host_line += (
            f" ansible_connection=local ansible_python_interpreter={sys.executable}"
        )
    elif port is not None:
        host_line += f" ansible_port={port}"
    return f"[runners]\n{host_line}\n"


def _build_playbook(roles: list[str]) -> str:
    role_entries = "\n".join(f"    - {r}" for r in roles)
    return f"---\n- hosts: runners\n  become: true\n  roles:\n{role_entries}\n"


def _run_deploy(
    *,
    hostname: str,
    port: int | None,
    roles: list[str],
    distribution: str,
    output_file: str,
    runner_count: int,
    owner: str | None,
    repo: str | None,
) -> int:
    inventory_content = _build_inventory(hostname, port)
    playbook_content = _build_playbook(roles)

    inv_fd, inv_path = tempfile.mkstemp(
        suffix=".ini", prefix="infinito-runner-inv-", dir=str(PROJECT_ROOT)
    )
    pb_fd, pb_path = tempfile.mkstemp(
        suffix=".yml", prefix="infinito-runner-pb-", dir=str(PROJECT_ROOT)
    )

    try:
        with os.fdopen(inv_fd, "w") as f:
            f.write(inventory_content)
        with os.fdopen(pb_fd, "w") as f:
            f.write(playbook_content)

        cmd = [
            "ansible-playbook",
            "-i",
            inv_path,
            pb_path,
            "-e",
            f"RUNNER_DISTRIBUTION={distribution}",
            "-e",
            "MASK_CREDENTIALS_IN_LOGS=true",
        ]
        if runner_count is not None:
            cmd += ["-e", f"RUNNER_COUNT={runner_count}"]

        # Pass GitHub identity as extra-vars (direct override, not env-lookup).
        # vars/main.yml resolves RUNNER_GITHUB_OWNER/REPO via lookup('env', ...) which
        # can be unreliable across subprocess boundaries — direct -e is authoritative.
        if owner is not None:
            cmd += ["-e", f"RUNNER_GITHUB_OWNER={owner}"]
        if repo is not None:
            cmd += ["-e", f"RUNNER_GITHUB_REPO={repo}"]

        # Token via env (avoid leaking into process list).
        extra_env = dict(os.environ)
        token = os.environ.get("RUNNER_API_TOKEN") or os.environ.get("GH_TOKEN") or ""
        if token:
            extra_env["GH_TOKEN"] = token
            extra_env["RUNNER_API_TOKEN"] = token

        print(f"\n▶️  Deploying runner to {hostname} — output: {output_file}\n")

        with Path(output_file).open("w", encoding="utf-8") as out_f:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(PROJECT_ROOT),
                env=extra_env,
            )
            for line in proc.stdout:
                print(line, end="", flush=True)
                out_f.write(line)
            proc.wait()

        if proc.returncode != 0:
            print(
                f"\n[ERROR] Deploy failed with exit code {proc.returncode}\n",
                file=sys.stderr,
            )
        return proc.returncode

    finally:
        # Best-effort cleanup — temp files may already be gone if the OS cleaned up.
        with contextlib.suppress(OSError):
            Path(inv_path).unlink()
        with contextlib.suppress(OSError):
            Path(pb_path).unlink()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    roles = _normalize_roles(args.roles)
    roles = _prepend_runner_role(roles)

    return _run_deploy(
        hostname=args.hostname,
        port=args.port,
        roles=roles,
        distribution=args.distribution,
        output_file=args.output,
        runner_count=args.runner_count,
        owner=args.owner,
        repo=args.repo,
    )
