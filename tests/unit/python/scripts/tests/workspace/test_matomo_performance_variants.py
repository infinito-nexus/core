from __future__ import annotations

import subprocess
import unittest

from cli.administration.deploy.development.variant_select import parse_variant_csv
from utils.cache.applications import get_variants
from utils.cache.files import PROJECT_ROOT, read_text

COMMON = PROJECT_ROOT / "scripts" / "tests" / "workspace" / "utils" / "common.sh"
ROLES_DIR = str(PROJECT_ROOT / "roles")


def shell_value(script: str, name: str) -> str:
    """Args:
        script: bash text that defines *name* and may derive from it.
        name: the variable to print after *script* ran.

    Returns:
        The variable's value as bash expands it.
    """
    result = subprocess.run(
        ["bash", "-c", f'{script}\nprintf "%s" "${{{name}}}"'],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def performance_rounds(pins: str) -> tuple[list[int], int]:
    """Args:
        pins: the MATOMO_PERFORMANCE_VARIANTS value.

    Returns:
        The rounds 02_performance deploys and the round 03_reuse redeploys.
    """
    last = shell_value(
        f'MATOMO_PERFORMANCE_VARIANTS="{pins}"\n'
        'last_variant="${MATOMO_PERFORMANCE_VARIANTS##*,}"',
        "last_variant",
    )
    return parse_variant_csv(pins), int(last)


def pinned_value() -> str:
    lines = [
        line
        for line in read_text(str(COMMON)).splitlines()
        if line.startswith("MATOMO_PERFORMANCE_VARIANTS=")
    ]
    return shell_value(lines[0], "MATOMO_PERFORMANCE_VARIANTS")


def findings(pins: str, declared: int) -> list[str]:
    """Args:
        pins: the MATOMO_PERFORMANCE_VARIANTS value.
        declared: how many variants web-app-matomo declares.

    Returns:
        Why 02_performance or 03_reuse would address a round that is missing
        or that the sweep did not deploy last.
    """
    rounds, reused = performance_rounds(pins)
    found = [f"round {r} not declared" for r in rounds if r >= declared]
    if reused != rounds[-1]:
        found.append(f"03_reuse redeploys {reused}, the sweep ends on {rounds[-1]}")
    if len(rounds) > 2:
        found.append(f"{len(rounds)} rounds exceed the fedora workspace budget")
    return found


class TestMatomoPerformanceVariants(unittest.TestCase):
    def setUp(self) -> None:
        self.declared = len(
            get_variants(roles_dir=ROLES_DIR, readonly=True)["web-app-matomo"]
        )

    def test_the_pinned_sweep_fits_and_reuse_takes_its_last_round(self) -> None:
        self.assertEqual(findings(pinned_value(), self.declared), [])

    def test_negative_control_the_full_sweep_is_reported(self) -> None:
        full = ",".join(str(index) for index in range(self.declared))
        self.assertGreater(self.declared, 2)
        self.assertTrue(findings(full, self.declared))

    def test_negative_control_an_undeclared_round_is_reported(self) -> None:
        self.assertTrue(findings(f"0,{self.declared}", self.declared))


if __name__ == "__main__":
    unittest.main()
