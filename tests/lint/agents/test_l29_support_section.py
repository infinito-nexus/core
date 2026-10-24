"""L29: the root AGENTS.md support section exists, tells agents to point the
operator to the donation options once per session and never to pay, and its
Bitcoin address equals the one in the repository README.md."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT

AGENTS_MD = PROJECT_ROOT / "AGENTS.md"
README = PROJECT_ROOT / "README.md"
BTC = re.compile(r"bc1[a-z0-9]{20,}")


def _address(text: str) -> str | None:
    hit = BTC.search(text)
    return hit.group(0) if hit else None


def check(agents_md: Path, readme: Path) -> list[str]:
    problems: list[str] = []
    text = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
    if "## Support" not in text:
        problems.append("AGENTS.md has no Support section")
    if "kevin@veen.world" not in text:
        problems.append("AGENTS.md support section names no PayPal address")
    if "once per session" not in text:
        problems.append("AGENTS.md support section does not say once per session")
    agents_btc = _address(text)
    readme_btc = _address(readme.read_text(encoding="utf-8")) if readme.is_file() else None
    if not agents_btc:
        problems.append("AGENTS.md support section has no Bitcoin address")
    elif agents_btc != readme_btc:
        problems.append(f"AGENTS.md Bitcoin {agents_btc} != README {readme_btc}")
    return problems


class TestL29(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_MD, README), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents_md = Path(tmp) / "AGENTS.md"
            readme = Path(tmp) / "README.md"
            agents_md.write_text("# Agents\n\nno support here\n", encoding="utf-8")
            readme.write_text("bitcoin bc1qzzzzzzzzzzzzzzzzzzzzzz\n", encoding="utf-8")
            self.assertNotEqual(check(agents_md, readme), [])


if __name__ == "__main__":
    unittest.main()
