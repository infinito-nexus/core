"""Lint guard for the repository's ``aliases`` file (Infinito.Nexus-specific
terminal aliases).

Rules enforced:

1. Every alias name starts with ``i8``.
2. Alias names are sorted ascending.
3. No more than two consonants stand next to each other in an alias name
   (digits count as separators, so ``i8`` never forms a cluster).
4. Every public Makefile target is invoked by at least one alias
   (full coverage).
5. Every ``m``/``make`` invocation inside an alias body references an
   existing Makefile target.
6. An alias whose body directly invokes a make target carries NO trailing
   comment (its description is derived from the Makefile at display time);
   every other alias MUST carry a trailing comment.
"""

from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

ALIASES_FILE = PROJECT_ROOT / "aliases"
MAKEFILE = PROJECT_ROOT / "Makefile"

VOWELS = frozenset("aeiou")
ALIAS_RE = re.compile(
    r"^alias\s+([^=]+)=(['\"])(?P<body>.*)\2(?:\s*#\s*(?P<comment>.*\S))?\s*$"
)
TARGET_RE = re.compile(r"^([a-z][a-z0-9-]*):")
MAKE_CALL_RE = re.compile(r"(?:^|[\s;&(])(?:m|make)\s+([a-z][a-z0-9-]*)")


def _makefile_targets() -> set[str]:
    return {
        match.group(1)
        for line in read_text(str(MAKEFILE)).splitlines()
        if (match := TARGET_RE.match(line))
    }


def _parse_aliases() -> list[tuple[str, str, str | None]]:
    parsed: list[tuple[str, str, str | None]] = []
    for line in read_text(str(ALIASES_FILE)).splitlines():
        if not line.startswith("alias "):
            continue
        match = ALIAS_RE.match(line)
        assert match, f"unparseable alias line: {line!r}"
        parsed.append(
            (match.group(1).strip(), match.group("body"), match.group("comment"))
        )
    return parsed


def _make_targets_in(body: str) -> set[str]:
    return set(MAKE_CALL_RE.findall(body))


def _has_consonant_cluster(name: str) -> bool:
    run = 0
    for char in name:
        if not char.isalpha():
            run = 0
            continue
        run = run + 1 if char.lower() not in VOWELS else 0
        if run > 2:
            return True
    return False


class TestInfinitoAliases(unittest.TestCase):
    def setUp(self):
        self.aliases = _parse_aliases()
        self.targets = _makefile_targets()

    def test_all_names_start_with_i8(self):
        bad = [name for name, _, _ in self.aliases if not name.startswith("i8")]
        self.assertFalse(bad, f"aliases not starting with 'i8': {bad}")

    def test_names_sorted_ascending(self):
        names = [name for name, _, _ in self.aliases]
        self.assertEqual(
            names, sorted(names), f"aliases not sorted; expected {sorted(names)}"
        )

    def test_no_consecutive_consonants(self):
        bad = [name for name, _, _ in self.aliases if _has_consonant_cluster(name)]
        self.assertFalse(
            bad, f"alias names with more than two adjacent consonants: {bad}"
        )

    def test_every_make_target_has_an_alias(self):
        covered: set[str] = set()
        for _, body, _ in self.aliases:
            covered |= _make_targets_in(body)
        missing = sorted(self.targets - covered)
        self.assertFalse(
            missing, f"{len(missing)} make target(s) without an alias: {missing}"
        )

    def test_make_calls_reference_valid_targets(self):
        invalid = [
            f"{name} -> m {target}"
            for name, body, _ in self.aliases
            for target in _make_targets_in(body)
            if target not in self.targets
        ]
        self.assertFalse(
            invalid, f"aliases invoking non-existent make targets: {invalid}"
        )

    def test_comment_presence_matches_make_usage(self):
        offenders: list[str] = []
        for name, body, comment in self.aliases:
            is_make = bool(_make_targets_in(body))
            if is_make and comment is not None:
                offenders.append(f"{name}: make alias MUST NOT carry a comment")
            if not is_make and comment is None:
                offenders.append(f"{name}: non-make alias MUST carry a comment")
        self.assertFalse(offenders, "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
