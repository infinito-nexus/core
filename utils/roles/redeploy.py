"""The compose redeploy a diff needs for the role an iteration works on.

A path outside ``roles/<name>/`` that lies under ``tests/`` or is a Markdown
or reStructuredText file reaches no deploy and is left out, the skip rule of
``scripts/meta/resolve/diff/affected_roles.sh``. Of the rest, a file the
inventory bakes in takes a reinstall, because ``mode=update`` reuses the
inventory and would test the old include set. A diff that stays inside the
app role, outside its shared meta files, its ``test.env`` template and its
CLI test files, takes a role sync. Everything else takes ``mode=update``.

The iteration plan (``cli.meta.ci.iterate``) reads the rule from here. The
compose iteration routine (``agents.routines.iterate.compose``) still holds a
copy of it until the merge switches the routine to this module; the plan's
unit tests pin the two to the same answer meanwhile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_MCP,
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_META_RBAC,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_TESTS,
    ROLE_FILE_META_USERS,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_PLAYWRIGHT_SPEC,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

ROLE_SYNC = "role-sync"
UPDATE = "update"
REINSTALL = "reinstall"

TEST_ENV_TEMPLATE = "templates/test.env.j2"
INVENTORY_FILES = frozenset(
    {
        ROLE_FILE_META_VARIANTS,
        ROLE_FILE_META_SERVICES,
        ROLE_FILE_META_SECRETS,
        ROLE_FILE_META_USERS,
    }
)
OUTSIDE_SYNC_FILES = frozenset(
    {
        ROLE_FILE_META_MAIN,
        ROLE_FILE_META_INFO,
        ROLE_FILE_META_NETWORKS,
        ROLE_FILE_META_DOMAINS,
        ROLE_FILE_META_RBAC,
        ROLE_FILE_META_MCP,
        ROLE_FILE_META_TESTS,
        TEST_ENV_TEMPLATE,
    }
)
OUTSIDE_SYNC_DIRS = ("files/test/",)
NO_DEPLOY_PREFIXES = ("tests/",)
NO_DEPLOY_SUFFIXES = (".md", ".rst")
SPEC_DIRS = (ROLE_FILE_PLAYWRIGHT_SPEC.rpartition("/")[0] + "/",)


def role_file(path: str) -> tuple[str, str] | None:
    """Return ``(role, path below the role)`` for a role path, else None.

    Args:
        path: repository-relative POSIX path.
    """
    parts = path.split("/", 2)
    if len(parts) == 3 and parts[0] == "roles" and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None


def compose_redeploy(role: str, paths: Iterable[str]) -> str:
    """Return :data:`REINSTALL`, :data:`ROLE_SYNC` or :data:`UPDATE`.

    Args:
        role: the application id the redeploy targets; empty takes
            ``mode=update`` unless an inventory file changed.
        paths: the changed paths that reach a deploy.
    """
    deployed = [
        path
        for path in paths
        if role_file(path)
        or not (
            path.startswith(NO_DEPLOY_PREFIXES) or path.endswith(NO_DEPLOY_SUFFIXES)
        )
    ]
    located = [role_file(path) for path in deployed]
    if any(found and found[1] in INVENTORY_FILES for found in located):
        return REINSTALL
    if not role or not deployed:
        return UPDATE
    for found in located:
        if (
            found is None
            or found[0] != role
            or found[1] in OUTSIDE_SYNC_FILES
            or found[1].startswith(OUTSIDE_SYNC_DIRS)
        ):
            return UPDATE
    return ROLE_SYNC


def spec_only(paths: Iterable[str]) -> bool:
    """Return True when every path sits in a role's Playwright spec folder,
    which ``make compose-playwright`` reruns against the running stack.

    Args:
        paths: the changed paths that reach a deploy.
    """
    located = [role_file(path) for path in paths]
    return bool(located) and all(
        found and found[1].startswith(SPEC_DIRS) for found in located
    )
