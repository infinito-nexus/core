"""Every pinned ``architectures`` has to say why it is pinned.

``architectures`` in ``meta/services.yml`` takes a role's rows out of part of
the deploy matrix, so the role stops being exercised where it is narrowed
away. That is sometimes correct - an upstream that publishes only amd64
cannot be scheduled on arm64 - and it is never self-evident from the three
lines it takes to write. Without a stated reason the next reader cannot tell
a pin that upstream forces from one that a long-gone build quirk left behind,
and the external architecture test can only say the pin disagrees with the
registry, never whether it should have existed.

The reason is unchecked prose. The gate is that a human had to write one.

Convention
==========
On the ``architectures`` line, or on the contiguous comment lines directly
above it, name the rule and the reason:

    # nocheck: architecture-pin  Reason: <what cannot run elsewhere>
    architectures:
      - amd64

Both markers are required, in either order. A role that stops needing the
pin deletes the declaration and this comment together; the external test
``test_image_architectures.py`` is what notices that moment, by failing once
every image the role pins publishes the architecture it narrows away.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import has_rule_with_reason
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_architectures

from . import PROJECT_ROOT

_RULE = "architecture-pin"
_ARCHITECTURES_KEY = re.compile(r"^\s+architectures:")
ROLES_DIR = PROJECT_ROOT / "roles"


def _declaration_lines(lines: list[str]) -> list[int]:
    """Return the 1-based lines on which ``architectures:`` is declared.

    Args:
        lines: the ``meta/services.yml`` lines.
    """
    return [
        number
        for number, line in enumerate(lines, start=1)
        if _ARCHITECTURES_KEY.match(line)
    ]


class TestArchitecturePinIsJustified(unittest.TestCase):
    def test_every_narrowed_role_states_why(self) -> None:
        offenders = []
        for services_file in sorted(ROLES_DIR.glob(f"*/{ROLE_FILE_META_SERVICES}")):
            role = services_file.parent.parent.name
            if not get_role_architectures(role):
                continue
            lines = read_text(str(services_file)).splitlines()
            declarations = _declaration_lines(lines)
            if not declarations:
                continue
            for line_no in declarations:
                if has_rule_with_reason(lines, line_no, _RULE):
                    continue
                offenders.append(
                    f"roles/{role}/{ROLE_FILE_META_SERVICES}:{line_no}: "
                    f"`architectures` narrows the deploy matrix without "
                    f"saying why"
                )
        self.assertEqual(
            [],
            offenders,
            "architecture pin(s) without a stated reason:\n"
            + "\n".join(f"  - {o}" for o in offenders)
            + f"\n\nAdd `# nocheck: {_RULE}  Reason: <what cannot run "
            "elsewhere>` on the declaration or directly above it, or drop "
            "the declaration if the pin is no longer needed.",
        )

    def test_the_scan_finds_the_roles_that_narrow(self) -> None:
        narrowed = {
            services_file.parent.parent.name
            for services_file in ROLES_DIR.glob(f"*/{ROLE_FILE_META_SERVICES}")
            if get_role_architectures(services_file.parent.parent.name)
        }
        unseen = sorted(
            role
            for role in narrowed
            if not _declaration_lines(
                read_text(str(ROLES_DIR / role / ROLE_FILE_META_SERVICES)).splitlines()
            )
        )
        self.assertEqual(
            [],
            unseen,
            "role(s) whose `architectures` the resolver reads but whose line "
            f"the scan does not find, so the rule passes vacuously: {unseen}",
        )


if __name__ == "__main__":
    unittest.main()
