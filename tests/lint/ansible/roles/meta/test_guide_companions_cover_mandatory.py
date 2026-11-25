"""Lint guard: a replayable role names every mandatory provider gated on
``'<role>' in group_names`` under ``guide_companions``.

Trip-wire: the README replay deploys ``--include`` of the role and its
companions only, so a provider pulled in as a dependency never joins
``group_names``; the gated flag stays false and the documented deploy fails
(web-svc-libretranslate answered 502 without its engine, fork run
45533254683).
"""

from __future__ import annotations

import re
import unittest

from utils.roles.guide import guide_deployable
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_guide_companions

from . import load_role_meta, role_dirs

GATE = re.compile(r"'([a-z0-9-]+)' in group_names")


def _mandatory_providers(services: dict) -> set[str]:
    """
    Args:
        services: a role's parsed ``meta/services.yml``.

    Returns:
        The roles a ``mandatory: true`` entry gates its ``enabled`` flag on.
    """
    providers: set[str] = set()
    for entry in services.values():
        if isinstance(entry, dict) and entry.get("mandatory") is True:
            providers.update(GATE.findall(str(entry.get("enabled", ""))))
    return providers


class TestGuideCompanionsCoverMandatory(unittest.TestCase):
    def test_every_mandatory_gated_provider_is_a_companion(self) -> None:
        offenders = []
        for role in role_dirs():
            services = load_role_meta(role / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict) or not guide_deployable(role.name):
                continue
            missing = _mandatory_providers(services) - set(
                get_role_guide_companions(role, role_name=role.name)
            )
            offenders.extend(f"{role.name}: {name}" for name in sorted(missing))
        self.assertEqual(
            offenders,
            [],
            "add each provider to guide_companions of the role's primary entry "
            "in meta/services.yml, or the README replay deploys without it",
        )


if __name__ == "__main__":
    unittest.main()
