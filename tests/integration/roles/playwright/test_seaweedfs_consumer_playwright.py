"""Integration guard: every ``roles/web-app-*`` role that consumes the
SeaweedFS object store (its ``meta/services.yml`` enables a ``seaweedfs``
service) MUST ship a dedicated object-store Playwright test that:

1. lives at ``files/playwright/test-seaweedfs.js``;
2. is gated by ``skipUnlessServiceEnabled("seaweedfs")`` so a deploy without
   the provider reports the scenario as skipped, never failed;
3. is wired into the role's ``files/playwright/playwright.spec.js`` via
   ``require("./test-seaweedfs")`` so the runner actually executes it.

The scenario itself proves a document reaches SeaweedFS for the app and is
visible through the Filer UI (see
``roles/test-e2e-playwright/files/personas/utils/seaweedfs.js``).

Scope
-----

Only roles that are actually Playwright-enabled are checked, i.e. those
that ship a ``templates/playwright.env.j2`` (the file the runner uses to
discover Playwright roles). A seaweedfs consumer with no Playwright env
cannot run the scenario at all and is out of scope here.

Exemption
---------

A role that enables seaweedfs purely as embedded storage with no
user-facing document surface MAY opt out with a file-head marker within the
first lines of its ``meta/services.yml``::

    ---
    # nocheck: seaweedfs-playwright — <reason>
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_PLAYWRIGHT_SPEC

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "seaweedfs-playwright"
_TEST_FILE_REL = "files/playwright/test-seaweedfs.js"  # nocheck: role-file-spot
_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_SPEC_FILE_REL = ROLE_FILE_PLAYWRIGHT_SPEC

_SEAWEEDFS_GATE_RE = re.compile(
    r"\b(?:skipUnlessServiceEnabled|requireService|isServiceEnabled|"
    r"isServiceDisabledReason|safeSkipUnlessEnabled|safeIsEnabled)\s*\(\s*"
    r"['\"]seaweedfs['\"]"
)
_REQUIRE_TEST_RE = re.compile(r"require\(\s*['\"]\./test-seaweedfs(?:\.js)?['\"]\s*\)")


def _is_truthy_flag(value: object) -> bool:
    return value is True or (isinstance(value, str) and "in group_names" in value)


class TestSeaweedfsConsumerPlaywright(unittest.TestCase):
    def test_seaweedfs_consumer_ships_gated_storage_spec(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            if not role_name.startswith("web-app-"):
                continue
            # The provider role itself owns the cross-consumer bucket spec.
            if role_name == "web-app-seaweedfs":
                continue

            services_file: Path = role_dir / ROLE_FILE_META_SERVICES
            if not services_file.is_file():
                continue

            # Only Playwright-enabled roles (those with a rendered env template)
            # can actually run the scenario; a consumer without one is out of
            # scope here.
            if not (role_dir / _ENV_TEMPLATE_REL).is_file():
                continue

            try:
                lines = read_text(str(services_file)).splitlines()
            except (UnicodeDecodeError, PermissionError):
                continue

            if is_suppressed_in_head(lines, _RULE, scan_lines=30):
                continue

            try:
                data = load_yaml_any(str(services_file), default_if_missing={}) or {}
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            seaweedfs = data.get("seaweedfs")
            if not (
                isinstance(seaweedfs, dict)
                and _is_truthy_flag(seaweedfs.get("enabled"))
            ):
                continue

            test_file = role_dir / _TEST_FILE_REL
            spec_file = role_dir / _SPEC_FILE_REL

            if not test_file.is_file():
                offenders.append(
                    f"{role_name}: consumes seaweedfs but is missing "
                    f"`{_TEST_FILE_REL}` (or mark `# nocheck: {_RULE}` in the "
                    f"services.yml head)."
                )
                continue

            test_text = read_text(str(test_file))
            if not _SEAWEEDFS_GATE_RE.search(test_text):
                offenders.append(
                    f"{role_name}: `{_TEST_FILE_REL}` does not gate on "
                    f'`skipUnlessServiceEnabled("seaweedfs")`.'
                )

            if not spec_file.is_file():
                offenders.append(
                    f"{role_name}: consumes seaweedfs but has no "
                    f"`{_SPEC_FILE_REL}` to wire `test-seaweedfs.js` into."
                )
            elif not _REQUIRE_TEST_RE.search(read_text(str(spec_file))):
                offenders.append(
                    f"{role_name}: `{_SPEC_FILE_REL}` does not "
                    f'`require("./test-seaweedfs")`.'
                )

        if offenders:
            self.fail(
                f"seaweedfs consumers MUST ship a gated storage Playwright test "
                f"({_RULE}):\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
