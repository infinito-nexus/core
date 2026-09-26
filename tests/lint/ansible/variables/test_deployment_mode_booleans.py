"""The deployment mode is asked by name, not compared to a string.

``IS_COMPOSE_MODE`` and ``IS_SWARM_MODE`` say what the comparison meant, and
they say it once. Spelling the mode out against a quoted literal writes the
same predicate in a hundred places: a third mode, a renamed value or an
inverted default then has to be chased through all of them.

Both are real booleans under this Ansible, so a template writes
``{% if IS_SWARM_MODE %}`` without a ``| bool``.

Only ``group_vars/all/18_swarm.yml`` may compare, because that is where the
two are defined.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

DEFINITION = Path("group_vars/all/18_swarm.yml")
SUFFIXES = {".yml", ".yaml", ".j2", ".py", ".sh", ".tmpl"}
COMPARISON = re.compile(r"DEPLOYMENT_MODE\s*[!=]=\s*['\"](?P<mode>compose|swarm)['\"]")
REPLACEMENT = {
    ("==", "compose"): "IS_COMPOSE_MODE",
    ("==", "swarm"): "IS_SWARM_MODE",
    ("!=", "compose"): "not IS_COMPOSE_MODE",
    ("!=", "swarm"): "not IS_SWARM_MODE",
}


def _offenders() -> list[str]:
    found: list[str] = []
    for raw in sorted(iter_non_ignored_files()):
        path = Path(raw)
        if path.suffix not in SUFFIXES:
            continue
        relative = path.relative_to(PROJECT_ROOT)
        if relative == DEFINITION:
            continue
        try:
            lines = read_text(str(path)).splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            match = COMPARISON.search(line)
            if match:
                found.append(f"{relative}:{number}: {match.group(0)}")
    return found


class TestDeploymentModeBooleans(unittest.TestCase):
    def test_no_file_compares_the_mode_to_a_string(self) -> None:
        offenders = _offenders()

        self.assertEqual(
            offenders,
            [],
            f"{len(offenders)} comparison(s) spell out the deployment mode. Use "
            f"the named boolean instead:\n"
            + "\n".join(f"    {k[0]} '{k[1]}'  ->  {v}" for k, v in REPLACEMENT.items())
            + "\n\n"
            + "\n".join(offenders[:20]),
        )

    def test_the_definition_still_declares_both(self) -> None:
        declared = read_text(str(PROJECT_ROOT / DEFINITION))

        for name in ("IS_COMPOSE_MODE", "IS_SWARM_MODE"):
            self.assertIn(
                f"{name}:", declared, f"{DEFINITION} no longer defines {name}"
            )


if __name__ == "__main__":
    unittest.main()
