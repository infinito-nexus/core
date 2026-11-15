"""Record the email policy of a new inventory in its host_vars.

A new inventory that deploys Keycloak, the mail provider and the directory gets
``applications.web-app-keycloak.services.keycloak.email.policy: mailbox``, so
its realm starts with mailbox addresses. An existing inventory is never
touched: its realm keeps the ``external`` default until an operator switches it.
An inventory rebuilt from scratch carries the policy and switch of the one it
replaces, since the realm it deploys against still holds that policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from cli.administration.inventory.ruamel_io import (
    dump_document,
    ensure_map,
    load_document,
)
from utils.cache.yaml import load_yaml_any
from utils.mail.policy import (
    POLICY_APPLICATION,
    POLICY_MAILBOX,
    POLICY_PATH,
    default_policy,
)
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

if TYPE_CHECKING:
    from pathlib import Path

CARRIED_KEYS = (POLICY_PATH[-1], "switch")


def inventory_is_new(*, inventory_file: Path, host_vars_dir: Path) -> bool:
    """Whether a provision run creates the inventory rather than extends one.

    Args:
        inventory_file: the inventory file the run writes, ``devices.yml`` by default.
        host_vars_dir: the inventory's ``host_vars`` directory.

    Returns:
        True only when neither the inventory file nor any host_vars file
        exists, since host_vars without an inventory file still belong to
        hosts whose realm holds a policy.
    """
    if inventory_file.exists():
        return False
    return not (host_vars_dir.is_dir() and any(host_vars_dir.iterdir()))


def _email_node(host_vars: Mapping[str, Any]) -> Mapping[str, Any]:
    node: Any = host_vars.get("applications")
    for key in (POLICY_APPLICATION, *POLICY_PATH[:-1]):
        if not isinstance(node, Mapping) or key not in node:
            return {}
        node = node[key]
    return node if isinstance(node, Mapping) else {}


def carry_email_policy(*, previous_host_vars_file: Path, host_vars_file: Path) -> bool:
    """Copy the email policy and switch of a replaced inventory into the new one.

    Args:
        previous_host_vars_file: host_vars of the inventory this run replaces.
        host_vars_file: host_vars of the provisioned host.

    Returns:
        True when a value was carried over.

    Raises:
        FileNotFoundError: ``previous_host_vars_file`` does not exist.
    """
    if not previous_host_vars_file.is_file():
        raise FileNotFoundError(
            f"previous host_vars {previous_host_vars_file} does not exist"
        )
    previous = _email_node(load_document(previous_host_vars_file))
    carried = {key: previous[key] for key in CARRIED_KEYS if key in previous}
    if not carried:
        return False
    document = load_document(host_vars_file)
    node = ensure_map(ensure_map(document, "applications"), POLICY_APPLICATION)
    for key in POLICY_PATH[:-1]:
        node = ensure_map(node, key)
    node.update(carried)
    dump_document(host_vars_file, document)
    return True


def _variant_sets_policy(roles_dir: Path, variant: int | None) -> bool:
    if variant is None:
        return False
    variants = load_yaml_any(
        str(roles_dir / POLICY_APPLICATION / ROLE_FILE_META_VARIANTS),
        default_if_missing=[],
    )
    node: Any = variants[variant] if variant < len(variants) else {}
    for key in POLICY_PATH:
        if not isinstance(node, Mapping) or key not in node:
            return False
        node = node[key]
    return True


def apply_email_policy(
    *,
    host_vars_file: Path,
    application_ids: list[str],
    host: str,
    roles_dir: Path,
    new_inventory: bool,
    keycloak_variant: int | None,
) -> bool:
    """Write the mailbox policy into the host_vars of a new inventory.

    Args:
        host_vars_file: host_vars file of the provisioned host.
        application_ids: applications the inventory deploys.
        host: the provisioned host.
        roles_dir: repository ``roles/`` directory.
        new_inventory: True when this run creates the inventory, see
            :func:`inventory_is_new`.
        keycloak_variant: variant index of web-app-keycloak, None for its base
            config; a variant that sets the policy keeps it, since the host_vars
            would override the variant.

    Returns:
        True when the policy was written.
    """
    if not new_inventory or _variant_sets_policy(roles_dir, keycloak_variant):
        return False
    variables = {"groups": {app: [host] for app in application_ids}}
    if default_policy(variables, roles_dir) != POLICY_MAILBOX:
        return False
    document = load_document(host_vars_file)
    node = ensure_map(ensure_map(document, "applications"), POLICY_APPLICATION)
    *parents, leaf = POLICY_PATH
    for key in parents:
        node = ensure_map(node, key)
    if leaf in node:
        return False
    node[leaf] = POLICY_MAILBOX
    dump_document(host_vars_file, document)
    return True
