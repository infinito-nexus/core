"""Lint: every web-facing addon ships a per-addon Playwright spec.

For each ``roles/<role>/meta/addons/<id>.yml`` of a web-facing role a spec
MUST exist at ``roles/<role>/files/playwright/addons/<id>.spec.js``. There is
no per-addon exemption: no mechanism auto-exempt and no ``# nocheck`` escape;
every such addon carries its own spec (gated with ``skipUnlessAddonEnabled``
so it skips cleanly when the addon is not enabled in the current variant).

Desktop (``dsk-*``) roles are the one categorical exception: they drive no
web surface a Playwright test could exercise, so they MUST NOT ship addon
specs at all. The lint forbids spec files under ``dsk-*`` roles.
"""

from __future__ import annotations

import unittest

from utils.update.addons import iter_addon_files

from . import PROJECT_ROOT

DESKTOP_ROLE_PREFIX = "dsk-"


class TestAddonsPlaywrightSpec(unittest.TestCase):
    def test_every_addon_has_a_spec(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        errors: list[str] = []
        for role, addon_file in iter_addon_files(roles_root):
            addon_id = addon_file.stem
            rel = addon_file.relative_to(PROJECT_ROOT).as_posix()
            spec_path = (
                roles_root
                / role
                / "files"
                / "playwright"
                / "addons"
                / f"{addon_id}.spec.js"
            )
            spec_rel = spec_path.relative_to(PROJECT_ROOT).as_posix()
            if role.startswith(DESKTOP_ROLE_PREFIX):
                if spec_path.is_file():
                    errors.append(
                        f"{role}: addons.{addon_id} ships a Playwright spec at "
                        f"{spec_rel} but desktop ({DESKTOP_ROLE_PREFIX}*) roles drive "
                        f"no web surface and MUST NOT ship specs; delete it."
                    )
                continue
            if not spec_path.is_file():
                errors.append(
                    f"{role}: addons.{addon_id} has no Playwright spec at "
                    f"{spec_rel} (declared in {rel}); every web-facing addon MUST ship a spec."
                )

        if errors:
            self.fail(
                f"playwright per-addon spec violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
