"""L27: no secret value lives in agents/. A placeholder like ${key} is a
reference, not a secret; this catches a real private key, cloud key or a
literal password or token that slipped into the tree."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import AGENTS_DIR

PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"(?i)\b(?:password|secret|api_key|token)\s*[:=]\s*['\"][^'\"${}\s]{12,}['\"]"),
)


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".md", ".yml", ".yaml", ".json"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in PATTERNS:
            if pattern.search(text):
                problems.append(f"{path.relative_to(root)}: possible secret value")
                break
    return problems


class TestL27(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(AGENTS_DIR), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "leak.yml").write_text(
                'api_key: "AKIAIOSFODNN7EXAMPLE1"\n', encoding="utf-8"
            )
            self.assertNotEqual(check(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
