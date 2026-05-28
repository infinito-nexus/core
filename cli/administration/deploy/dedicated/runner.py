from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cli.administration.inventory.provision.services_disabler import (
    ServicesDisabledConflictError,
    assert_services_disabled_inventory_consistency_from_env,
)
from cli.meta.roles.services.called import verify as verify_required_system_services

from .proc import run, run_make


def run_ansible_playbook(
    *,
    repo_root: str,
    playbook_path: str,
    inventory_validator_path: str,
    inventory: str,
    modes: dict[str, Any],
    limit: str | None = None,
    allowed_applications: list[str] | None = None,
    password_file: str | None = None,
    verbose: int = 0,
    skip_build: bool = False,
    diff: bool = False,
    ansible_args: list[str] | None = None,
) -> None:
    """Run ansible-playbook with the given parameters and execution modes."""
    start_time = datetime.datetime.now(tz=datetime.UTC)
    print(f"\n▶️ Script started at: {start_time.isoformat()}\n")

    # ---------------------------------------------------------
    # 1) Cleanup Phase (wrapper-level)
    # ---------------------------------------------------------
    if modes.get("MODE_CLEANUP", False):
        print("\n🧹 Cleaning up...\n", flush=True)
        run_make(repo_root, "clean")
    else:
        print("\n🧹 Cleanup skipped (MODE_CLEANUP not set or False)\n")

    # ---------------------------------------------------------
    # 2) Build Phase
    # ---------------------------------------------------------
    if not skip_build:
        print("\n🛠️  Running project build (make setup)...\n")
        run_make(repo_root, "setup")
    else:
        print("\n🛠️  Build skipped (--skip-build)\n")

    # ---------------------------------------------------------
    # 3) `disable` env var consistency guard
    # ---------------------------------------------------------
    try:
        assert_services_disabled_inventory_consistency_from_env(
            inventory_dir=Path(inventory).resolve().parent,
            roles_dir=Path(repo_root).resolve() / "roles",
        )
    except ServicesDisabledConflictError as exc:
        print(f"\n[ERROR] {exc}\n", file=sys.stderr)
        sys.exit(1)

    # ---------------------------------------------------------
    # 4) Inventory Validation Phase
    # ---------------------------------------------------------
    if modes.get("MODE_ASSERT") is False:
        print("\n🔍 Inventory assertion explicitly disabled (MODE_ASSERT=false)\n")
    else:
        print("\n🔍 Validating inventory before deployment...\n")
        try:
            run(
                [sys.executable, inventory_validator_path, str(Path(inventory).parent)],
                cwd=repo_root,
                check=True,
            )
        except subprocess.CalledProcessError:
            print(
                "\n[ERROR] Inventory validation failed. Aborting deployment.\n",
                file=sys.stderr,
            )
            sys.exit(1)

    # ---------------------------------------------------------
    # 5) Build ansible-playbook command
    # ---------------------------------------------------------
    cmd: list[str] = ["ansible-playbook", "-i", inventory, playbook_path]

    if limit:
        cmd.extend(["-l", limit])

    # Wrapper-provided extra-vars first; user can override via passthrough -e later.
    if allowed_applications:
        joined = ",".join(allowed_applications)
        cmd.extend(["-e", f"APPLICATIONS_WHITELIST={joined}"])

    for key, value in modes.items():
        val = str(value).lower() if isinstance(value, bool) else str(value)
        cmd.extend(["-e", f"{key}={val}"])

    if password_file:
        cmd.extend(["--vault-password-file", password_file])

    if diff:
        cmd.append("--diff")

    if modes.get("MODE_DEBUG", False):
        verbose = max(verbose, 3)

    if verbose:
        cmd.append("-" + "v" * verbose)

    # Native ansible-playbook flags passthrough (must come last for override behavior)
    if ansible_args:
        cmd.extend(ansible_args)

    ansible_log_path = (
        os.environ.get("ANSIBLE_LOG_PATH") or "/tmp/infinito-deploy.log"  # noqa: S108
    )
    os.environ["ANSIBLE_LOG_PATH"] = ansible_log_path

    try:
        log_offset_before = Path(ansible_log_path).stat().st_size
    except OSError:
        log_offset_before = 0

    print("\n🚀 Launching Ansible Playbook...\n")
    result = subprocess.run(cmd, cwd=repo_root, check=False)

    if result.returncode != 0:
        print(
            f"\n[ERROR] ansible-playbook exited with status {result.returncode}\n",
            file=sys.stderr,
        )
        sys.exit(result.returncode)

    if allowed_applications:
        ok, missing = verify_required_system_services(
            roles_dir=Path(repo_root) / "roles",
            log_path=ansible_log_path,
            log_byte_offset=log_offset_before,
            deployed_role_ids=allowed_applications,
        )
        if not ok:
            print(
                f"\n[ERROR] required role(s) did not execute for deploy "
                f"{allowed_applications}:",
                file=sys.stderr,
            )
            for role in missing:
                print(f"          - {role}", file=sys.stderr)
            print(
                "        See `required_by` declarations in roles/*/meta/services.yml — "
                "the role(s) above must run on every deploy whose primaries match.",
                file=sys.stderr,
            )
            sys.exit(2)

    end_time = datetime.datetime.now(tz=datetime.UTC)
    print(f"\n✅ Script ended at: {end_time.isoformat()}\n")
    print(f"⏱️ Total execution time: {end_time - start_time}\n")
