"""Keep the gateway role out of a host that uses another host's gateway.

A host whose ``svc-ai-litellm`` names a gateway host in
``services.litellm.gateway_host`` reaches that gateway over the mesh and runs
none of its own. Provisioning it like any other host would put
``svc-ai-litellm`` into its inventory and mint a master key nothing uses, so
the role is dropped before credentials are generated.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from cli.administration.inventory.gateway.plan import APPLICATION_ID, gateway_of
from cli.administration.inventory.ruamel_io import load_document
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from pathlib import Path


def _applications(document: Any) -> Any:
    return document.get("applications") if isinstance(document, dict) else None


def named_gateway_host(
    host_vars_file: Path, vars_json: str | None, vars_file: Path | None
) -> str:
    """The gateway host this provisioning run leaves the host pointing at.

    Args:
        host_vars_file: the host's existing host_vars, if any.
        vars_json: the ``--vars`` override, applied after the file.
        vars_file: the ``--vars-file`` override, applied before ``--vars``.
    """
    named = gateway_of(_applications(load_document(host_vars_file)))
    if vars_file is not None and vars_file.exists():
        override = gateway_of(
            _applications(load_yaml_any(str(vars_file), default_if_missing={}))
        )
        named = override or named
    if vars_json:
        try:
            overrides = json.loads(vars_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON passed to --vars: {exc}") from exc
        named = gateway_of(_applications(overrides)) or named
    return named


def drop_gateway_role(inventory: dict[str, Any]) -> bool:
    """Remove ``svc-ai-litellm`` from an inventory's groups.

    Args:
        inventory: an ``all.children`` inventory mapping, changed in place.

    Returns:
        Whether the group was present.
    """
    children = (inventory.get("all") or {}).get("children") or {}
    if APPLICATION_ID not in children:
        return False
    del children[APPLICATION_ID]
    return True
