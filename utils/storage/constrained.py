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
from typing import TYPE_CHECKING, Any

from plugins.filter.libretranslate_store import (
    SELECTION_KEYS,
    libretranslate_selection,
)
from utils import PROJECT_ROOT
from utils.cache.applications import get_variants, with_variants
from utils.cache.artefacts import (
    Artefact,
    artefacts,
    records,
    store_bytes,
    unpacked_bytes,
)
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    load_applications_from_roles_dir,
)
from utils.roles.applications.services.resources import (
    aggregate,
    collect_role_resources,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

DOCKER_INFO_TIMEOUT_S = 30


class StorageDeclarationError(ValueError):
    pass


def selected_artefacts(services: Iterable[tuple[str, Any]]) -> list[Artefact]:
    """
    Args:
        services: ``(role, configuration)`` of every service a round runs.

    Returns:
        The Argos packages and MiniSBD models each consumer's ``load_only`` and
        ``directions`` select, the ``artefacts`` `libretranslate_store` seeds
        for it, each name once however many consumers select it; empty when no
        consumer runs.

    Raises:
        StorageDeclarationError: a consumer runs and an artefact breaks the
            manifest contract, its ``model_store`` is no boolean or an Argos
            record names no package pair; the message names the consumer role
            and the breaching record.
    """
    consumers = [
        (role, service)
        for role, service in services
        if isinstance(service, dict) and all(key in service for key in SELECTION_KEYS)
    ]
    if not consumers:
        return []
    try:
        pinned = list(records("").values())
    except ValueError as exc:
        roles = ", ".join(sorted({role for role, _ in consumers}))
        raise StorageDeclarationError(
            f"{roles}: the LibreTranslate selection cannot be sized: {exc}"
        ) from exc
    names: set[str] = set()
    for role, service in consumers:
        try:
            names.update(
                record["name"] for record in libretranslate_selection(pinned, service)
            )
        except (TypeError, ValueError) as exc:
            raise StorageDeclarationError(
                f"{role}: the LibreTranslate selection cannot be sized: {exc}"
            ) from exc
    return [item for item in artefacts() if item.name in names]


def selection_storage_bytes(services: Iterable[tuple[str, Any]]) -> int:
    """
    Args:
        services: as `selected_artefacts` takes them.

    Returns:
        The packed and unpacked bytes of `selected_artefacts`, each digest once.

    Raises:
        StorageDeclarationError: as `selected_artefacts` raises it.
    """
    selected = selected_artefacts(services)
    return store_bytes(selected) + unpacked_bytes(selected)


def _service(applications: Mapping[str, Any], row: dict) -> tuple[str, Any]:
    config = applications.get(row["role"])
    services = config.get("services") if isinstance(config, dict) else None
    service = services.get(row["service"]) if isinstance(services, dict) else None
    return row["role"], service


def required_storage_bytes(
    app_ids: list[str], variants: dict[str, int] | None = None
) -> int:
    """Return the summed min_storage of app_ids and their transitive dependencies.

    Args:
        app_ids: applications the deploy installs; dependencies are walked.
        variants: per-app variant index whose `meta/variants.yml` overlay decides
            which services are enabled and what a LibreTranslate service
            selects. Without it the base configuration counts, which
            over-states a deploy that a variant trims down.

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
    declared = aggregate(rows, ["min_storage"]).get("min_storage_bytes") or 0
    return declared + selection_storage_bytes(
        _service(applications, row) for row in rows
    )


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
        bytes, 0 for a role that declares nothing or is no application. A
        role also carries the `selected_artefacts` digests of its services
        that no earlier role of ``roles`` seeds, so the values sum each
        digest of the closure once.

    Raises:
        StorageDeclarationError: from ``measure``, when a service of a listed
            role sets min_storage to a value that does not parse; counting it
            as 0 would under-state the closure without a trace. Also as
            `selected_artefacts` raises it.
    """
    applications = load_applications_from_roles_dir(roles_dir)
    available = get_variants(roles_dir=str(roles_dir))
    service_registry = build_service_registry_from_applications(applications)

    def measure(roles: Iterable[str], variants: dict[str, int]) -> dict[str, int]:
        scoped = with_variants(applications, available, variants)
        declared: dict[str, int] = {}
        seeded: set[str] = set()
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
            fresh = [
                item
                for item in selected_artefacts(_service(scoped, row) for row in rows)
                if item.sha256 not in seeded
            ]
            seeded.update(item.sha256 for item in fresh)
            declared[role] = (
                aggregate(rows, ["min_storage"]).get("min_storage_bytes") or 0
            ) + (store_bytes(fresh) + unpacked_bytes(fresh))
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
