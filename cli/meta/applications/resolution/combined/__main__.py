#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .resolver import CombinedResolver
from .tree import print_tree


def _load_services_overrides(path: str | None) -> dict[str, dict]:
    """Load `{role_name: services_dict}` overrides from a JSON file.

    The file is produced by the variant-aware planner in
    `cli.deploy.development.inventory` to feed each round's
    variant-merged services map back into the resolver running inside
    the infinito container. Missing or empty path returns `{}` so
    non-variant-aware callers keep the legacy disk-only behaviour.
    """
    if not path:
        return {}
    raw = Path(path).read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit(
            f"--services-overrides {path}: expected a JSON object "
            f"({{role_name: services_map}}), got {type(data).__name__}"
        )
    out: dict[str, dict] = {}
    for role_name, services in data.items():
        if not isinstance(role_name, str) or not role_name.strip():
            raise SystemExit(
                f"--services-overrides {path}: invalid role key {role_name!r}"
            )
        if not isinstance(services, dict):
            raise SystemExit(
                f"--services-overrides {path}: services for {role_name!r} "
                f"must be an object, got {type(services).__name__}"
            )
        out[role_name] = services
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve run_after + dependencies transitively for a role (optional tree output)."
    )
    parser.add_argument(
        "role_name", help="Name of the role folder under ./roles (e.g., web-app-taiga)"
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Print an ASCII dependency tree instead of a whitespace-separated list.",
    )
    parser.add_argument(
        "--services-overrides",
        default=None,
        help=(
            "Path to a JSON file `{role_name: services_map}` whose entries "
            "replace each listed role's on-disk meta/services.yml when "
            "deriving services edges. Used by the variant-aware planner to "
            "feed round-specific topology into the resolver."
        ),
    )
    args = parser.parse_args()

    if args.tree:
        print_tree(args.role_name)
        return

    overrides = _load_services_overrides(args.services_overrides)
    resolver = CombinedResolver(services_overrides=overrides)
    resolved = resolver.resolve(args.role_name)
    print(" ".join(resolved))


if __name__ == "__main__":
    main()
