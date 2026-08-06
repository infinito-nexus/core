"""Pin a password on every user the resolved role set needs.

A user definition that declares no password falls back to
``{{ 42 | strong_password }}``. That is a template, not a value: it is
re-rendered at every use site, so the task that creates an account and the
task that later authenticates as it read two different secrets. Inventory
creation is where the value gets decided once, next to the role credentials
that are already generated there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_USERS

from .passwords import generate_random_password
from .ruamel_io import dump_document, ensure_map, load_document, vault_value

if TYPE_CHECKING:
    from pathlib import Path


def required_usernames(roles_dir: Path, application_ids: list[str]) -> list[str]:
    """Return every username the given roles declare.

    Args:
        roles_dir: directory the roles live in.
        application_ids: the roles resolved into this inventory.

    A role that declares no users contributes none, so the result follows the
    deployment rather than everything the repository could ever deploy.
    """
    usernames: set[str] = set()
    for application_id in application_ids:
        users_file = roles_dir / application_id / ROLE_FILE_META_USERS
        if not users_file.exists():
            continue
        declared = load_yaml_any(users_file)
        if not isinstance(declared, dict):
            continue
        for username, overrides in declared.items():
            if not isinstance(overrides, dict):
                raise SystemExit(
                    f"Invalid definition for user {username!r} in {users_file}"
                )
            usernames.add(str(username))
    return sorted(usernames)


def generate_user_passwords(
    roles_dir: Path,
    application_ids: list[str],
    host_vars_file: Path,
    vault_password_file: Path,
) -> int:
    """Write a vaulted password for every required user that has none yet.

    Args:
        roles_dir: directory the roles live in.
        application_ids: the roles resolved into this inventory.
        host_vars_file: inventory file the passwords are written into.
        vault_password_file: vault password used to encrypt each value.

    Returns:
        How many users received a freshly generated password.
    """
    usernames = required_usernames(roles_dir, application_ids)
    if not usernames:
        return 0

    document = load_document(host_vars_file)
    users_doc = ensure_map(document, "users")

    generated = 0
    for username in usernames:
        user_doc = ensure_map(users_doc, username)
        if user_doc.get("password"):
            continue
        user_doc["password"] = vault_value(
            vault_password_file, generate_random_password(), f"{username}_password"
        )
        generated += 1

    if generated == 0:
        return 0

    dump_document(host_vars_file, document)
    return generated
