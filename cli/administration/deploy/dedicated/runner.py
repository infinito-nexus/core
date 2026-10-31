from __future__ import annotations

import datetime as dt
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from cli.administration.inventory.provision.services_disabler import (
    ServicesDisabledConflictError,
    assert_services_disabled_inventory_consistency_from_env,
)
from cli.meta.roles.services.called import verify as verify_required_system_services
from cli.meta.runtime import detect_runtime
from utils.cache.files import read_text

from .proc import run, run_make

_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def deploy_ansible_playbook(repo_root: str) -> str:
    """
    Return the ansible-playbook of the running interpreter once that
    interpreter carries every distribution of the `deploy` extra.

    Args:
      repo_root: checkout whose pyproject.toml declares the `deploy` extra
    Returns:
      absolute path of the ansible-playbook next to sys.executable
    Exits:
      1 when a `deploy` distribution or that ansible-playbook is missing
    """
    pyproject = tomllib.loads(read_text(str(Path(repo_root) / "pyproject.toml")))
    missing: list[str] = []
    for requirement in pyproject["project"]["optional-dependencies"]["deploy"]:
        name = _REQUIREMENT_NAME.match(requirement)
        try:
            importlib.metadata.distribution(name.group(0))
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement)

    ansible_playbook = Path(sys.executable).parent / "ansible-playbook"
    if missing:
        quoted = " ".join(f"'{requirement}'" for requirement in missing)
        print(
            f"\n[ERROR] The deploy interpreter {sys.executable} lacks "
            f"{', '.join(missing)} from the `deploy` extra of "
            f"{repo_root}/pyproject.toml.\n"
            f"        Install them with: {sys.executable} -m pip install {quoted}\n"
            "        or launch the CLI from the venv `make install` provisions.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    if not ansible_playbook.is_file():
        print(
            f"\n[ERROR] No ansible-playbook at {ansible_playbook} beside the "
            f"deploy interpreter {sys.executable}.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return str(ansible_playbook)


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
    start_time = dt.datetime.now(tz=dt.UTC)
    print(f"\n▶️ Script started at: {start_time.isoformat()}\n", flush=True)

    ansible_playbook = deploy_ansible_playbook(repo_root)

    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    if not skip_build:
        print("\n🛠️  Running project build (make setup)...\n", flush=True)
        run_make(repo_root, "setup")
    else:
        print("\n🛠️  Build skipped (--skip-build)\n", flush=True)

    try:
        assert_services_disabled_inventory_consistency_from_env(
            inventory_dir=Path(inventory).resolve().parent,
            roles_dir=Path(repo_root).resolve() / "roles",
        )
    except ServicesDisabledConflictError as exc:
        print(f"\n[ERROR] {exc}\n", file=sys.stderr)
        sys.exit(1)

    if modes.get("MODE_ASSERT") is False:
        print(
            "\n🔍 Inventory assertion explicitly disabled (MODE_ASSERT=false)\n",
            flush=True,
        )
    else:
        print("\n🔍 Validating inventory before deployment...\n", flush=True)
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

    cmd: list[str] = [ansible_playbook, "-i", inventory, playbook_path]

    if limit:
        cmd.extend(["-l", limit])

    if allowed_applications:
        joined = ",".join(allowed_applications)
        cmd.extend(["-e", f"APPLICATIONS_WHITELIST={joined}"])

    if modes:
        cmd.extend(["-e", json.dumps(modes)])

    if password_file:
        cmd.extend(["--vault-password-file", password_file])

    if diff:
        cmd.append("--diff")

    if modes.get("MODE_DEBUG", False):
        verbose = max(verbose, 3)

    if verbose:
        cmd.append("-" + "v" * verbose)

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

    print("\n🚀 Launching Ansible Playbook...\n", flush=True)
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
            runtime=detect_runtime(),
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

    end_time = dt.datetime.now(tz=dt.UTC)
    print(f"\n✅ Script ended at: {end_time.isoformat()}\n")
    print(f"⏱️ Total execution time: {end_time - start_time}\n")
