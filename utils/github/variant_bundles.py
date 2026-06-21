"""Expand a discovered app-id list into CI deploy-matrix entries.

A role whose matrix-deploy declares more variants than a single runner should
iterate (``INFINITO_VARIANT_BUNDLE_SIZE``, default 3) is split into bundles of
consecutive variant indices, one runner per bundle — e.g. a 5-variant role
becomes ``0,1,2`` and ``3,4``. Roles that fit one runner stay a single entry.

Each entry is ``{"apps": <id>, "variant": "<csv>", "variant_slug": "<dashed>"}``;
an empty ``variant`` means full-matrix mode. The ``variant`` slice is threaded
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

from utils.cache.applications import get_variants

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Any

DEFAULT_BUNDLE_SIZE = 3


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
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for app in apps:
        count = variant_count(variants_per_app, app)
        if count <= bundle_size:
            entries.append({"apps": app, "variant": "", "variant_slug": ""})
            continue
        entries.extend(
            _entry(app, ",".join(map(str, chunk)))
            for chunk in chunk_indices(count, bundle_size)
        )
    return entries


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    raw = argv[0] if argv else sys.stdin.read()
    apps = json.loads(raw) if raw.strip() else []
    if not isinstance(apps, list):
        raise SystemExit(
            f"variant_bundles: expected a JSON array of app ids, got "
            f"{type(apps).__name__}"
        )
    entries = expand_apps(apps, get_variants(), resolve_bundle_size())
    print(json.dumps(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
