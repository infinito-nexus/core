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

from utils import PROJECT_ROOT
from utils.cache.applications import get_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.applications.services.resources import (
    aggregate,
    collect_role_resources,
)


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
        applications = dict(applications)
        available = get_variants(roles_dir=str(roles_dir))
        for app_id, index in variants.items():
            app_variants = available.get(app_id) or []
            if 0 <= index < len(app_variants):
                applications[app_id] = app_variants[index] or {}

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


def is_constrained(*, free_bytes: int, required_bytes: int) -> bool:
    """Return True when the declared need does not fit into the free space."""
    return required_bytes > free_bytes


def docker_data_root() -> str:
    """Return Docker's data root as reported by the local daemon.

    Raises:
        RuntimeError: the daemon is unreachable or reports no data root. Guessing
            a path here would silently measure the wrong filesystem and report a
            roomy host, which is the failure this module exists to prevent.
    """
    proc = subprocess.run(
        ["docker", "info", "-f", "{{.DockerRootDir}}"],
        capture_output=True,
        text=True,
        check=False,
    )
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
