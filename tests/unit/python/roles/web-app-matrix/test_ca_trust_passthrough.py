"""Every CA path synapse binds must reach the matrix container at that path.

The mdad stack runs its own Docker daemon inside the matrix container, so a
bind source in ``matrix_synapse_container_extra_arguments`` is resolved in that
container's mount namespace rather than on the host. A path the compose service
never passes through therefore does not exist where synapse looks for it, and
``docker create`` refuses the unit before anything is logged about Matrix.

Run 34348821577 lost a job to exactly that: ``vars.yml.j2`` mounted
``CA_TRUST.bundle_host`` while ``services.yml.j2`` passed only
``CA_TRUST.cert_host``, and synapse crash-looped on "bind source path does not
exist". The templates are read as text because rendering them needs a full
Ansible context, and the invariant is about what the two files say to each
other, not about the values.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]
_MATRIX = PROJECT_ROOT / "roles/web-app-matrix/templates/flavor/ansible"

_BOUND_BY_SYNAPSE = re.compile(r"src='?\s*~?\s*CA_TRUST\.(\w+)")
_PASSED_THROUGH = re.compile(
    r"\{\{\s*CA_TRUST\.(\w+)\s*\}\}\s*:\s*\{\{\s*CA_TRUST\.(\w+)\s*\}\}"
)


class TestCaTrustPassthrough(unittest.TestCase):
    def test_every_ca_path_synapse_mounts_is_passed_through_at_the_same_path(
        self,
    ) -> None:
        wanted = set(_BOUND_BY_SYNAPSE.findall((_MATRIX / "vars.yml.j2").read_text()))
        self.assertTrue(
            wanted,
            "no CA_TRUST bind source found in vars.yml.j2 — the regex no longer "
            "matches how synapse's extra arguments are built, so this test has "
            "stopped guarding anything",
        )

        services = (_MATRIX / "services.yml.j2").read_text()
        same_path = {
            source
            for source, target in _PASSED_THROUGH.findall(services)
            if source == target
        }

        missing = sorted(wanted - same_path)
        self.assertFalse(
            missing,
            "synapse binds CA_TRUST."
            + ", CA_TRUST.".join(missing)
            + " inside the nested daemon, but services.yml.j2 does not pass "
            "it into the matrix container at the same absolute path. The "
            "nested daemon resolves the source in the container's namespace, "
            "so docker create fails with 'bind source path does not exist' "
            "and matrix-synapse never starts. Add "
            + " and ".join(
                f"`- {{{{ CA_TRUST.{name} }}}}:{{{{ CA_TRUST.{name} }}}}:ro`"
                for name in missing
            )
            + " to the self_signed block.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
