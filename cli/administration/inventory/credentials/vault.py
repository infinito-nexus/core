"""Vault block construction and detection helpers."""

from __future__ import annotations

from typing import Any

from ruamel.yaml import YAML

from utils.handler.vault import VaultHandler, VaultScalar


def is_ruamel_vault(val: Any) -> bool:
    """Detect if a ruamel scalar already carries the !vault tag."""
    try:
        return getattr(val, "tag", None) == "!vault"
    except Exception:
        return False


def is_vault_encrypted(val: Any) -> bool:
    """Detect if a value is already a vault string, a ruamel !vault scalar,
    or an internal VaultScalar from InventoryManager.apply_schema()."""
    if isinstance(val, VaultScalar):
        return True
    if is_ruamel_vault(val):
        return True
    return bool(isinstance(val, str) and ("$ANSIBLE_VAULT" in val or "!vault" in val))


def _vault_body(text: str) -> str:
    """Return only the vault body starting from the first line containing
    ``$ANSIBLE_VAULT``. Strips any leading ``!vault |`` header if present."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "$ANSIBLE_VAULT" in ln:
            return "\n".join(lines[i:])
    return text


def _make_vault_scalar_from_text(text: str) -> Any:
    """Build a ruamel object representing a literal block scalar tagged
    with !vault by parsing a tiny YAML snippet. This avoids depending on
    yaml_set_tag()."""
    body = _vault_body(text)
    indented = "  " + body.replace("\n", "\n  ")
    snippet = f"v: !vault |\n{indented}\n"
    y = YAML(typ="rt")
    return y.load(snippet)["v"]


def to_vault_block(vault_handler: VaultHandler, value: str | Any, label: str) -> Any:
    """Return a ruamel scalar tagged as !vault. Reuses existing vault
    payloads (VaultScalar, ruamel !vault, ``$ANSIBLE_VAULT`` strings)
    and encrypts plaintext otherwise. Empty strings stay plain."""
    if isinstance(value, str) and value == "":
        return ""
    if is_ruamel_vault(value):
        return value
    if isinstance(value, VaultScalar):
        return _make_vault_scalar_from_text(str(value))
    if isinstance(value, str) and ("$ANSIBLE_VAULT" in value or "!vault" in value):
        return _make_vault_scalar_from_text(value)
    snippet = vault_handler.encrypt_string(str(value), label)
    return _make_vault_scalar_from_text(snippet)
