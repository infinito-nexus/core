"""Install plans for the package registry.

Turns a resolved :class:`~utils.packages.registry.PackageSpec` into the
ordered module calls that acquire it. Keeping this pure means every
acquisition path - distribution repository, AUR, COPR, PPA, source build -
is unit-testable without an Ansible connection; the action plugin only
executes what it is handed.
"""

from __future__ import annotations

from utils.packages.calls import (
    STATE_ABSENT,
    STATE_PRESENT,
    ModuleCall,
    package_call,
)
from utils.packages.schema import (
    SOURCE_AUR,
    SOURCE_BUILD,
    SOURCE_COPR,
    SOURCE_PPA,
    PackageSpec,
)
from utils.packages.sources import aur_calls, build_calls, repository_calls


def build_plan(spec: PackageSpec, state: str) -> list[ModuleCall]:
    """Return the ordered module calls that bring ``spec`` into ``state``."""
    names = list(spec.names)
    if not names:
        return []

    if state == STATE_ABSENT:
        return [package_call(names, STATE_ABSENT)]

    if spec.source == SOURCE_AUR:
        return aur_calls(names)

    if spec.source == SOURCE_BUILD:
        if not spec.build:
            raise ValueError("source 'build' requires a 'build' block")
        return build_calls(spec.build)

    if spec.source in (SOURCE_COPR, SOURCE_PPA) and not spec.repo:
        raise ValueError(f"source '{spec.source}' requires a 'repo' block")

    if spec.repo:
        return repository_calls(spec.repo, names)
    return [package_call(names, STATE_PRESENT)]
