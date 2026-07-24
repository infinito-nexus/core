"""Pick the role, distro, and deploy mode for the Guide test.

Role selection: an explicit ``--role`` wins; otherwise a random pick from
``--priority``, then ``--whitelist``, then every invokable role inside the
tested lifecycle envelope (``INFINITO_LIFECYCLES`` in ``default.env``). The distro is
a random pick from ``INFINITO_DISTROS``, resolved to that distro's pkgmgr base
image (it ships systemd plus the build toolchain, so a host role can boot
systemd and install straight inside it). The mode is ``host`` for a role that
ships no container stack (installed straight onto the machine), else
``compose``. Output is ``key=value`` lines for ``$GITHUB_ENV``.
"""

from __future__ import annotations

import argparse
import os
import random
import sys

from utils.cache.files import PROJECT_ROOT
from utils.roles.deploy import role_has_stack
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
    _role_lifecycle,
)

_RUNTIME_IMAGE = "ghcr.io/kevinveenbirkenbach/pkgmgr-{distro}:stable"

_DISTROS = ("arch", "debian", "ubuntu", "fedora", "centos")


def _tokens(raw: str) -> list[str]:
    return [t for t in raw.split() if t]


def _testable_roles() -> list[str]:
    paths = _get_invokable_paths()
    roles_dir = PROJECT_ROOT / "roles"
    tested = set(tested_lifecycles())
    return sorted(
        d.name
        for d in roles_dir.iterdir()
        if d.is_dir()
        and _is_role_invokable(d.name, paths)
        and _role_lifecycle(d) in tested
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--whitelist", default="")
    args = parser.parse_args(argv)

    if args.role.strip():
        role = args.role.strip()
    else:
        pool = _tokens(args.priority) or _tokens(args.whitelist) or _testable_roles()
        if not pool:
            print("guide_select: no candidate roles", file=sys.stderr)
            return 1
        role = random.choice(pool)  # noqa: S311 - test-role pick, not cryptographic

    distros = [d for d in _tokens(os.environ["INFINITO_DISTROS"]) if d in _DISTROS]
    if not distros:
        print("guide_select: no known distro in INFINITO_DISTROS", file=sys.stderr)
        return 1
    distro = random.choice(distros)  # noqa: S311 - test-distro pick, not cryptographic

    mode = "compose" if role_has_stack(PROJECT_ROOT / "roles" / role) else "host"

    print(f"GUIDE_ROLE={role}")
    print(f"GUIDE_MODE={mode}")
    print(f"INFINITO_DISTRO={distro}")
    print(f"GUIDE_RUNTIME_IMAGE={_RUNTIME_IMAGE.format(distro=distro)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
