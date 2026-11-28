from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import MetaServicesShapeError, get_role_requires_devices

from . import ROLES_DIR, load_role_meta

KEY = "requires_devices"


def offenders(roles_dir: Path) -> list[str]:
    """Args:
        roles_dir: the ``roles`` directory to scan.

    Returns:
        One line per malformed ``requires_devices`` and per declaration on an
        entity other than the primary one, which the deploy runner never reads.
    """
    found = []
    for services_file in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        role_dir = services_file.parent.parent
        role = role_dir.name
        services = load_role_meta(services_file)
        if not isinstance(services, dict):
            continue
        primary = entity_name(role) or role
        found.extend(
            f"roles/{role}/{ROLE_FILE_META_SERVICES}: {entity}.{KEY} is not on "
            f"the primary entity {primary}"
            for entity, entry in services.items()
            if entity != primary and isinstance(entry, dict) and KEY in entry
        )
        try:
            get_role_requires_devices(role_dir, role_name=role)
        except MetaServicesShapeError as exc:
            found.append(str(exc))
    return found


class TestRequiresDevices(unittest.TestCase):
    def test_every_declaration_is_well_formed_and_on_the_primary_entity(self) -> None:
        found = offenders(ROLES_DIR)
        self.assertEqual(
            [],
            found,
            f"malformed or misplaced {KEY}:\n"
            + "\n".join(f"  - {line}" for line in found)
            + f"\n\n{KEY} is a non-empty list of distinct device paths below /dev "
            "on the role's primary entity in meta/services.yml.",
        )

    def test_the_scan_reports_a_malformed_and_a_misplaced_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_dir = Path(tmp)
            fixtures = {
                "svc-virt-scalar": "scalar:\n  requires_devices: /dev/kvm\n",
                "svc-virt-aside": "aside:\n  lifecycle: alpha\nhelper:\n"
                "  requires_devices:\n    - /dev/kvm\n",
                "svc-virt-sound": "sound:\n  requires_devices:\n    - /dev/kvm\n",
            }
            for role, body in fixtures.items():
                meta = roles_dir / role / "meta"
                meta.mkdir(parents=True)
                (roles_dir / role / ROLE_FILE_META_SERVICES).write_text(
                    body, encoding="utf-8"
                )
            found = offenders(roles_dir)

        self.assertEqual(len(found), 2, found)
        self.assertIn("svc-virt-scalar", found[1])
        self.assertIn("helper.requires_devices is not on the primary entity", found[0])
        self.assertFalse(any("svc-virt-sound" in line for line in found), found)


if __name__ == "__main__":
    unittest.main()
