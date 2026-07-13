"""Expand a discovered app-id list into CI deploy-matrix entries.

A role whose matrix-deploy declares more variants than a single runner should
iterate is split into bundles of consecutive variant indices, one runner per
bundle — e.g. a 5-variant role becomes ``0,1,2`` and ``3,4``. A new bundle opens
as soon as the current one would exceed ``INFINITO_VARIANT_BUNDLE_SIZE`` variants
(default 3) OR ``INFINITO_VARIANT_BUNDLE_MAX_STORAGE`` cumulative ``min_storage``
(default 350GB), so storage-heavy variants are not stacked onto one runner that
would then run too long. Roles that fit one runner stay a single entry but still
carry their full ``0,…,N-1`` variant CSV, so every job name shows the variants it
covers.

Each entry is ``{"apps": <id>, "variant": "<csv>", "variant_slug": "<dashed>"}``;
``variant`` is empty only for a role that declares no variants (a plain base
deploy). The ``variant`` slice is threaded
through to ``cli.administration.deploy.development`` via the ``variant``
environment variable (consumed by ``--variant``), so a runner only iterates the
rounds in its bundle. ``variant_slug`` is a comma-free copy for artifact/job
names (GitHub Actions expressions have no string-replace function).
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

from humanfriendly import parse_size

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

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path
    from typing import Any

DEFAULT_BUNDLE_SIZE = 3
# Also a runtime proxy: hosted runners kill jobs at 6h, and heavy multi-round
# roles (nextcloud) only fit that wall with <= 2 variants per bundle. Keep the
# cap below their lightest 3-variant sum or the greedy packer overshoots.
DEFAULT_MAX_STORAGE = "330GB"
ROLES_DIR = PROJECT_ROOT / "roles"


def resolve_bundle_size(raw: str | None = None) -> int:
    if raw is None:
        raw = os.environ.get("INFINITO_VARIANT_BUNDLE_SIZE")
    value = (raw or "").strip()
    if not value:
        return DEFAULT_BUNDLE_SIZE
    try:
        size = int(value)
    except ValueError:
        raise ValueError(
            f"INFINITO_VARIANT_BUNDLE_SIZE must be an integer, got {value!r}"
        ) from None
    if size < 1:
        raise ValueError("INFINITO_VARIANT_BUNDLE_SIZE must be >= 1")
    return size


def resolve_max_storage(raw: str | None = None) -> int | None:
    if raw is None:
        raw = os.environ.get("INFINITO_VARIANT_BUNDLE_MAX_STORAGE")
    value = (raw or "").strip()
    if not value:
        value = DEFAULT_MAX_STORAGE
    if value.lower() in ("0", "off", "none"):
        return None
    try:
        return int(parse_size(value))
    except Exception:
        raise ValueError(
            f"INFINITO_VARIANT_BUNDLE_MAX_STORAGE must be a size like {DEFAULT_MAX_STORAGE!r}, "
            f"got {value!r}"
        ) from None


def bundle_indices(
    count: int,
    bundle_size: int,
    storages: Sequence[int | None] | None = None,
    max_storage_bytes: int | None = None,
) -> list[list[int]]:
    """Greedily pack variant indices into bundles, opening a new bundle as soon
    as the current one would exceed ``bundle_size`` variants OR
    ``max_storage_bytes`` cumulative ``min_storage``; both counters reset per
    bundle. With no storage cap this matches ``chunk_indices``. A single variant
    that alone exceeds the storage cap still forms its own bundle."""
    bundles: list[list[int]] = []
    current: list[int] = []
    current_storage = 0
    for index in range(count):
        size = 0
        if storages is not None and index < len(storages):
            size = storages[index] or 0
        over_count = len(current) >= bundle_size
        over_storage = (
            max_storage_bytes is not None
            and bool(current)
            and current_storage + size > max_storage_bytes
        )
        if current and (over_count or over_storage):
            bundles.append(current)
            current = []
            current_storage = 0
        current.append(index)
        current_storage += size
    if current:
        bundles.append(current)
    return bundles


def chunk_indices(count: int, bundle_size: int) -> list[list[int]]:
    return [
        list(range(start, min(start + bundle_size, count)))
        for start in range(0, count, bundle_size)
    ]


def variant_count(variants_per_app: Mapping[str, Sequence[Any]], app: str) -> int:
    return max(1, len(variants_per_app.get(app) or []))


def _entry(app: str, variant_csv: str) -> dict[str, str]:
    # `variant_slug` is a comma-free copy for artifact/job names: GitHub Actions
    # expressions have no replace(), so the CSV cannot be sanitised in YAML.
    return {
        "apps": app,
        "variant": variant_csv,
        "variant_slug": variant_csv.replace(",", "-"),
    }


def expand_apps(
    apps: Iterable[str],
    variants_per_app: Mapping[str, Sequence[Any]],
    bundle_size: int = DEFAULT_BUNDLE_SIZE,
    *,
    storages_per_app: Mapping[str, Sequence[int | None]] | None = None,
    max_storage_bytes: int | None = None,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for app in apps:
        variant_list = variants_per_app.get(app) or []
        if not variant_list:
            entries.append({"apps": app, "variant": "", "variant_slug": ""})
            continue
        storages = (storages_per_app or {}).get(app)
        bundles = bundle_indices(
            len(variant_list), bundle_size, storages, max_storage_bytes
        )
        entries.extend(_entry(app, ",".join(map(str, chunk))) for chunk in bundles)
    return entries


def app_variant_storages(
    apps: Iterable[str],
    variants_per_app: Mapping[str, Sequence[Any]],
    roles_dir: Path = ROLES_DIR,
) -> dict[str, list[int | None]]:
    """Per-variant total ``min_storage`` (bytes) for each app, via the shared
    resource collection (same machinery as the ``ressources`` CLI / budget
    lint). Unknown apps and variants without storage yield ``None`` entries."""
    applications = load_applications_from_roles_dir(roles_dir)
    registry = build_service_registry_from_applications(applications)
    result: dict[str, list[int | None]] = {}
    for app in apps:
        sizes: list[int | None] = []
        for variant_config in variants_per_app.get(app) or []:
            scoped = dict(applications)
            scoped[app] = variant_config or {}
            rows: list[dict[str, Any]] = []
            collect_role_resources(
                role_name=app,
                applications=scoped,
                service_registry=registry,
                visited=set(),
                rows=rows,
                warnings=[],
                dedup=True,
            )
            sizes.append(aggregate(rows).get("min_storage_bytes"))
        result[app] = sizes
    return result


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    raw = argv[0] if argv else sys.stdin.read()
    apps = json.loads(raw) if raw.strip() else []
    if not isinstance(apps, list):
        raise SystemExit(
            f"variant_bundles: expected a JSON array of app ids, got "
            f"{type(apps).__name__}"
        )
    variants_per_app = get_variants()
    entries = expand_apps(
        apps,
        variants_per_app,
        resolve_bundle_size(),
        storages_per_app=app_variant_storages(apps, variants_per_app),
        max_storage_bytes=resolve_max_storage(),
    )
    print(json.dumps(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
