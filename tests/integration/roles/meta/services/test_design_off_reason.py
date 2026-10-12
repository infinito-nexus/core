"""Every ``web-app-`` and ``web-svc-`` role declares a ``design`` entry in
``meta/services.yml``, and a role that switches it off says why.

``design.enabled: false`` keeps a role out of the design queue
(``make design-queue``) and off the shared CSS and the design script. The
``design:`` line or the contiguous comment lines directly above it carry the
marker and the reason on one comment line:

    # nocheck: design-off  Reason: <why the role has no UI to design>
    design:
      enabled: false
      shared: false

``web-svc-design``, the provider, is exempt.
"""

from __future__ import annotations

import re
import unittest

from cli.meta.roles.design import DESIGN_ENTITY, UI_PREFIXES, design_disabled
from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.roles.applications.services.registry import read_yaml_file
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "design-off"
_REASON = re.compile(r"#.*\breason\b\s*:\s*\S", re.IGNORECASE)
_DESIGN_KEY = re.compile(rf"^{DESIGN_ENTITY}\s*:")


def justified(lines: list[str]) -> bool:
    """Whether the top-level ``design:`` key carries the marker and a reason.

    Args:
        lines: Lines of a ``meta/services.yml``.

    Returns:
        ``True`` when the key line or the contiguous comment lines directly
        above it hold ``# nocheck: design-off`` and ``Reason: <text>``.
    """
    index = next((i for i, line in enumerate(lines) if _DESIGN_KEY.match(line)), None)
    if index is None:
        return False
    block = [lines[index]]
    above = index - 1
    while above >= 0 and lines[above].lstrip().startswith("#"):
        block.append(lines[above])
        above -= 1
    has_rule = any(line_has_rule(line, _RULE) for line in block)
    return has_rule and any(_REASON.search(line) for line in block)


class TestDesignOffReason(unittest.TestCase):
    def test_every_ui_role_declares_design_and_justifies_switching_it_off(
        self,
    ) -> None:
        offenders: list[str] = []
        roles_dir = PROJECT_ROOT / "roles"
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
            role = role_dir.name
            services = role_dir / ROLE_FILE_META_SERVICES
            if not role.startswith(UI_PREFIXES) or not services.is_file():
                continue
            if get_entity_name(role) == DESIGN_ENTITY:
                continue
            if DESIGN_ENTITY not in read_yaml_file(services):
                offenders.append(f"{role}: declares no '{DESIGN_ENTITY}' entry")
                continue
            if design_disabled(role_dir) and not justified(
                read_text(str(services)).splitlines()
            ):
                offenders.append(
                    f"{role}: 'design.enabled: false' without "
                    f"'# nocheck: {_RULE}  Reason: ...'"
                )

        if offenders:
            self.fail(
                "Every web-app-/web-svc- role declares a 'design' entry in "
                "meta/services.yml. A role that sets 'enabled: false' leaves the "
                "design queue and the shared CSS, so it MUST say why: put "
                f"'# nocheck: {_RULE}  Reason: <why there is no UI to design>' on "
                "the 'design:' line or the comment lines directly above it.\n\n"
                "Offenders:\n" + "\n".join(f"- {line}" for line in offenders)
            )

    def test_reason_detection(self) -> None:
        cases = {
            "marker and reason above": (
                [f"# nocheck: dynamic-flag, {_RULE}  Reason: no page", "design:"],
                True,
            ),
            "marker without reason": ([f"# nocheck: {_RULE}", "design:"], False),
            "reason without marker": (
                ["# nocheck: dynamic-flag  Reason: x", "design:"],
                False,
            ),
            "blank line breaks the block": (
                [f"# nocheck: {_RULE}  Reason: no page", "", "design:"],
                False,
            ),
            "marker and reason on the key line": (
                [f"design:  # nocheck: {_RULE}  Reason: no page"],
                True,
            ),
        }
        for name, (lines, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(justified(lines), expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
