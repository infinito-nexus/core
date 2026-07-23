"""``*_PORT`` constants in ``roles/*/vars/main.yml`` MUST resolve their
value through a lookup (``lookup('config', ...)`` on the role's
``meta/services.yml`` ports block, or another port-resolving plugin) -
never a literal number.

A literal port in vars/main.yml is a second source of truth: the service's
ports live in ``meta/services.yml`` (``services.<service>.ports.<scope>.<name>``),
where the port governance (bands, collision checks, stack rendering) reads
them. A vars literal silently drifts away from what the stack actually
publishes. Suppress a genuine exception per line with
``# nocheck: port-literal <why>``.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*port-literal\b")


def _is_literal_port(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and value.strip().isdigit()


def _nocheck_lines(path: Path) -> set[int]:
    return {
        lineno
        for lineno, line in enumerate(read_text(str(path)).splitlines(), start=1)
        if _NOCHECK_RE.search(line)
    }


def _key_line(path: Path, key: str) -> int:
    for lineno, line in enumerate(read_text(str(path)).splitlines(), start=1):
        if re.match(rf"\s*{re.escape(key)}\s*:", line):
            return lineno
    return 0


class TestPortVarsUseLookup(unittest.TestCase):
    def test_port_vars_resolve_via_lookup(self):
        offenders: list[str] = []

        for vars_file in sorted(ROLES_DIR.glob(f"*/{ROLE_FILE_VARS_MAIN}")):
            data = load_yaml_any(str(vars_file), default_if_missing={}) or {}
            if not isinstance(data, dict):
                continue
            suppressed = _nocheck_lines(vars_file)
            for key, value in data.items():
                if not (isinstance(key, str) and key.endswith("_PORT")):
                    continue
                if not _is_literal_port(value):
                    continue
                lineno = _key_line(vars_file, key)
                if lineno in suppressed:
                    continue
                rel = vars_file.relative_to(PROJECT_ROOT)
                offenders.append(f"{rel}:{lineno}: {key}: {value!r}")

        if offenders:
            self.fail(
                f"{len(offenders)} literal *_PORT value(s) in vars/main.yml. "
                "Define the port in the role's meta/services.yml under the "
                "service (services.<service>.ports.<scope>.<name>) and resolve "
                "it here via lookup, e.g. "
                "\"{{ lookup('config', application_id, "
                "'services.<service>.ports.internal.<name>') }}\". Suppress a "
                "genuine exception with `# nocheck: port-literal <why>`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
