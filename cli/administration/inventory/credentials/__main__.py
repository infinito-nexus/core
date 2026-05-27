#!/usr/bin/env python3
"""Selectively add & vault NEW credentials in your inventory, preserving
comments and formatting. Existing values are left untouched unless
``--force`` is used.

Usage example::

    infinito administration inventory credentials \\
      --role-path roles/web-app-akaunting \\
      --inventory-file host_vars/echoserver.yml \\
      --vault-password-file .pass/echoserver.txt \\
      --set credentials.database_password=mysecret

Snippet mode (no file changes, YAML printed to stdout)::

    infinito administration inventory credentials \\
      --role-path roles/web-app-akaunting \\
      --inventory-file host_vars/echoserver.yml \\
      --vault-password-file .pass/echoserver.txt \\
      --snippet
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils.manager.inventory import InventoryManager

from .emit import emit_credentials, ensure_map
from .overrides import parse_overrides
from .prompts import ask_for_confirmation
from .vault import to_vault_block


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Selectively add & vault NEW credentials in your inventory, preserving comments/formatting."
    )
    parser.add_argument("--role-path", required=True, help="Path to your role")
    parser.add_argument(
        "--inventory-file", required=True, help="Host vars file to update"
    )
    parser.add_argument(
        "--vault-password-file", required=True, help="Vault password file"
    )
    parser.add_argument(
        "--set",
        nargs="*",
        default=[],
        help="Override values key[.subkey]=VALUE (applied to NEW keys; with --force also to existing)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow overrides to replace existing values (will ask per key unless combined with --yes)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Non-interactive: assume 'yes' for all overwrite confirmations when --force is used",
    )
    parser.add_argument(
        "--snippet",
        action="store_true",
        help=(
            "Do not modify the inventory file. Instead, print a YAML snippet with "
            "the generated credentials to stdout. The snippet contains only the "
            "applications/credentials blocks that would be generated (and ansible_become_password if provided)."
        ),
    )
    parser.add_argument(
        "--allow-empty-plain",
        action="store_true",
        help=(
            "Allow 'plain' credentials in the schema without an explicit --set override. "
            "Missing plain values will be set to an empty string before encryption."
        ),
    )
    parser.add_argument(
        "--variant",
        type=int,
        default=None,
        help=(
            "Variant index of the role to resolve. Affects shared-provider "
            "discovery (services.<key>.enabled+shared) so credentials are "
            "generated for the providers actually pulled in by the variant. "
            "If omitted, the role's base config is used (variants.yml overlay "
            "is not applied)."
        ),
    )
    args = parser.parse_args()

    overrides = parse_overrides(args.set)

    manager = InventoryManager(
        role_path=Path(args.role_path),
        inventory_path=Path(args.inventory_file),
        vault_pw=args.vault_password_file,
        overrides=overrides,
        allow_empty_plain=args.allow_empty_plain,
        variant=args.variant,
    )

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    schema_inventory: dict[str, Any] = manager.apply_schema()
    schema_apps = schema_inventory.get("applications", {}) or {}

    if args.snippet:
        return _run_snippet_mode(schema_apps, overrides, manager, yaml_rt)

    return _run_default_mode(schema_apps, overrides, manager, yaml_rt, args)


def _run_snippet_mode(
    schema_apps: dict,
    overrides: dict[str, str],
    manager: InventoryManager,
    yaml_rt: YAML,
) -> int:
    snippet_data = CommentedMap()
    apps_snip = ensure_map(snippet_data, "applications")

    for app_id, app_block in schema_apps.items():
        if not isinstance(app_block, dict):
            continue
        schema_creds = app_block.get("credentials", {})
        if not isinstance(schema_creds, dict) or not schema_creds:
            continue

        app_block_snip = ensure_map(apps_snip, app_id)
        creds_snip = ensure_map(app_block_snip, "credentials")
        emit_credentials(
            schema_creds,
            creds_snip,
            app_id=app_id,
            primary_app_id=manager.app_id,
            key_path="",
            overrides=overrides,
            vault_handler=manager.vault_handler,
            skip_existing=False,
            track_added=None,
        )

    if "ansible_become_password" in overrides:
        snippet_data["ansible_become_password"] = to_vault_block(
            manager.vault_handler,
            overrides["ansible_become_password"],
            "ansible_become_password",
        )

    yaml_rt.dump(snippet_data, sys.stdout)
    return 0


def _run_default_mode(
    schema_apps: dict,
    overrides: dict[str, str],
    manager: InventoryManager,
    yaml_rt: YAML,
    args: argparse.Namespace,
) -> int:
    with Path(args.inventory_file).open(encoding="utf-8") as f:
        data = yaml_rt.load(f)
    if data is None:
        data = CommentedMap()

    apps = ensure_map(data, "applications")
    newly_added_keys: dict[str, set[str]] = {}

    for app_id, app_block_schema in schema_apps.items():
        if not isinstance(app_block_schema, dict):
            continue
        schema_creds = app_block_schema.get("credentials", {})
        if not isinstance(schema_creds, dict) or not schema_creds:
            continue

        app_block = ensure_map(apps, app_id)
        creds = ensure_map(app_block, "credentials")
        added = newly_added_keys.setdefault(app_id, set())
        emit_credentials(
            schema_creds,
            creds,
            app_id=app_id,
            primary_app_id=manager.app_id,
            key_path="",
            overrides=overrides,
            vault_handler=manager.vault_handler,
            skip_existing=True,
            track_added=added,
        )

    if "ansible_become_password" not in data:
        val = overrides.get("ansible_become_password")
        if val is not None:
            data["ansible_become_password"] = to_vault_block(
                manager.vault_handler, val, "ansible_become_password"
            )
    elif args.force and "ansible_become_password" in overrides:
        do_overwrite = args.yes or ask_for_confirmation("ansible_become_password")
        if do_overwrite:
            data["ansible_become_password"] = to_vault_block(
                manager.vault_handler,
                overrides["ansible_become_password"],
                "ansible_become_password",
            )

    if args.force:
        _apply_force_overrides(apps, overrides, newly_added_keys, manager, args)

    with Path(args.inventory_file).open("w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)

    print(
        f"✅ Added new credentials without touching existing formatting/comments → {args.inventory_file}"
    )
    return 0


def _apply_force_overrides(
    apps: CommentedMap,
    overrides: dict[str, str],
    newly_added_keys: dict[str, set[str]],
    manager: InventoryManager,
    args: argparse.Namespace,
) -> None:
    """Apply ``--set`` overrides to keys that already existed in the
    inventory. Only fires under ``--force``; freshly-added keys are
    skipped because they were already populated from the same override."""
    for ov_key, ov_val in overrides.items():
        if ov_key.startswith("applications.") and ".credentials." in ov_key:
            rest = ov_key[len("applications.") :]
            app_id, tail = rest.split(".credentials.", 1)
            key = tail
        elif ".credentials." in ov_key:
            app_id, key = ov_key.split(".credentials.", 1)
        else:
            app_id = manager.app_id
            key = (
                ov_key.split(".", 1)[1] if ov_key.startswith("credentials.") else ov_key
            )

        if app_id not in apps:
            continue
        app_block = ensure_map(apps, app_id)
        creds = ensure_map(app_block, "credentials")

        if key in creds:
            if key in newly_added_keys.get(app_id, set()):
                continue
            if args.yes or ask_for_confirmation(f"{app_id}.credentials.{key}"):
                creds[key] = to_vault_block(manager.vault_handler, ov_val, key)


if __name__ == "__main__":
    sys.exit(main())
