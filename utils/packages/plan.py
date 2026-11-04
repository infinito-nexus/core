"""Install plans for the package registry.

Turns a resolved :class:`~utils.packages.registry.PackageSpec` into the
ordered module calls that acquire it. Keeping this pure means every
acquisition path - distribution repository, AUR, COPR, PPA, source build,
pinned vendor download, Flatpak remote - is unit-testable without an Ansible connection; the action
plugin only executes what it is handed.
"""

from __future__ import annotations

from dataclasses import replace

from utils.packages.calls import (
    GENERIC_PACKAGE,
    STATE_ABSENT,
    STATE_PRESENT,
    ModuleCall,
    package_call,
)
from utils.packages.schema import (
    SOURCE_AUR,
    SOURCE_BUILD,
    SOURCE_COPR,
    SOURCE_DOWNLOAD,
    SOURCE_FLATPAK,
    SOURCE_PPA,
    PackageSpec,
)
from utils.packages.sources import (
    aur_calls,
    build_calls,
    download_calls,
    flatpak_calls,
    repository_calls,
)


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

    if spec.source == SOURCE_DOWNLOAD:
        if not spec.download:
            raise ValueError("source 'download' requires a 'download' block")
        return download_calls(names, spec.download)

    if spec.source == SOURCE_FLATPAK:
        return flatpak_calls(names, spec.flatpak)

    if spec.source in (SOURCE_COPR, SOURCE_PPA) and not spec.repo:
        raise ValueError(f"source '{spec.source}' requires a 'repo' block")

    if spec.repo:
        return repository_calls(spec.repo, names)
    return [package_call(names, STATE_PRESENT)]


def _plain(plan: list[ModuleCall]) -> bool:
    if not plan or any(
        call.module != GENERIC_PACKAGE
        or call.become_user is not None
        or set(call.args) != {"name", "state"}
        for call in plan
    ):
        return False
    return len({call.args["state"] for call in plan}) == 1


def merge_plans(plans: list[list[ModuleCall]]) -> list[list[ModuleCall]]:
    """Fold the plans that only call the host's package manager into one plan.

    The plain plans are aligned on their last call, so the n-th call from
    the end of every plan lands in the same merged call and each plan's own
    order survives: a bootstrap package still installs before the names it
    unlocks. Every other plan follows unchanged, in request order.

    Args:
        plans: one plan per package id, in request order.

    Returns:
        one merged plan per state the plain plans bring their names into,
        then every other plan.
    """
    groups: dict[str, list[list[ModuleCall]]] = {}
    for plan in plans:
        if _plain(plan):
            groups.setdefault(plan[-1].args["state"], []).append(plan)
    return [_merge(group) for group in groups.values()] + [
        plan for plan in plans if not _plain(plan)
    ]


def _merge(plain: list[list[ModuleCall]]) -> list[ModuleCall]:
    merged: list[ModuleCall] = []
    for offset in range(max(len(plan) for plan in plain), 0, -1):
        calls = [plan[-offset] for plan in plain if len(plan) >= offset]
        names = list(
            dict.fromkeys(name for call in calls for name in call.args["name"])
        )
        merged.append(replace(calls[0], args={**calls[0].args, "name": names}))
    return merged
