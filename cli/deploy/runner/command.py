from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

DEFAULT_OUTPUT = "/tmp/infinito-runner-deploy.log"
DEFAULT_RUNNER_COUNT = 15
RUNNER_ROLE = "svc-runner"


def _normalize_roles(raw_roles: List[str]) -> List[str]:
    """Normalize roles: accept space- and comma-separated values, deduplicate, preserve order."""
    result: List[str] = []
    for item in raw_roles:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        result.extend(parts)
    seen: set[str] = set()
    unique: List[str] = []
    for role in result:
        if role not in seen:
            seen.add(role)
            unique.append(role)
    return unique


def _prepend_runner_role(roles: List[str]) -> List[str]:
    """Ensure svc-runner is the first entry in the roles list."""
    filtered = [r for r in roles if r != RUNNER_ROLE]
    return [RUNNER_ROLE] + filtered


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
        default=DEFAULT_RUNNER_COUNT,
        dest="runner_count",
        metavar="N",
        help=(
            f"Number of parallel runner instances to provision on the target host "
            f"(default: {DEFAULT_RUNNER_COUNT}). Each instance handles one CI job at a time."
        ),
    )
    parser.add_argument(
        "--owner",
        default=None,
        help=(
            "GitHub repository owner the runner registers with "
            "(default: role default 'kevinveenbirkenbach'). "
            "Override to your GitHub username when deploying for a fork."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "GitHub repository name the runner registers with "
            "(default: role default 'infinito-nexus'). "
            "Override when deploying for a different repository."
        ),
    )

    return parser


def _build_inventory(hostname: str, port: Optional[int]) -> str:
    host_line = hostname
    if port is not None:
        host_line += f" ansible_port={port}"
    return f"[runners]\n{host_line}\n"


def _build_playbook(roles: List[str]) -> str:
    role_entries = "\n".join(f"    - {r}" for r in roles)
    return f"---\n- hosts: runners\n  become: true\n  roles:\n{role_entries}\n"


def _run_deploy(
    *,
    hostname: str,
    port: Optional[int],
    roles: List[str],
    distribution: str,
    output_file: str,
    runner_count: int,
    owner: Optional[str],
    repo: Optional[str],
) -> int:
    repo_root = Path(__file__).resolve().parents[3]

    inventory_content = _build_inventory(hostname, port)
    playbook_content = _build_playbook(roles)

    inv_fd, inv_path = tempfile.mkstemp(suffix=".ini", prefix="infinito-runner-inv-")
    pb_fd, pb_path = tempfile.mkstemp(suffix=".yml", prefix="infinito-runner-pb-")

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
            f"runner_distribution={distribution}",
            "-e",
            f"runner_count={runner_count}",
            "-e",
            "MASK_CREDENTIALS_IN_LOGS=true",
        ]
        if owner is not None:
            cmd += ["-e", f"runner_github_owner={owner}"]
        if repo is not None:
            cmd += ["-e", f"runner_github_repo={repo}"]

        print(f"\n▶️  Deploying runner to {hostname} — output: {output_file}\n")

        with open(output_file, "w", encoding="utf-8") as out_f:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(repo_root),
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
        with contextlib.suppress(OSError):
            os.unlink(inv_path)
        with contextlib.suppress(OSError):
            os.unlink(pb_path)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for `infinito deploy runner`."""
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
