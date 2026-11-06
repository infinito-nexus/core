"""Relevant delta: whether the files changed since a loop's last run can change
that run's outcome for the roles under test. A rerun that runs the test suite
(``make test``, a workflow) reads every path. A rerun that only deploys leaves
out what no deploy reads (under ``tests/``, or a Markdown or reStructuredText
file outside ``roles/``), the skip rule of
``scripts/meta/resolve/diff/affected_roles.sh``; a path outside ``roles/``
reaches every role; a path in another role reaches the roles under test only
when the affected-roles resolver lists one of them.
"""

from __future__ import annotations

from agents.routines.tools.affected import matrix_size
from utils.roles.display import VARIANT_SEPARATOR

_NO_DEPLOY_PREFIXES = ("tests/",)
_NO_DEPLOY_SUFFIXES = (".md", ".rst")


def role_file(path: str) -> tuple[str, str] | None:
    """Return ``(role, path inside the role)`` for a path under
    ``roles/<role>/``, else ``None``.

    Args:
        path: a repository-relative path.
    """
    parts = path.split("/", 2)
    if len(parts) == 3 and parts[0] == "roles" and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None


def deployed_paths(paths: list[str]) -> list[str]:
    """Return the paths a deploy reads: every path under ``roles/<role>/`` and
    every other path that is neither under ``tests/`` nor a Markdown or
    reStructuredText file.

    Args:
        paths: repository-relative paths.
    """
    return [
        path
        for path in paths
        if role_file(path)
        or not (
            path.startswith(_NO_DEPLOY_PREFIXES) or path.endswith(_NO_DEPLOY_SUFFIXES)
        )
    ]


def role_ids(tokens: list[str]) -> set[str]:
    """Return the role ids of selection tokens, a ``#<variants>`` narrowing
    dropped.

    Args:
        tokens: role ids, each optionally narrowed (``web-app-x#0,2``).
    """
    return {
        token.split(VARIANT_SEPARATOR, 1)[0]
        for token in tokens
        if token.split(VARIANT_SEPARATOR, 1)[0]
    }


def relevant(
    roles: set[str], paths: list[str], resolver_output: str, runs_tests: bool
) -> bool:
    """Return whether ``paths`` can change the outcome of a rerun for
    ``roles``.

    Args:
        roles: the role ids under test; an empty set cannot be judged.
        paths: the repository-relative paths changed since the last run.
        resolver_output: the line ``python -m
            cli.meta.roles.applications.resolution.affected --changed-roles
            <roles>`` prints for the roles of ``paths``; ``""`` or ``__ALL__``
            counts as every role.
        runs_tests: the rerun runs the test suite, which reads every path.

    Returns:
        With ``runs_tests``, whether any path changed. Else ``False`` when no
        deployed path is left; ``True`` when ``roles`` is empty, when a
        deployed path lies outside ``roles/`` or under one of ``roles``, or
        when the resolver output is the full sentinel or lists one of
        ``roles``; else ``False``.
    """
    if runs_tests:
        return bool(paths)
    located = [role_file(path) for path in deployed_paths(paths)]
    if not located:
        return False
    if not roles:
        return True
    if any(found is None or found[0] in roles for found in located):
        return True
    if matrix_size(resolver_output) == -1:
        return True
    return bool(roles & role_ids(resolver_output.split()))
