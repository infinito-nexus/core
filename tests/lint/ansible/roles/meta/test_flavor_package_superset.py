"""A role's default flavor MUST address every package its other flavors can.

A role that installs itself in more than one flavor keeps one set of packages
per flavor, and the two sets are derived from different places. For
``web-app-matrix`` the compose flavor builds its bridge loop from
``meta/addons/`` (``tasks/flavor/compose/main.yml`` selects the addons whose
``mechanism`` is ``bridge`` and whose ``config.bridge_name`` is set), while the
default ansible flavor addresses packages through a mapping constant in
``vars/main.yml`` that pairs each package key with the upstream switches it
drives.

Nothing ties those two sources together, so a package added as an addon is
invisible to the default flavor until someone also adds its key to that
mapping, and a deployment that switches flavor silently loses it. The default
flavor is therefore required to be the superset: every bridge the non-default
flavor can construct must have a key the default flavor can address. The
reverse is allowed - the default flavor may know packages no addon declares.

The check compares the two derived sets rather than grepping the templates,
because the compose flavor iterates its bridges instead of naming them and a
token scan would read that as "supports none". The default flavor iterates too,
so its side is read from the mapping constant rather than from the rendered
variable names.
"""

from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
BRIDGE_MECHANISM = "bridge"
PLUGIN_PREFIX = "mautrix_"


def _bridge_names(role_dir) -> set[str]:
    """Every ``config.bridge_name`` a role's bridge addons declare.

    Args:
        role_dir: the role's directory.
    """
    names: set[str] = set()
    for path in sorted((role_dir / "meta" / "addons").glob("*.yml")):
        spec = load_yaml_str(read_text(str(path))) or {}
        if spec.get("mechanism") != BRIDGE_MECHANISM:
            continue
        name = (spec.get("config") or {}).get("bridge_name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _unaddressed_bridges(role_dir) -> list[str]:
    """Bridge addons that name no upstream switch for the default flavor.

    Args:
        role_dir: the role's directory.
    """
    offenders: list[str] = []
    for path in sorted((role_dir / "meta" / "addons").glob("*.yml")):
        spec = load_yaml_str(read_text(str(path))) or {}
        if spec.get("mechanism") != BRIDGE_MECHANISM:
            continue
        config = spec.get("config") or {}
        name = config.get("bridge_name")
        if not isinstance(name, str) or not name:
            continue
        flags = config.get("upstream_flags")
        if not isinstance(flags, list) or not [f for f in flags if str(f).strip()]:
            offenders.append(path.stem)
    return offenders


def _multi_flavor_roles() -> list:
    """Role directories that ship more than one ``templates/flavor/`` tree."""
    return [
        flavor_dir.parent.parent
        for flavor_dir in sorted(ROLES_DIR.glob("*/templates/flavor"))
        if len([d for d in flavor_dir.iterdir() if d.is_dir()]) > 1
    ]


class TestFlavorPackageSuperset(unittest.TestCase):
    def test_the_default_flavor_addresses_every_bridge_addon(self) -> None:
        offenders: list[str] = []
        for role_dir in _multi_flavor_roles():
            offenders.extend(
                f"{role_dir.name}: addons.{addon_id} builds a bridge in the "
                "non-default flavor but declares no config.upstream_flags, so the "
                "default flavor renders no switch for it"
                for addon_id in _unaddressed_bridges(role_dir)
            )

        if offenders:
            self.fail(
                f"{len(offenders)} bridge addon(s) the default flavor cannot "
                "address. List the upstream switches under config.upstream_flags "
                "so both flavors deploy the same set:\n" + "\n".join(offenders)
            )

    def test_the_check_sees_at_least_one_multi_flavor_role(self) -> None:
        roles = _multi_flavor_roles()
        self.assertTrue(
            roles,
            "no role ships two flavor trees any more, so this guard passes "
            "vacuously and needs rewriting rather than silently succeeding",
        )
        self.assertTrue(
            any(_bridge_names(role_dir) for role_dir in roles),
            "no multi-flavor role declares a bridge addon with a bridge_name, so "
            "the superset comparison has nothing to compare",
        )


if __name__ == "__main__":
    unittest.main()
