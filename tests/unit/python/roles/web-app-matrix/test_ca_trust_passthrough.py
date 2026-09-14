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

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_ROLE = PROJECT_ROOT / "roles/web-app-matrix"
_MATRIX = _ROLE / "templates/flavor/ansible"
_VARS = _ROLE / ROLE_FILE_VARS_MAIN
_CA_GATE = "MATRIX_CA_INJECTED"

_BOUND_BY_SYNAPSE = re.compile(r"src='?\s*~?\s*CA_TRUST\.(\w+)")
_PASSED_THROUGH = re.compile(
    r"\{\{\s*CA_TRUST\.(\w+)\s*\}\}\s*:\s*\{\{\s*CA_TRUST\.(\w+)\s*\}\}"
)


class TestCaTrustPassthrough(unittest.TestCase):
    def test_every_ca_path_synapse_mounts_is_passed_through_at_the_same_path(
        self,
    ) -> None:
        wanted = set(_BOUND_BY_SYNAPSE.findall(read_text(str(_MATRIX / "vars.yml.j2"))))
        self.assertTrue(
            wanted,
            "no CA_TRUST bind source found in vars.yml.j2 — the regex no longer "
            "matches how synapse's extra arguments are built, so this test has "
            "stopped guarding anything",
        )

        services = read_text(str(_MATRIX / "services.yml.j2"))
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
            + " to the ca_injected block.",
        )

    def test_the_ca_blocks_are_gated_by_the_predicate_that_provisions_them(
        self,
    ) -> None:
        drift = (
            "sys-svc-compose-ca provisions the CA material for exactly this "
            "predicate, while TLS_MODE is global: on an onion deployment TLS "
            "is off per app, the CA is never written, and compose bind-mounts "
            "a path docker then creates as a directory. The restart once the "
            "file appears fails with 'not a directory' (run 34653754175, "
            "Matrix#1)"
        )
        self.assertIn(
            f"{_CA_GATE}: \"{{{{ lookup('ca_injected', application_id) | bool }}}}\"",
            read_text(str(_VARS)),
            drift,
        )
        for name in ("services.yml.j2", "vars.yml.j2"):
            with self.subTest(template=name):
                template = read_text(str(_MATRIX / name))
                gate = next(
                    line
                    for line in template.splitlines()
                    if "CA_TRUST" in template and line.strip().startswith("{% if ")
                    if _CA_GATE in line or "TLS_MODE" in line
                )
                self.assertIn(_CA_GATE, gate, drift)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
