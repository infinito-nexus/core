"""Pick the role and deploy mode for the Guide test.

Role selection: an explicit ``--role`` wins; otherwise a random pick from
``--priority``, then ``--whitelist``, then every invokable role inside the
tested lifecycle envelope (``INFINITO_LIFECYCLES`` in ``default.env``) whose
guide deploy mode is not skipped via ``meta/tests.yml``. The mode is ``host``
for a role that ships no container stack (installed straight onto the machine),
else ``compose``. The distro is not picked here: the role is replayed on every
distro by ``scripts/tests/deploy/distros.sh``. Output is ``key=value`` lines
for ``$GITHUB_ENV``.
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT
from utils.roles.deploy import role_has_stack
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.meta_lookup import get_role_test_skips
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
    _role_lifecycle,
)

if TYPE_CHECKING:
    from pathlib import Path


def _tokens(raw: str) -> list[str]:
    return [t for t in raw.split() if t]


def _guide_mode(role_dir: Path) -> str:
    return "compose" if role_has_stack(role_dir) else "host"


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
        and _guide_mode(d) not in get_role_test_skips(d, role_name=d.name)
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

    mode = _guide_mode(PROJECT_ROOT / "roles" / role)

    print(f"GUIDE_ROLE={role}")
    print(f"GUIDE_MODE={mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
