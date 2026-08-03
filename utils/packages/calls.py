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
"""Applies to the calls that reach the AUR, COPR, a PPA or a source build."""


@dataclass(frozen=True)
class ModuleCall:
    """One Ansible module invocation the action plugin should execute.

    Args:
        module: module name, or GENERIC_PACKAGE for the host's manager.
        args: module arguments; a None value is dropped before execution.
        become_user: user to escalate to, None for the connection default.
        retry: None when the call is run once, else its retry policy.
    """

    module: str
    args: dict[str, Any] = field(default_factory=dict)
    become_user: str | None = None
    retry: RetryPolicy | None = None


def package_call(names: list[str], state: str) -> ModuleCall:
    """Install or remove *names* through the host's own package manager."""
    return ModuleCall(GENERIC_PACKAGE, {"name": names, "state": state})
