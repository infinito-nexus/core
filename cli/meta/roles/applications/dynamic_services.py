"""Print the group-conditional service keys, comma-separated for ``disable=``.

A service key is group-conditional when some role declares it with a Jinja
``enabled`` expression rather than a literal, i.e. the shape
``tests/integration/roles/meta/services/test_dynamic_flags.py`` enforces.
Those keys are the ones a test deploy may drop without changing what the
role under test is: their providers are co-deployed only because a host
happens to be in the provider's group.

A key some other role declares group-conditionally can still be one the role
under test enables literally (``openresty`` of a web app, conditional in
``svc-stack``); ``--role`` keeps those, since dropping them changes that role.

Keys without a provider role are omitted — ``disable=`` cannot act on them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.administration.inventory.provision.services.disabler import find_provider_roles
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _role_services(role_dir: Path) -> dict:
    services = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    return services if isinstance(services, dict) else {}


def literally_enabled_keys(roles_dir: Path, role: str) -> set[str]:
    """Return the service keys a role enables with a literal ``true``.

    Args:
        roles_dir: roles tree holding the role.
        role: role directory name of the role under test.

    Returns:
        every key of the role's ``meta/services.yml`` whose ``enabled`` is the
        boolean ``True``; empty when the role declares no services.
    """
    return {
        str(key)
        for key, conf in _role_services(roles_dir / role).items()
        if isinstance(conf, dict) and conf.get("enabled") is True
    }


def dynamic_service_keys(roles_dir: Path) -> list[str]:
    """Return every group-conditional service key that has a provider role."""
    keys: set[str] = set()
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        for key, conf in _role_services(role_dir).items():
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
        "--role",
        action="append",
        default=[],
        metavar="ROLE",
        help="role under test; every key it enables literally stays enabled",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        metavar="KEY",
        help="further service keys to keep enabled, e.g. a provider the role needs",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    roles_dir = Path(args.roles_dir)
    excluded = {k for k in args.exclude if k}
    for role in args.role:
        excluded |= literally_enabled_keys(roles_dir, role)
    keys = [k for k in dynamic_service_keys(roles_dir) if k not in excluded]
    print(",".join(keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
