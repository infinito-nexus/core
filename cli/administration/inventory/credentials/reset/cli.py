"""Rotate the generated credentials of an inventory.

Usage example::

    infinito administration inventory credentials reset \\
      --inventory-dir /etc/inventories/local-full-server \\
      --schema --users --except administrator
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cli.administration.inventory.provision.project import (
    build_env_with_project_root,
    detect_project_root,
)
from cli.administration.inventory.provision.reset import reset_credentials
from cli.administration.inventory.provision.ruamel_io import load_document


def _parse_app_variants(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--app-variants must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--app-variants must be a JSON object")
    variants: dict[str, int] = {}
    for application_id, index in parsed.items():
        try:
            variants[str(application_id)] = int(index)
        except (TypeError, ValueError) as exc:
            raise SystemExit(
                f"--app-variants[{application_id!r}] must be an integer, got {index!r}"
            ) from exc
    return variants


def _backup(host_vars_file: Path) -> Path:
    """Copy ``host_vars_file`` next to itself, stamped with the current UTC time.

    Args:
        host_vars_file: the file about to be rewritten.

    Returns:
        The path of the copy.

    A rotation destroys the only record of what the previous pass deployed
    with, which is exactly what a post-mortem needs. The `.backup` suffix
    keeps the copy out of both the mirror glob and Ansible's host_vars
    loading, which only reads YAML extensions.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    copy = host_vars_file.with_name(f"{host_vars_file.name}.{stamp}.backup")
    shutil.copyfile(host_vars_file, copy)
    return copy


def _mirror_host_vars(host_vars_dir: Path, source: Path) -> list[str]:
    """Copy ``source`` over every other host_vars file in its directory.

    Args:
        host_vars_dir: the inventory's ``host_vars`` directory.
        source: the file the other hosts are aligned to.

    Returns:
        The host names that were overwritten.

    A multi-host test inventory holds one file per node, all copies of the
    manager's. Rotating only the manager's would hand every other node the
    previous secrets.
    """
    mirrored: list[str] = []
    for candidate in sorted(host_vars_dir.glob("*.yml")):
        if candidate == source:
            continue
        shutil.copyfile(source, candidate)
        mirrored.append(candidate.stem)
    return mirrored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drop the generated credentials of an inventory and regenerate them, "
            "so the next deploy has to propagate a changed secret."
        )
    )
    parser.add_argument(
        "--inventory-dir", required=True, help="Inventory directory to rotate."
    )
    parser.add_argument(
        "--host", default="localhost", help="Host whose host_vars file is rotated."
    )
    parser.add_argument(
        "--vault-password-file",
        default=None,
        help="Vault password file. Default: <inventory-dir>/.password",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Rotate applications.<app>.credentials.* (everything meta/schema.yml generates).",
    )
    parser.add_argument(
        "--users", action="store_true", help="Rotate users.<name>.password."
    )
    parser.add_argument(
        "--except",
        dest="exclude",
        nargs="*",
        default=[],
        help="Application ids and user keys to leave untouched (e.g. administrator).",
    )
    parser.add_argument(
        "--app-variants",
        default=None,
        help="JSON object {app_id: variant_index}, as passed to provision.",
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="Copy the rotated host_vars file over every other host in the inventory.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Keep the pre-rotation host_vars as <file>.YYYYMMDDTHHMMSSZ.backup.",
    )
    args = parser.parse_args(argv)

    if not args.schema and not args.users:
        raise SystemExit("Nothing to rotate: pass --schema, --users, or both.")

    inventory_dir = Path(args.inventory_dir).resolve()
    host_vars_file = inventory_dir / "host_vars" / f"{args.host}.yml"
    if not host_vars_file.exists():
        raise SystemExit(f"No host_vars file to rotate: {host_vars_file}")

    vault_password_file = (
        Path(args.vault_password_file).resolve()
        if args.vault_password_file
        else inventory_dir / ".password"
    )
    if not vault_password_file.exists():
        raise SystemExit(f"Vault password file not found: {vault_password_file}")

    project_root = detect_project_root(Path(__file__).resolve())
    env = build_env_with_project_root(project_root)

    document = load_document(host_vars_file)
    applications = document.get("applications") or {}
    application_ids = sorted(str(application_id) for application_id in applications)
    if not application_ids:
        raise SystemExit(f"No applications block to rotate in {host_vars_file}")

    if args.backup:
        print(f"[INFO] Pre-rotation copy: {_backup(host_vars_file)}")

    exclude = set(args.exclude)
    print(
        f"[INFO] Rotating credentials in {host_vars_file} "
        f"({len(application_ids)} applications, excluding {sorted(exclude) or 'nothing'})"
    )
    rotated = reset_credentials(
        application_ids=application_ids,
        roles_dir=(project_root / "roles").resolve(),
        host_vars_file=host_vars_file,
        vault_password_file=vault_password_file,
        project_root=project_root,
        env=env,
        schema=args.schema,
        users=args.users,
        exclude=exclude,
        app_variants=_parse_app_variants(args.app_variants),
    )
    print(f"[INFO] Rotated {rotated} value(s)")

    if args.mirror:
        mirrored = _mirror_host_vars(host_vars_file.parent, host_vars_file)
        print(f"[INFO] Mirrored to {', '.join(mirrored) or 'no other host'}")

    return 0
