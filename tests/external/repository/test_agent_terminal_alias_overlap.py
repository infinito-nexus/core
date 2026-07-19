"""Verify agent conversation shortcuts do not collide with terminal aliases.

Both sources come from the generated ``.env`` (``make dotenv``): the
agent shortcut table at INFINITO_ALIAS_MD and the terminal aliases from
INFINITO_ALIAS_REPOSITORY (downloaded once per environment via
``utils.terminal_aliases``). A name present in both tables would make
the same token mean two different things depending on where the
operator types it.

This is an external test because the terminal aliases are fetched from
the repository host. A download failure without a warm cache emits a
warning and skips, matching the external-suite convention for upstream
outages.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.message import warning
from utils.cache.files import read_text
from utils.terminal_aliases import (
    alias_md_file,
    alias_repository,
    fetch_cached,
    local_alias_names,
    parse_alias_names,
)

ROW_RE = re.compile(r"^\|\s*`(?P<shortcut>[^`]+)`\s*\|")


class TestAgentTerminalAliasOverlap(unittest.TestCase):
    def test_agent_shortcuts_do_not_shadow_terminal_aliases(self):
        alias_md = alias_md_file()
        self.assertTrue(alias_md.is_file(), f"agent alias markdown missing: {alias_md}")
        agent_shortcuts = {
            match.group("shortcut")
            for line in read_text(str(alias_md)).splitlines()
            if (match := ROW_RE.match(line))
        }
        self.assertTrue(agent_shortcuts, f"No shortcut rows found in {alias_md}")

        repository = alias_repository()
        try:
            terminal_aliases = set(parse_alias_names(fetch_cached(repository)))
        except OSError as exc:
            warning(
                f"terminal aliases not fetchable from {repository} "
                f"and no cache present: {exc}"
            )
            self.skipTest(f"terminal aliases unavailable: {exc}")

        self.assertTrue(
            terminal_aliases,
            f"Aliases file from {repository} parsed to zero names",
        )

        all_aliases = terminal_aliases | set(local_alias_names())
        overlap = sorted(agent_shortcuts & all_aliases)
        self.assertFalse(
            overlap,
            "Agent shortcuts collide with terminal aliases (general repo "
            f"{repository} or the project's own aliases): {overlap}. "
            f"Rename the entries in {alias_md}.",
        )


if __name__ == "__main__":
    unittest.main()
