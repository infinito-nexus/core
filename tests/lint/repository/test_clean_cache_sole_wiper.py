from __future__ import annotations

import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text, repository_files

WIPER = "scripts/system/cache/clean.sh"
TARGET = "clean-cache"
SCANNED_PREFIXES = (
    "scripts/",
    "cli/",
    "utils/",
    "roles/",
    ".github/",
    "compose/",
    "Makefile",
)
SCANNED_SUFFIXES = (".sh", ".py", ".yml", ".yaml", ".j2", "Makefile")
_HEADER = re.compile(r"^(?P<name>[A-Za-z0-9_./%-]+)\s*:(?!=)(?P<prereqs>.*)$")
_CALLS_TARGET = re.compile(
    r"(?:\bmake\b|\$\(MAKE\)|\"\$\(MAKE\)\")\s+(?:-\S+\s+)*clean-cache\b"
)
_ARGV_TARGET = re.compile(r"[\"']clean-cache[\"']")
_CACHE_ROOT = r"(INFINITO_CACHE_[A-Z_]*(HOST_PATH|_DIR)|INFINITO_TOOLS_MODELS_HOST_PATH|DIR_CACHE|/var/cache/infinito)"
_REMOVES_ROOT = re.compile(rf"(\brm\s+-[A-Za-z]*[rR]|\brmtree\b).*{_CACHE_ROOT}")


def _targets(makefile: str) -> dict[str, tuple[str, str]]:
    """Args:
        makefile: the text of a Makefile.

    Returns:
        Every target with its prerequisite list and its recipe text.
    """
    targets: dict[str, tuple[str, str]] = {}
    current = ""
    for line in makefile.splitlines():
        if line.startswith("\t") and current:
            prereqs, recipe = targets[current]
            targets[current] = (prereqs, f"{recipe}{line}\n")
            continue
        match = _HEADER.match(line)
        if match and not line.startswith((".PHONY", "#")):
            current = match.group("name")
            targets[current] = (match.group("prereqs"), "")
        elif not line.startswith("\t"):
            current = ""
    return targets


def _scanned() -> list[str]:
    return [
        rel
        for rel in repository_files()
        if rel.startswith(SCANNED_PREFIXES)
        and rel.endswith(SCANNED_SUFFIXES)
        and rel != WIPER
    ]


class TestCleanCacheIsTheSoleWiper(unittest.TestCase):
    def test_only_clean_cache_runs_the_wiper(self) -> None:
        targets = _targets(read_text(str(PROJECT_ROOT / "Makefile")))
        self.assertIn(WIPER, targets[TARGET][1])
        runners = sorted(
            name for name, (_, recipe) in targets.items() if WIPER in recipe
        )
        self.assertEqual(runners, [TARGET])

    def test_no_other_target_depends_on_or_calls_clean_cache(self) -> None:
        targets = _targets(read_text(str(PROJECT_ROOT / "Makefile")))
        callers = sorted(
            name
            for name, (prereqs, recipe) in targets.items()
            if name != TARGET
            and (
                re.search(r"(?<![\w-])clean-cache(?![\w-])", prereqs)
                or _CALLS_TARGET.search(recipe)
            )
        )
        self.assertEqual(callers, [])

    def test_no_script_calls_the_wiper_or_the_target(self) -> None:
        offenders = []
        for rel in _scanned():
            if rel == "Makefile":
                continue
            text = read_text(str(PROJECT_ROOT / rel))
            calls = _ARGV_TARGET if rel.endswith(".py") else _CALLS_TARGET
            if WIPER in text or calls.search(text):
                offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_no_other_script_removes_a_cache_directory(self) -> None:
        offenders = [
            f"{rel}:{number}"
            for rel in _scanned()
            for number, line in enumerate(
                read_text(str(PROJECT_ROOT / rel)).splitlines(), 1
            )
            if _REMOVES_ROOT.search(line)
        ]
        self.assertEqual(offenders, [])

    def test_the_detectors_catch_a_second_wiper(self) -> None:
        makefile = (
            "clean-cache:\n\t@bash scripts/system/cache/clean.sh\n"
            "reset: clean-cache\n\t@true\n"
            "purge:\n\t@$(MAKE) clean-cache\n"
            "wipe:\n\t@bash scripts/system/cache/clean.sh\n"
        )
        targets = _targets(makefile)
        self.assertEqual(
            sorted(name for name, (_, recipe) in targets.items() if WIPER in recipe),
            ["clean-cache", "wipe"],
        )
        self.assertIsNotNone(
            re.search(r"(?<![\w-])clean-cache(?![\w-])", targets["reset"][0])
        )
        self.assertIsNotNone(_CALLS_TARGET.search(targets["purge"][1]))
        self.assertIsNotNone(
            _ARGV_TARGET.search('subprocess.run(["make", "clean-cache"], check=True)')
        )
        self.assertIsNone(
            _ARGV_TARGET.search("``make clean-cache`` removes four of these entries")
        )
        self.assertIsNotNone(
            _REMOVES_ROOT.search('rm -rf -- "${INFINITO_CACHE_SHARED_HOST_PATH}"')
        )
        self.assertIsNone(
            _REMOVES_ROOT.search('rm -f -- "${INFINITO_CACHE_SHARED_HOST_PATH}/x.lock"')
        )


if __name__ == "__main__":
    unittest.main()
