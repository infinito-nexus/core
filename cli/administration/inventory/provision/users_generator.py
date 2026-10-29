"""Pin a password on every user a deployment creates or authenticates.

A user definition that declares no password falls back to
``{{ 42 | strong_password }}``. That is a template, not a value: it is
re-rendered at every use site, so the task that creates an account and the
task that later authenticates as it read two different secrets. Inventory
creation is where the value gets decided once, next to the role credentials
that are already generated there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.cache.users import get_user_defaults
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_USERS

from .passwords import generate_declared_user_password
from .ruamel_io import dump_document, ensure_map, load_document, vault_value

if TYPE_CHECKING:
    from pathlib import Path

BOT_ROLE = "bot"


def _declarations(
    roles_dir: Path,
) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    """Return every role's declaration of every user, keyed by username.

    Args:
        roles_dir: directory the roles live in.
    """
    declarations: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for users_file in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_USERS}")):
        declared = load_yaml_any(users_file)
        if not isinstance(declared, dict):
            continue
        for username, overrides in declared.items():
            if not isinstance(overrides, dict):
                raise SystemExit(
                    f"Invalid definition for user {username!r} in {users_file}"
                )
            declarations.setdefault(str(username), []).append((users_file, overrides))
    return declarations


def _policy(
    username: str, declarations: list[tuple[Path, dict[str, Any]]]
) -> dict[str, str | None]:
    """Return the password policy the declarations of one user agree on.

    Args:
        username: the user the declarations belong to.
        declarations: every role's declaration of that user.

    Two roles sharing a user must agree on its policy: the account is one
    thing, so silently picking one declaration would hand the other role a
    password its application rejects. A declaration without a policy agrees
    with any.
    """
    policy: dict[str, str | None] = {"algorithm": None, "validation": None}
    source: Path | None = None
    for users_file, overrides in declarations:
        declared = overrides.get("password")
        if not isinstance(declared, dict):
            continue
        candidate = {
            "algorithm": declared.get("algorithm"),
            "validation": declared.get("validation"),
        }
        if not any(candidate.values()):
            continue
        if source is not None and candidate != policy:
            raise SystemExit(
                f"user {username!r} carries conflicting password policies: "
                f"{source} asks for {policy}, {users_file} for {candidate}"
            )
        policy, source = candidate, users_file
    return policy


def _provisioned_users(roles_dir: Path) -> set[str]:
    """Return every user that holds an account or is a bot, deployed role or not.

    Args:
        roles_dir: directory the roles live in.

    The directory and the mail providers iterate ``lookup('users')``, the
    catalogue of every role, so a bot whose declaring role this inventory never
    deploys still gets a mailbox and a submission token.
    """
    return {
        username
        for username, user in get_user_defaults(roles_dir=roles_dir).items()
        if user["accounts"] or BOT_ROLE in user["roles"]
    }


def required_user_policies(
    roles_dir: Path, application_ids: list[str]
) -> dict[str, dict[str, str | None]]:
    """Return every username the deployment needs pinned, with its policy.

    Args:
        roles_dir: directory the roles live in.
        application_ids: the roles resolved into this inventory.

    A user is needed when a resolved role declares it, or when it holds an
    account or is a bot and no role states its password outright.
    """
    resolved = {
        roles_dir / application_id / ROLE_FILE_META_USERS
        for application_id in application_ids
    }
    declarations = _declarations(roles_dir)
    policies = {
        username: _policy(username, declared)
        for username, declared in declarations.items()
    }
    provisioned = _provisioned_users(roles_dir)

    required: dict[str, dict[str, str | None]] = {}
    for username, declared in declarations.items():
        by_resolved_role = any(users_file in resolved for users_file, _ in declared)
        stated = any(
            isinstance(overrides.get("password"), str) for _, overrides in declared
        )
        if by_resolved_role or (username in provisioned and not stated):
            required[username] = policies[username]
    return dict(sorted(required.items()))


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
    policies = required_user_policies(roles_dir, application_ids)
    if not policies:
        return 0

    document = load_document(host_vars_file)
    users_doc = ensure_map(document, "users")

    generated = 0
    for username, policy in policies.items():
        user_doc = ensure_map(users_doc, username)
        if user_doc.get("password"):
            continue
        user_doc["password"] = vault_value(
            vault_password_file,
            generate_declared_user_password(
                username, policy["algorithm"], policy["validation"]
            ),
            f"{username}_password",
        )
        generated += 1

    if generated == 0:
        return 0

    dump_document(host_vars_file, document)
    return generated
