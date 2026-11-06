"""The vocabulary a package plan is written in.

A :class:`ModuleCall` is one Ansible module invocation, a
:class:`RetryPolicy` says how often it may be repeated. Both are plain
data, so a plan can be built and asserted without an Ansible connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATE_PRESENT = "present"
STATE_ABSENT = "absent"
STATES: tuple[str, ...] = (STATE_PRESENT, STATE_ABSENT)

GENERIC_PACKAGE = "ansible.builtin.package"
"""`ansible.builtin.package` ships as a documentation-only stub; its logic
lives in Ansible's action plugin. The action plugin here executes modules
directly, so it must swap this marker for the host's `ansible_facts.pkg_mgr`."""


@dataclass(frozen=True)
class RetryPolicy:
    """How often a module call may be repeated, and how long between tries.

    Args:
        attempts: total tries, including the first.
        seconds: pause between tries.
    """

    attempts: int
    seconds: int


EXTERNAL_FETCH = RetryPolicy(attempts=3, seconds=10)
"""Applies to every call that fetches over the network, the distribution's own
repositories included: their metadata is served by mirror pools that degrade
independently of the package manager's internal retries."""

AUR_FETCH = RetryPolicy(attempts=6, seconds=60)
"""The AUR is one origin host with no mirror pool behind it, so a flap there
lasts minutes rather than the seconds a pool member needs to rotate out;
EXTERNAL_FETCH's ~40s window has been observed losing to a single flap."""


@dataclass(frozen=True)
class ModuleCall:
    """One Ansible module invocation the action plugin should execute.

    Args:
        module: module name, or GENERIC_PACKAGE for the host's manager.
        args: module arguments; a None value is dropped before execution.
        become_user: user to escalate to, None for the connection default.
        retry: None when the call is run once, else its retry policy.
        pin: exact version of a GENERIC_PACKAGE call's one name, possibly a
            Jinja expression the action plugin renders; None installs any version.
    """

    module: str
    args: dict[str, Any] = field(default_factory=dict)
    become_user: str | None = None
    retry: RetryPolicy | None = None
    pin: str | None = None


PIN_FORMATS: dict[str, str] = {
    "apt": "{name}={version}",
    "dnf": "{name}-{version}",
    "dnf5": "{name}-{version}",
    "yum": "{name}-{version}",
}

DNF_MANAGERS: frozenset[str] = frozenset({"dnf", "dnf5", "yum"})

MANAGER_ARGS: dict[str, dict[str, Any]] = {"apt": {"install_recommends": False}}


def package_call(names: list[str], state: str) -> ModuleCall:
    """Install or remove *names* through the host's own package manager."""
    return ModuleCall(
        GENERIC_PACKAGE, {"name": names, "state": state}, retry=EXTERNAL_FETCH
    )


def manager_args(
    pkg_mgr: str,
    args: dict[str, Any],
    version: str | None,
    disable_excludes: str | None,
) -> dict[str, Any]:
    """Return a GENERIC_PACKAGE call's arguments for the host's package manager.

    The manager's fixed arguments (``MANAGER_ARGS``) always apply. An exact
    version overrides the role's own hold (apt) for that one install; on the
    dnf family, ``disable_excludes`` lifts the given repository's excludes only.

    Args:
        pkg_mgr: the host's ``ansible_facts.pkg_mgr``.
        args: the call's arguments, with ``name`` as a list.
        version: rendered exact version, None for any version.
        disable_excludes: repository id whose excludes the install may lift.

    Raises:
        ValueError: a version is pinned on a manager without a pin format.
    """
    result = {**args, **MANAGER_ARGS.get(pkg_mgr, {})}
    if version is not None:
        if pkg_mgr not in PIN_FORMATS:
            raise ValueError(f"package manager '{pkg_mgr}' cannot pin an exact version")
        result["name"] = [
            PIN_FORMATS[pkg_mgr].format(name=name, version=version)
            for name in args["name"]
        ]
        if pkg_mgr == "apt":
            result["allow_change_held_packages"] = True
    if disable_excludes and pkg_mgr in DNF_MANAGERS:
        result["disable_excludes"] = disable_excludes
    return result
