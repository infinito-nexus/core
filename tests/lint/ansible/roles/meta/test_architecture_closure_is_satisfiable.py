"""Hard-fail when a deploy row's architecture declarations cancel out.

``utils.github.variant.axes.row_architectures`` intersects the declaration of
the role under test with those of every role its variant deploys. An empty
intersection raises ``SystemExit`` from inside the row loop, so one
contradictory pair anywhere aborts the whole matrix build rather than the one
row, and it does so at dispatch time when the sweep is already queued.

The check short-circuits on the fact that intersecting fewer sets can only
yield more: if every declaration in the repository shares an architecture,
then no subset of them can be empty and no closure needs computing. Only when
that global intersection is empty does the lint go and resolve the per-variant
closures, so the normal case costs a few file reads instead of a plan per role.
"""

from __future__ import annotations

import unittest

from utils.github.variant.pools import ARCHITECTURES
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_architectures
from utils.roles.validation.invokable import list_invokable_app_ids

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def declarations() -> dict[str, list[str]]:
    """Every role that narrows its architectures, and to what."""
    found: dict[str, list[str]] = {}
    for role_dir in sorted(ROLES_DIR.iterdir()):
        if not (role_dir / ROLE_FILE_META_SERVICES).is_file():
            continue
        declared = get_role_architectures(role_dir.name)
        if declared:
            found[role_dir.name] = declared
    return found


def unsatisfiable_rows(declared: dict[str, list[str]]) -> list[str]:
    """Rows whose own closure leaves no architecture, as ``app#variant``.

    Args:
        declared: every role that narrows its architectures.
    """
    from cli.meta.ci.matrix import deployed_rounds

    narrowing = set(declared)
    broken: list[str] = []
    for app in sorted(list_invokable_app_ids()):
        for index, deploys in enumerate(deployed_rounds(app)):
            involved = narrowing.intersection({app, *deploys})
            if len(involved) < 2:
                continue
            allowed = set(ARCHITECTURES)
            for role in involved:
                allowed &= set(declared[role])
            if not allowed:
                names = ", ".join(
                    f"{r} ({'/'.join(declared[r])})" for r in sorted(involved)
                )
                broken.append(f"- {app}#{index}: {names}")
    return broken


class TestArchitectureClosureIsSatisfiable(unittest.TestCase):
    def test_no_row_declares_itself_out_of_every_architecture(self) -> None:
        declared = declarations()
        if not declared:
            self.skipTest("no role narrows its architectures")

        shared = set(ARCHITECTURES)
        for allowed in declared.values():
            shared &= set(allowed)
        if shared:
            return

        broken = unsatisfiable_rows(declared)
        self.assertEqual(
            broken,
            [],
            "These deploy rows pull in roles whose architecture declarations "
            "leave nothing in common, so `row_architectures` aborts the entire "
            "matrix build when the sweep reaches them:\n"
            + "\n".join(broken)
            + "\n\nFix: widen one of the declarations, or stop the variant from "
            "deploying both roles together.",
        )


if __name__ == "__main__":
    unittest.main()
