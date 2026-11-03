"""Shared Ansible-side assembly for the pre-flight lookup plugins.

Each of them checks the host against the roles the deploy may run on it, so
each needs the same three things: that role set, the merged applications the
set was derived from, and a reader for one role's rendered config. Building
them once keeps the lookups from drifting apart on which roles they check.

Args of :func:`deploy_closure_context` are documented on the function.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ansible.plugins.loader import lookup_loader

from utils import PROJECT_ROOT
from utils.roles.invocations import deploy_closure
from utils.roles.validation.invokable import types_from_group_names

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


@dataclass(frozen=True)
class DeployClosureContext:
    """The roles a pre-flight lookup checks and the readers it needs for them."""

    roles: list[str]
    applications: dict[str, Any]
    config: Callable[[str, str, Any], Any]
    lookup: Callable[..., Any]


def deploy_closure_context(
    lookup: Any, variables: dict[str, Any] | None, group_names: Iterable[Any]
) -> DeployClosureContext:
    """Assemble every role the deploy may run on the host.

    Args:
        lookup: the LookupModule instance, for its templar and loader.
        variables: the variables Ansible passed to ``run``.
        group_names: every group of the host, after the swarm auto-placement.

    Returns:
        The sorted roles of :func:`utils.roles.invocations.deploy_closure`, the
        merged applications, ``config(role, path, default)`` over the
        ``config`` lookup and ``lookup(name, *terms)`` over any other one.

    Raises:
        TypeError, ValueError: the closure cannot be derived.
    """
    groups = [str(group) for group in group_names]
    templar = getattr(lookup, "_templar", None)
    vars_ = variables or getattr(templar, "available_variables", {}) or {}

    def _lookup(name: str, *terms: Any) -> Any:
        return lookup_loader.get(name, loader=lookup._loader, templar=templar).run(
            list(terms), variables=vars_
        )[0]

    applications = _lookup("applications")
    roles = deploy_closure(
        applications,
        groups,
        project_root=PROJECT_ROOT,
        host_types=types_from_group_names(groups),
        group_names=groups,
    )
    return DeployClosureContext(
        roles=sorted(roles),
        applications=applications,
        config=lambda role, path, default: _lookup("config", role, path, default),
        lookup=_lookup,
    )
