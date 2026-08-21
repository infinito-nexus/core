"""Integration guard: for every ``svc-db-*`` role shipping an over-Tor
credential test, assert that the transport its ``test.env.j2`` selects agrees
with the onion mapping ``plugins.lookup.tor_ports.collect_exposed_ports``
produces, in the base config and in every declared variant.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from plugins.lookup.tor_ports import collect_exposed_ports
from plugins.lookup.tor_reachable import is_reachable
from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications, get_variants
from utils.cache.files import read_text

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_GATE_RE = re.compile(
    r"TOR_ENABLED=\{\{\s*"
    r"lookup\('tor_reachable',\s*application_id\)"
    r"\s*\|\s*lower\s*\}\}"
)


def _roles_with_tor_credential_test() -> dict[str, Path]:
    found = {}
    for template in sorted(ROLES_DIR.glob("svc-db-*/templates/test.env.j2")):
        if "TOR_ENABLED=" in read_text(str(template)):
            found[template.parent.parent.name] = template
    return found


class TestDbTorTransportGate(unittest.TestCase):
    def setUp(self) -> None:
        self.templates = _roles_with_tor_credential_test()
        self.assertTrue(self.templates, "no svc-db-* role renders TOR_ENABLED")

    def test_template_delegates_to_the_shared_lookup(self) -> None:
        for role, template in self.templates.items():
            with self.subTest(role=role):
                self.assertRegex(
                    read_text(str(template)),
                    _GATE_RE,
                    f"{role} must select its transport with "
                    f"lookup('tor_reachable', application_id) rather than a "
                    f"hand-rolled flag expression, so the credential test and "
                    f"the onion mapping (plugins/lookup/tor_ports.py) cannot "
                    f"drift apart.",
                )

    def test_gate_agrees_with_the_onion_mapping(self) -> None:
        base = get_merged_applications(roles_dir=str(ROLES_DIR))
        variants = get_variants(roles_dir=str(ROLES_DIR))

        for role in self.templates:
            configs = [("base", base[role])]
            configs += [
                (f"variant {i}", v) for i, v in enumerate(variants.get(role) or [])
            ]

            for label, config in configs:
                with self.subTest(role=role, config=label):
                    gate = is_reachable({role: config}, role)
                    ports = collect_exposed_ports({role: config}, [role])
                    self.assertEqual(
                        gate,
                        bool(ports),
                        f"{role} [{label}]: the credential test would use "
                        f"{'Tor' if gate else 'local'} transport while the deploy "
                        f"forwards {ports or 'no'} port(s) over the onion",
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
