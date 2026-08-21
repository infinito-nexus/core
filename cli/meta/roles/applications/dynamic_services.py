"""Print the group-conditional service keys, comma-separated for ``disable=``.

A service key is group-conditional when some role declares it with a Jinja
``enabled`` expression rather than a literal, i.e. the shape
``tests/integration/roles/meta/services/test_dynamic_flags.py`` enforces.
Those keys are the ones a test deploy may drop without changing what the
role under test is: their providers are co-deployed only because a host
happens to be in the provider's group.

Keys without a provider role are omitted — ``disable=`` cannot act on them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.administration.inventory.provision.services_disabler import find_provider_roles
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def dynamic_service_keys(roles_dir: Path) -> list[str]:
    """Return every group-conditional service key that has a provider role."""
    keys: set[str] = set()
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        services = load_yaml_any(
            str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        if not isinstance(services, dict):
            continue
        for key, conf in services.items():
            if not isinstance(conf, dict):
                continue
            if any(
                isinstance(conf.get(flag), str) and "{{" in conf[flag]
                for flag in ("enabled", "shared")
            ):
                keys.add(str(key))
    if not keys:
        return []
    providers = find_provider_roles(sorted(keys), roles_dir)
    return sorted(k for k in keys if k in providers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roles-dir",
        default="roles",
        help="roles directory to scan (default: roles)",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        metavar="KEY",
        help="service keys to keep enabled, e.g. the key the deploy is testing",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    excluded = {k for k in args.exclude if k}
    keys = [k for k in dynamic_service_keys(Path(args.roles_dir)) if k not in excluded]
    print(",".join(keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
