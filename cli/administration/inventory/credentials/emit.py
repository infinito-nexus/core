"""Recursive credentials emission into a ruamel CommentedMap."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from .overrides import override_for
from .vault import is_vault_encrypted, to_vault_block

if TYPE_CHECKING:
    from utils.handler.vault import VaultHandler


def ensure_map(node: CommentedMap, key: str) -> CommentedMap:
    """Ensure ``node[key]`` exists and is a CommentedMap for round-trip
    safety. Overwrites non-CommentedMap placeholders."""
    if key not in node or not isinstance(node.get(key), CommentedMap):
        node[key] = CommentedMap()
    return node[key]


def emit_credentials(
    schema_node: dict,
    dest_node: CommentedMap,
    *,
    app_id: str,
    primary_app_id: str,
    key_path: str,
    overrides: dict[str, str],
    vault_handler: VaultHandler,
    skip_existing: bool,
    track_added: set[str] | None,
) -> None:
    """Walk a (possibly nested) credentials schema and emit one vault
    block per scalar leaf into ``dest_node``. Nested dicts (e.g.
    ``credentials.recaptcha = {key, secret}``) recurse into nested
    CommentedMaps so each leaf becomes its own vault-encrypted entry
    instead of being collapsed via ``str(dict)`` into a Python-repr
    blob (the regression that broke run 26428080957 jobs 77797371397
    and 77797371442 for web-app-espocrm and web-app-listmonk)."""
    is_primary = app_id == primary_app_id
    for key, default_val in schema_node.items():
        full_key = f"{key_path}.{key}" if key_path else key

        if isinstance(default_val, dict) and not is_vault_encrypted(default_val):
            sub = ensure_map(dest_node, key)
            emit_credentials(
                default_val,
                sub,
                app_id=app_id,
                primary_app_id=primary_app_id,
                key_path=full_key,
                overrides=overrides,
                vault_handler=vault_handler,
                skip_existing=skip_existing,
                track_added=track_added,
            )
            continue

        if skip_existing and key in dest_node:
            continue

        ov = override_for(app_id, full_key, overrides, is_primary=is_primary)
        value_for_key: str | Any = ov if ov is not None else default_val

        if is_vault_encrypted(value_for_key):
            dest_node[key] = to_vault_block(vault_handler, value_for_key, key)
        else:
            if value_for_key is None:
                value_for_key = ""
            dest_node[key] = to_vault_block(vault_handler, str(value_for_key), key)

        if track_added is not None:
            track_added.add(full_key)
