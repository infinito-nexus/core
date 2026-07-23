"""Lint guard: a role whose categories.yml category declares ``modes``
defaults MUST declare exactly those ``modes.<mode>.enabled`` values on its
deploy-bearing service entries -- explicitly, so meta/services.yml stays the
readable truth while categories.yml defines the category policy (deepest
category wins, parents apply when no deeper one declares).

Current policy: drv and svc-net are host-hardware categories (compose and
swarm disabled); svc-registry is CI bootstrap infrastructure (compose and
swarm enabled).

Exempt a service with ``# nocheck: category-modes`` on (or directly above)
its ``meta/services.yml`` key.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.stage import role_modes_defaults

from . import PROJECT_ROOT

_ROLES_DIR = PROJECT_ROOT / "roles"
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*category-modes\b")


def _service_nocheck(lines: list[str], key: str) -> bool:
    pat = re.compile(r"^" + re.escape(key) + r"\s*:")
    for i, line in enumerate(lines):
        if not pat.match(line):
            continue
        if _NOCHECK_RE.search(line):
            return True
        j = i - 1
        while j >= 0 and lines[j].lstrip().startswith("#"):
            if _NOCHECK_RE.search(lines[j]):
                return True
            j -= 1
        return False
    return False


def _is_deploy_entry(entry: dict) -> bool:
    """Deploy-bearing entries carry modes/lifecycle; pure consumer blocks
    (bond/enabled/shared references to a shared service) carry neither."""
    return "modes" in entry or "lifecycle" in entry


class TestCategoryModes(unittest.TestCase):
    def test_roles_declare_category_mode_defaults_explicitly(self) -> None:
        offenders: list[str] = []
        checked = 0

        for role_dir in sorted(p for p in _ROLES_DIR.iterdir() if p.is_dir()):
            defaults = role_modes_defaults(role_dir.name)
            if not defaults:
                continue
            services_file = role_dir / ROLE_FILE_META_SERVICES
            services = load_yaml_any(str(services_file), default_if_missing=None)
            if not isinstance(services, dict):
                continue
            lines = read_text(str(services_file)).splitlines()

            for key, entry in services.items():
                if not isinstance(entry, dict) or not _is_deploy_entry(entry):
                    continue
                if _service_nocheck(lines, key):
                    continue
                checked += 1
                modes = entry.get("modes")
                for mode, expected in defaults.items():
                    conf = modes.get(mode) if isinstance(modes, dict) else None
                    enabled = conf.get("enabled") if isinstance(conf, dict) else None
                    if enabled is not expected:
                        offenders.append(
                            f"{role_dir.name}: services.{key}.modes.{mode}.enabled "
                            f"must be declared {str(expected).lower()} "
                            f"(found {enabled!r})"
                        )

        self.assertTrue(checked, "no category-mode-governed service entries found")
        if offenders:
            self.fail(
                "category mode policy violations "
                f"({len(offenders)}):\n\n"
                "categories.yml declares mode defaults for this role's "
                "category; the role must declare exactly those "
                "modes.<mode>.enabled values in meta/services.yml, or exempt "
                "the service with '# nocheck: category-modes' on its key.\n\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
