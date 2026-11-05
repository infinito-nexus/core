"""Decide whether a deploy should prefer free storage space over cache.

The decision compares the free space on the filesystem holding Docker's data
root - where images, volumes and build cache grow - against the storage the
deploy actually declares it needs: the sum of ``min_storage`` over the services
of the applications being deployed, transitive dependencies included. No
threshold constant is involved, so the answer follows the declarations rather
than a guess about disk sizes.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.applications import get_variants, with_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.applications.services.resources import (
    aggregate,
    collect_role_resources,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DOCKER_INFO_TIMEOUT_S = 30


class StorageDeclarationError(ValueError):
    """A service sets min_storage to a value that does not parse as a size."""


def required_storage_bytes(
    app_ids: list[str], variants: dict[str, int] | None = None
) -> int:
    """Return the summed min_storage of app_ids and their transitive dependencies.

    Args:
        app_ids: applications the deploy installs; dependencies are walked.
        variants: per-app variant index whose `meta/variants.yml` overlay decides
            which services are enabled. Without it the base configuration counts,
            which over-states a deploy that a variant trims down.

    Services that declare no min_storage contribute nothing, so an entirely
    undeclared deploy yields 0 and is never treated as constrained.
    """
    roles_dir = PROJECT_ROOT / "roles"
    applications = load_applications_from_roles_dir(roles_dir)

    if variants:
        applications = with_variants(
            applications, get_variants(roles_dir=str(roles_dir)), variants
        )

    service_registry = build_service_registry_from_applications(applications)

    rows: list[dict] = []
    visited: set = set()
    for app_id in app_ids:
        collect_role_resources(
            role_name=app_id,
            applications=applications,
            service_registry=service_registry,
            visited=visited,
            rows=rows,
            warnings=[],
        )
    return aggregate(rows, ["min_storage"]).get("min_storage_bytes") or 0


def closure_storage(
    roles_dir: Path,
) -> Callable[[Iterable[str], dict[str, int]], dict[str, int]]:
    """Return a measure of the min_storage each role of a resolved closure declares.

    The roles tree is read once, so ranking hundreds of closures costs one load.

    Args:
        roles_dir: the roles tree the declarations are read from.

    Returns:
        ``measure(roles, variants)``. ``roles`` is a closure a resolver already
        settled, so no dependency is walked and a provider counts only when it
        is listed. ``variants`` is the round's per-app variant index, as in
        required_storage_bytes. The result maps each role to its declared
        bytes, 0 for a role that declares nothing or is no application.

    Raises:
        StorageDeclarationError: from ``measure``, when a service of a listed
            role sets min_storage to a value that does not parse; counting it
            as 0 would under-state the closure without a trace.
    """
    applications = load_applications_from_roles_dir(roles_dir)
    available = get_variants(roles_dir=str(roles_dir))
    service_registry = build_service_registry_from_applications(applications)

    def measure(roles: Iterable[str], variants: dict[str, int]) -> dict[str, int]:
        scoped = with_variants(applications, available, variants)
        declared: dict[str, int] = {}
        for role in roles:
            rows: list[dict] = []
            collect_role_resources(
                role_name=role,
                applications=scoped,
                service_registry=service_registry,
                visited=set(),
                rows=rows,
                warnings=[],
                max_depth=1,
            )
            unparsable = [
                f"{row['service']}={row['min_storage_raw']!r}"
                for row in rows
                if row["min_storage_raw"] is not None
                and row["min_storage_bytes"] is None
            ]
            if unparsable:
                raise StorageDeclarationError(
                    f"{role}: min_storage does not parse as a size: "
                    + ", ".join(unparsable)
                )
            declared[role] = (
                aggregate(rows, ["min_storage"]).get("min_storage_bytes") or 0
            )
        return declared

    return measure


def is_constrained(*, free_bytes: int, required_bytes: int) -> bool:
    """Return True when the declared need does not fit into the free space."""
    return required_bytes > free_bytes


def docker_data_root() -> str:
    """Return Docker's data root as reported by the local daemon.

    Raises:
        RuntimeError: the daemon is unreachable, answers no data root, or does
            not answer within DOCKER_INFO_TIMEOUT_S. Guessing a path here would
            silently measure the wrong filesystem and report a roomy host, which
            is the failure this module exists to prevent.
    """
    try:
        proc = subprocess.run(
            ["docker", "info", "-f", "{{.DockerRootDir}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=DOCKER_INFO_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "cannot determine Docker's data root: `docker info` did not answer "
            f"within {DOCKER_INFO_TIMEOUT_S}s"
        ) from exc
    root = (proc.stdout or "").strip()
    if proc.returncode != 0 or not root:
        raise RuntimeError(
            "cannot determine Docker's data root: "
            f"rc={proc.returncode} stderr={(proc.stderr or '').strip()!r}"
        )
    return root


def docker_root_free_bytes(*, local_vantage: str) -> int:
    """Return the free bytes on the filesystem where Docker's data grows.

    Args:
        local_vantage: a path in the caller's own mount namespace that sits on the
            same filesystem as the daemon's storage. Consulted only when the data
            root the daemon reports does not resolve here.
    """
    root = docker_data_root()
    if Path(root).is_dir():
        return shutil.disk_usage(root).free
    return shutil.disk_usage(local_vantage).free


def resolved_docker_root_free_bytes() -> int:
    """Return the free bytes on Docker's data root, measured where the daemon reports it.

    Raises:
        RuntimeError: as docker_data_root, or when the data root does not
            resolve in this mount namespace (a remote DOCKER_HOST, another
            context, Docker Desktop) or cannot be reached through its parents.
            Measuring a local filesystem instead would answer for a disk the
            deploy never writes to.
    """
    root = docker_data_root()
    try:
        return shutil.disk_usage(root).free
    except OSError as exc:
        raise RuntimeError(
            f"Docker's data root {root!r} cannot be measured here: {exc}"
        ) from exc


def host_storage_constrained(
    app_ids: list[str],
    variants: dict[str, int] | None = None,
    *,
    local_vantage: str,
) -> bool:
    """Return True when the deploy's declared storage need exceeds the free space.

    Args:
        app_ids: applications the deploy installs; dependencies are walked.
        variants: per-app variant index, as in required_storage_bytes.
        local_vantage: measurement point when the daemon's data root does not
            resolve in this mount namespace, as in docker_root_free_bytes.
    """
    return is_constrained(
        free_bytes=docker_root_free_bytes(local_vantage=local_vantage),
        required_bytes=required_storage_bytes(app_ids, variants),
    )
