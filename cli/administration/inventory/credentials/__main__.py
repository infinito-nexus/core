#!/usr/bin/env python3
"""
Selectively add & vault NEW credentials in your inventory, preserving comments
and formatting. Existing values are left untouched unless --force is used.

Usage example:
  infinito administration inventory credentials \
    --role-path roles/web-app-akaunting \
    --inventory-file host_vars/echoserver.yml \
    --vault-password-file .pass/echoserver.txt \
    --set credentials.database_password=mysecret

With snippet mode (no file changes, just YAML output):

  infinito administration inventory credentials \
    --role-path roles/web-app-akaunting \
    --inventory-file host_vars/echoserver.yml \
    --vault-password-file .pass/echoserver.txt \
    --snippet
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils.handler.vault import (
    VaultHandler,
    VaultScalar,
)  # uses your existing handler
from utils.manager.inventory import InventoryManager

# ---------- helpers ----------


def ask_for_confirmation(key: str) -> bool:
    """Prompt the user for confirmation to overwrite an existing value."""
    confirmation = (
        input(f"Are you sure you want to overwrite the value for '{key}'? (y/n): ")
        .strip()
        .lower()
    )
    return confirmation == "y"


def ensure_map(node: CommentedMap, key: str) -> CommentedMap:
    """
    Ensure node[key] exists and is a mapping (CommentedMap) for round-trip safety.
    """
    if key not in node or not isinstance(node.get(key), CommentedMap):
        node[key] = CommentedMap()
    return node[key]


def _is_ruamel_vault(val: Any) -> bool:
    """Detect if a ruamel scalar already carries the !vault tag."""
    try:
        return getattr(val, "tag", None) == "!vault"
    except Exception:
        return False


def _is_vault_encrypted(val: Any) -> bool:
    """
    Detect if value is already a vault string, a ruamel !vault scalar,
    or our internal VaultScalar (from InventoryManager.apply_schema()).
    """
    if isinstance(val, VaultScalar):
        return True
    if _is_ruamel_vault(val):
        return True
    return bool(isinstance(val, str) and ("$ANSIBLE_VAULT" in val or "!vault" in val))


def _vault_body(text: str) -> str:
    """
    Return only the vault body starting from the first line that contains
    '$ANSIBLE_VAULT'. If not found, return the original text.
    Also strips any leading '!vault |' header if present.
    """
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "$ANSIBLE_VAULT" in ln:
            return "\n".join(lines[i:])
    return text


def _make_vault_scalar_from_text(text: str) -> Any:
    """
    Build a ruamel object representing a literal block scalar tagged with !vault
    by parsing a tiny YAML snippet. This avoids depending on yaml_set_tag().
    """
    body = _vault_body(text)
    indented = "  " + body.replace("\n", "\n  ")  # proper block scalar indentation
    snippet = f"v: !vault |\n{indented}\n"
    y = YAML(typ="rt")
    return y.load(snippet)["v"]


def to_vault_block(vault_handler: VaultHandler, value: str | Any, label: str) -> Any:
    """
    Return a ruamel scalar tagged as !vault. If the input value is already
    vault-encrypted (string contains $ANSIBLE_VAULT, is a !vault scalar, or a VaultScalar),
    reuse/wrap. Otherwise, encrypt plaintext via ansible-vault.

    Special rule:
    - Empty strings ("") are NOT encrypted and are returned as plain "".
    """
    # Empty strings should not be encrypted
    if isinstance(value, str) and value == "":
        return ""

    # Already a ruamel !vault scalar → reuse
    if _is_ruamel_vault(value):
        return value

    # InventoryManager provides VaultScalar (vault body). Wrap it.
    if isinstance(value, VaultScalar):
        return _make_vault_scalar_from_text(str(value))

    # Already an encrypted string (may include '!vault |' or just the header)
    if isinstance(value, str) and ("$ANSIBLE_VAULT" in value or "!vault" in value):
        return _make_vault_scalar_from_text(value)

    # Plaintext → encrypt now
    snippet = vault_handler.encrypt_string(str(value), label)
    return _make_vault_scalar_from_text(snippet)


def parse_overrides(pairs: list[str]) -> dict[str, str]:
    """
    Parse --set key=value pairs into a dict.
    Supports both 'credentials.key=val' and 'key=val' (short) forms.
    """
    out: dict[str, str] = {}
    for pair in pairs:
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _override_for(
    app_id: str, key: str, overrides: dict[str, str], *, is_primary: bool
) -> str | None:
    """
    Resolve overrides for a credential key.

    Supported forms:
      - applications.<app_id>.credentials.<key>=...
      - <app_id>.credentials.<key>=...
    Backwards compatible (PRIMARY app only):
      - credentials.<key>=...
      - <key>=...
    """
    v = overrides.get(f"applications.{app_id}.credentials.{key}")
    if v is not None:
        return v
    v = overrides.get(f"{app_id}.credentials.{key}")
    if v is not None:
        return v
    if is_primary:
        v = overrides.get(f"credentials.{key}")
        if v is not None:
            return v
        v = overrides.get(key)
        if v is not None:
            return v
    return None


# ---------- main ----------


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

    # Initialize inventory manager (provides schema + app_id + vault)
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

    # Get schema-applied structure (includes shared-provider application blocks)
    schema_inventory: dict[str, Any] = manager.apply_schema()
    schema_apps = schema_inventory.get("applications", {}) or {}

    # -------------------------------------------------------------------------
    # SNIPPET MODE: only build a YAML fragment and print to stdout, no file I/O
    # -------------------------------------------------------------------------
    if args.snippet:
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

            for key, default_val in schema_creds.items():
                ov = _override_for(
                    app_id, key, overrides, is_primary=(app_id == manager.app_id)
                )

                if ov is not None:
                    value_for_key: str | Any = ov
                else:
                    value_for_key = default_val

                # Default rule: if schema provided vault, reuse; otherwise encrypt generated/plain
                if _is_vault_encrypted(value_for_key):
                    creds_snip[key] = to_vault_block(
                        manager.vault_handler, value_for_key, key
                    )
                else:
                    # if schema didn't provide a value, treat as empty string
                    if value_for_key is None:
                        value_for_key = ""
                    creds_snip[key] = to_vault_block(
                        manager.vault_handler, str(value_for_key), key
                    )

        # Optional ansible_become_password only if provided via overrides
        if "ansible_become_password" in overrides:
            snippet_data["ansible_become_password"] = to_vault_block(
                manager.vault_handler,
                overrides["ansible_become_password"],
                "ansible_become_password",
            )

        yaml_rt.dump(snippet_data, sys.stdout)
        return 0

    # -------------------------------------------------------------------------
    # DEFAULT MODE: modify the inventory file on disk (preserve formatting)
    # -------------------------------------------------------------------------

    # 1) Load existing inventory with ruamel (round-trip)
    with Path(args.inventory_file).open(encoding="utf-8") as f:
        data = yaml_rt.load(f)  # CommentedMap or None
    if data is None:
        data = CommentedMap()

    # 2) Ensure structural path exists
    apps = ensure_map(data, "applications")

    # 3) Add ONLY missing credential keys for ALL schema apps (primary + shared providers)
    newly_added_keys: dict[str, set[str]] = {}

    for app_id, app_block_schema in schema_apps.items():
        if not isinstance(app_block_schema, dict):
            continue
        schema_creds = app_block_schema.get("credentials", {})
        if not isinstance(schema_creds, dict) or not schema_creds:
            continue

        app_block = ensure_map(apps, app_id)
        creds = ensure_map(app_block, "credentials")

        newly_added_keys.setdefault(app_id, set())

        for key, default_val in schema_creds.items():
            if key in creds:
                continue

            ov = _override_for(
                app_id, key, overrides, is_primary=(app_id == manager.app_id)
            )
            value_for_new_key: str | Any

            value_for_new_key = ov if ov is not None else default_val

            if _is_vault_encrypted(value_for_new_key):
                creds[key] = to_vault_block(
                    manager.vault_handler, value_for_new_key, key
                )
            else:
                if value_for_new_key is None:
                    value_for_new_key = ""
                creds[key] = to_vault_block(
                    manager.vault_handler, str(value_for_new_key), key
                )

            newly_added_keys[app_id].add(key)

    # 4) ansible_become_password: only add if missing;
    #    never rewrite an existing one unless --force (+ confirm/--yes) and override provided.
    if "ansible_become_password" not in data:
        val = overrides.get("ansible_become_password", None)
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

    # 5) Overrides for existing credential keys (only with --force)
    if args.force:
        # Apply overrides only for keys that map to an existing application credential
        # (supports applications.<app>.credentials.<key> and <app>.credentials.<key>)
        for ov_key, ov_val in overrides.items():
            if ov_key.startswith("applications.") and ".credentials." in ov_key:
                # applications.<app>.credentials.<key>
                rest = ov_key[len("applications.") :]
                app_id, tail = rest.split(".credentials.", 1)
                key = tail
            elif ".credentials." in ov_key:
                # <app>.credentials.<key>
                app_id, key = ov_key.split(".credentials.", 1)
            else:
                # legacy: only apply to primary app
                app_id = manager.app_id
                key = (
                    ov_key.split(".", 1)[1]
                    if ov_key.startswith("credentials.")
                    else ov_key
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

    # 6) Write back with ruamel (preserve formatting & comments)
    with Path(args.inventory_file).open("w", encoding="utf-8") as f:
        yaml_rt.dump(data, f)

    print(
        f"✅ Added new credentials without touching existing formatting/comments → {args.inventory_file}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
