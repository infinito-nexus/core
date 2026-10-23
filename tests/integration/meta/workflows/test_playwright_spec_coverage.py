"""Integration: every Playwright spec of a tested role is triggered somewhere.

A spec that no row of the sweep reaches is dead weight that still reads as
coverage: the file is there, the lint that demands it is satisfied, and
nothing ever runs it. The matrix cuts rows for redundancy and for budget, so
the set of triggered specs is a property of the whole sweep rather than of any
single role, and only a sweep-wide assertion can hold it.

Specs of roles outside the tested lifecycle envelope are excluded, not
missing: the sweep leaves an eol, deprecated or pre-alpha role out on purpose.
"""

from __future__ import annotations

import unittest

from cli.meta.ci import matrix, query
from utils import PROJECT_ROOT
from utils.github.variant import axes, network, pools, vpn
from utils.roles.display import display_names
from utils.roles.playwright_coverage import (
    chunk_index,
    classify,
    first_rows,
    specs_by_role,
)


def _coverage():
    codec = display_names()
    entries = matrix.entries_of(
        modes=query.resolve_modes(query.ALL_MODES),
        whitelist=codec.decode_list(""),
        priority=codec.decode_list(""),
        lifecycles="",
        sweep=axes.resolve_sweep(),
        network_input=network.resolve_network_input(None),
        vpn_mode=vpn.resolve_vpn_mode(None),
        distros=pools.resolve_distros(""),
        filesystems=pools.resolve_filesystems(""),
        architectures=pools.resolve_architectures(""),
    )
    plan = matrix.chunks_of(entries, matrix.resolve_offset(None))
    roles_dir = PROJECT_ROOT / "roles"
    return classify(
        specs_by_role(roles_dir), first_rows(entries), chunk_index(plan), roles_dir
    )


class TestPlaywrightSpecCoverage(unittest.TestCase):
    def test_every_spec_of_a_tested_role_is_triggered(self) -> None:
        coverage = _coverage()
        self.assertEqual(
            [],
            coverage.uncovered,
            f"{len(coverage.uncovered)} Playwright spec(s) of roles inside the "
            "tested lifecycles are never triggered by any row of the sweep. "
            "Give the role a row, or retire the spec:\n"
            + "\n".join(f"  - {role}: {spec}" for role, spec in coverage.uncovered),
        )

    def test_the_sweep_triggers_specs_at_all(self) -> None:
        coverage = _coverage()
        self.assertTrue(
            coverage.triggered,
            "no Playwright spec is triggered at all, which means the sweep or "
            "the spec discovery broke rather than the coverage improving",
        )
