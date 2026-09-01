"""Rotate the credentials an inventory generated, so a redeploy has to carry them.

Provisioning fills a missing credential and leaves an existing one alone. That
keeps a redeploy stable, and it also means no deploy ever runs against a secret
that moved: every pass reads the value the first pass wrote. Dropping the
generated values and regenerating them between two deploy passes turns the
second pass into a test of the update path, where each role has to push its new
secret into the application and the database it already created.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.credentials.vault import is_ruamel_vault
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from .credentials_generator import generate_credentials_for_roles
from .ruamel_io import dump_document, load_document
from .users_generator import generate_user_passwords, required_user_policies

if TYPE_CHECKING:
    from pathlib import Path


ROTATABLE_KEY = "rotatable"


def _pinned_paths(
    schema: CommentedMap, prefix: tuple[str, ...]
) -> set[tuple[str, ...]]:
    """Return the credential paths ``schema`` marks ``rotatable: false``.

    Args:
        schema: a ``credentials`` branch of a role's ``meta/secrets.yml``.
        prefix: the path walked so far.

    Returns:
        The pinned paths, each as a tuple of keys.
    """
    pinned: set[tuple[str, ...]] = set()
    for key, meta in schema.items():
        if not isinstance(meta, CommentedMap):
            continue
        if meta.get(ROTATABLE_KEY) is False:
            pinned.add((*prefix, key))
        else:
            pinned |= _pinned_paths(meta, (*prefix, key))
    return pinned


def _pinned_credentials(roles_dir: Path) -> dict[str, set[tuple[str, ...]]]:
    """Map application id to the credentials its role refuses to have rotated.

    Args:
        roles_dir: directory the roles live in.

    Returns:
        Application id to the set of pinned credential paths.
    """
    pinned: dict[str, set[tuple[str, ...]]] = {}
    for role_dir in sorted(roles_dir.iterdir()):
        schema = load_document(role_dir / ROLE_FILE_META_SECRETS).get(CREDENTIALS_KEY)
        if not isinstance(schema, CommentedMap):
            continue
        paths = _pinned_paths(schema, ())
        if not paths:
            continue
        application_id = load_document(role_dir / ROLE_FILE_VARS_MAIN).get(
            "application_id"
        )
        if application_id:
            pinned[str(application_id)] = paths
    return pinned


def _drop_generated(
    node: CommentedMap, pinned: set[tuple[str, ...]], prefix: tuple[str, ...]
) -> int:
    """Remove every vault-encrypted leaf below ``node``.

    Args:
        node: a ``credentials`` branch of the inventory.
        pinned: paths the role marked ``rotatable: false``.
        prefix: the path walked so far.

    Returns:
        How many values were removed.

    A `plain` credential the operator supplies stays unencrypted in host_vars
    (an empty string while it was never set), so restricting the drop to
    vaulted leaves keeps operator input out of the rotation.
    """
    dropped = 0
    for key in list(node.keys()):
        path = (*prefix, key)
        if path in pinned:
            print(
                f"[WARN] not rotated, pinned as rotatable: false: {'.'.join(path)}",
                file=sys.stderr,
            )
            continue
        value = node.get(key)
        if isinstance(value, CommentedMap):
            dropped += _drop_generated(value, pinned, path)
        elif is_ruamel_vault(value):
            del node[key]
            dropped += 1
    return dropped


def _drop_app_credentials(
    document: CommentedMap,
    exclude: set[str],
    pinned: dict[str, set[tuple[str, ...]]],
) -> int:
    """Remove the generated credentials of every application in ``document``.

    Args:
        document: the host_vars document.
        exclude: application ids to leave untouched.
        pinned: per-application credential paths that must survive a rotation.

    Returns:
        How many values were removed.
    """
    applications = document.get("applications")
    if not isinstance(applications, CommentedMap):
        return 0

    dropped = 0
    for application_id, application in applications.items():
        if application_id in exclude or not isinstance(application, CommentedMap):
            continue
        secrets = application.get(SECRETS_KEY)
        if not isinstance(secrets, CommentedMap):
            continue
        credentials = secrets.get(CREDENTIALS_KEY)
        if isinstance(credentials, CommentedMap):
            dropped += _drop_generated(
                credentials, pinned.get(str(application_id), set()), ()
            )
    return dropped


def _drop_user_passwords(
    document: CommentedMap,
    roles_dir: Path,
    application_ids: list[str],
    exclude: set[str],
) -> int:
    """Remove the pinned password of every user the resolved roles declare.

    Args:
        document: the host_vars document.
        roles_dir: directory the roles live in.
        application_ids: the roles resolved into this inventory.
        exclude: user keys to leave untouched.

    Returns:
        How many passwords were removed.

    Only declared users are dropped, because only those get a new password
    pinned afterwards; a user that exists solely in the inventory would lose
    its password with nothing to put it back.
    """
    users = document.get("users")
    if not isinstance(users, CommentedMap):
        return 0

    dropped = 0
    for username in required_user_policies(roles_dir, application_ids):
        if username in exclude:
            continue
        user = users.get(username)
        if isinstance(user, CommentedMap) and user.pop("password", None) is not None:
            dropped += 1
    return dropped


def reset_credentials(
    application_ids: list[str],
    roles_dir: Path,
    host_vars_file: Path,
    vault_password_file: Path,
    project_root: Path,
    env: dict[str, str] | None,
    schema: bool,
    users: bool,
    exclude: set[str],
    workers: int = 4,
    app_variants: dict[str, int] | None = None,
) -> int:
    """Replace every generated credential in ``host_vars_file`` with a fresh one.

    Args:
        application_ids: the roles resolved into this inventory.
        roles_dir: directory the roles live in.
        host_vars_file: inventory file the credentials are rewritten in.
        vault_password_file: vault password used to encrypt each value.
        project_root: repository root the role resolver works from.
        env: environment the credential subprocesses inherit.
        schema: rotate ``applications.<app>.credentials.*``.
        users: rotate ``users.<name>.password``.
        exclude: application ids and user keys to leave untouched.
        workers: worker threads for credentials generation.
        app_variants: variant index per app, as at provision time.

    Returns:
        How many values were rotated.
    """
    if not schema and not users:
        raise SystemExit("reset_credentials: pick at least one of schema, users")

    document = load_document(host_vars_file)
    dropped = 0
    if schema:
        dropped += _drop_app_credentials(
            document, exclude, _pinned_credentials(roles_dir)
        )
    if users:
        dropped += _drop_user_passwords(document, roles_dir, application_ids, exclude)
    dump_document(host_vars_file, document)

    if schema:
        generate_credentials_for_roles(
            application_ids=application_ids,
            roles_dir=roles_dir,
            host_vars_file=host_vars_file,
            vault_password_file=vault_password_file,
            project_root=project_root,
            env=env,
            workers=workers,
            app_variants=app_variants,
        )
    if users:
        generate_user_passwords(
            roles_dir=roles_dir,
            application_ids=application_ids,
            host_vars_file=host_vars_file,
            vault_password_file=vault_password_file,
        )
    return dropped
