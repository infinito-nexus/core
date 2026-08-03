"""A vendored addon and its shipped file must find each other.

``source: vendored`` means the payload is committed under the role. The
install path resolves it by convention - ``files/mu-plugins/<addon_id>.php``
for a WordPress mu-plugin - so a rename on either side silently breaks the
deploy: the copy step fails on a path nobody typed, and a file with no
declaration is never installed at all. That second direction is how
``infinito-http-ca-trust`` shipped for months while the loop that installs
mu-plugins never saw it.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
VENDORED_DIRS = {"mu_plugin": ("files/mu-plugins", ".php")}


def _vendored_addons():
    for role in sorted(ROLES_DIR.iterdir()):
        addons_dir = role / ROLE_DIR_META_ADDONS
        if not addons_dir.is_dir():
            continue
        for spec_file in sorted(addons_dir.glob("*.yml")):
            spec = load_yaml_any(str(spec_file), default_if_missing={}) or {}
            layout = VENDORED_DIRS.get(spec.get("mechanism"))
            if layout and spec.get("source") == "vendored":
                yield role, spec_file.stem, layout


class TestAddonsVendoredFiles(unittest.TestCase):
    def test_every_vendored_addon_ships_its_file(self) -> None:
        missing = [
            f"{role.name}: addon '{addon_id}' declares source: vendored "
            f"but {subdir}/{addon_id}{suffix} does not exist"
            for role, addon_id, (subdir, suffix) in _vendored_addons()
            if not (role / subdir / f"{addon_id}{suffix}").is_file()
        ]
        if missing:
            self.fail("\n".join(missing))

    def test_every_shipped_file_is_declared(self) -> None:
        declared = {
            (role.name, subdir, addon_id)
            for role, addon_id, (subdir, _) in _vendored_addons()
        }
        orphans = []
        for role in sorted(ROLES_DIR.iterdir()):
            for subdir, suffix in VENDORED_DIRS.values():
                orphans.extend(
                    f"{role.name}: {subdir}/{shipped.name} has no "
                    f"meta/addons/{shipped.stem}.yml, so nothing installs it"
                    for shipped in sorted((role / subdir).glob(f"*{suffix}"))
                    if (role.name, subdir, shipped.stem) not in declared
                )
        if orphans:
            self.fail("\n".join(orphans))


if __name__ == "__main__":
    unittest.main()
