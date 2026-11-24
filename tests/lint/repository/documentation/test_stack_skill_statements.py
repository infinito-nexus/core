from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text

SKILLS_DIR = PROJECT_ROOT / "agents" / "skills"
MAKEFILE = PROJECT_ROOT / "Makefile"
TARGET_RE = re.compile(r"^([a-z][a-z0-9-]*):")
GATE_SKILLS = ("i8-quality", "i8-quality-high")
GATE_STATEMENTS = (
    "shared test runner `infinito-test-<hash>`",
    "starts no deploy stack",
    "`make test-runner-status`",
)
CLEANUP_SKILL = "i8-cleanup"
CLEANUP_STATEMENTS = (
    "never a candidate",
    "its network `infinito-infra`",
    "`DIR_CACHE`",
    "MUST NOT remove a pool runner, a held job or a job stack",
    "`make build-cleanup`",
    "`make runner-cleanup-report`",
    "`make cache-evict`",
)
CLEANUP_FORBIDDEN = ("infinito-nexus-core_default",)
NEVER_HEADING = "## Never"
WIPE = "make clean-cache"
NAMED_TARGETS = (
    "test-runner-status",
    "build-cleanup",
    "runner-cleanup-report",
    "cache-evict",
)


def _skill(name: str) -> str:
    return read_text(str(SKILLS_DIR / name / "SKILL.md"))


def _targets() -> set[str]:
    return {
        match.group(1)
        for line in read_text(str(MAKEFILE)).splitlines()
        if (match := TARGET_RE.match(line))
    }


def missing(text: str, statements: tuple[str, ...]) -> list[str]:
    """Args:
        text: a skill file.
        statements: the phrases the skill must carry.

    Returns:
        The phrases absent from the text.
    """
    return [statement for statement in statements if statement not in text]


def present(text: str, forbidden: tuple[str, ...]) -> list[str]:
    """Args:
        text: a skill file.
        forbidden: the phrases the skill must not carry.

    Returns:
        The forbidden phrases found in the text.
    """
    return [phrase for phrase in forbidden if phrase in text]


def wipe_offered(text: str) -> bool:
    """Args:
        text: the cleanup skill.

    Returns:
        Whether the cache wipe appears anywhere but under the Never heading.
    """
    offered, _, _ = text.partition(NEVER_HEADING)
    return WIPE in offered


class TestGateSkillsNameTheTestRunner(unittest.TestCase):
    def test_each_gate_skill_states_the_runner_and_its_target(self) -> None:
        for name in GATE_SKILLS:
            with self.subTest(skill=name):
                self.assertEqual(missing(_skill(name), GATE_STATEMENTS), [])

    def test_a_gate_skill_without_the_runner_statement_is_flagged(self) -> None:
        text = _skill(GATE_SKILLS[0]).replace(GATE_STATEMENTS[1], "")
        self.assertEqual(missing(text, GATE_STATEMENTS), [GATE_STATEMENTS[1]])


class TestCleanupSkillStacks(unittest.TestCase):
    def test_the_cleanup_skill_states_every_stack_rule(self) -> None:
        text = _skill(CLEANUP_SKILL)
        self.assertEqual(missing(text, CLEANUP_STATEMENTS), [])
        self.assertEqual(present(text, CLEANUP_FORBIDDEN), [])
        self.assertFalse(wipe_offered(text))

    def test_a_dropped_pool_rule_is_flagged(self) -> None:
        text = _skill(CLEANUP_SKILL).replace(CLEANUP_STATEMENTS[3], "")
        self.assertEqual(missing(text, CLEANUP_STATEMENTS), [CLEANUP_STATEMENTS[3]])

    def test_the_shared_default_network_is_flagged(self) -> None:
        text = _skill(CLEANUP_SKILL) + "\n- `infinito-nexus-core_default`\n"
        self.assertEqual(present(text, CLEANUP_FORBIDDEN), list(CLEANUP_FORBIDDEN))

    def test_a_cache_wipe_offered_before_the_never_list_is_flagged(self) -> None:
        text = _skill(CLEANUP_SKILL).replace(
            NEVER_HEADING, f"Free space with `{WIPE}`.\n\n{NEVER_HEADING}", 1
        )
        self.assertTrue(wipe_offered(text))


class TestNamedTargetsExist(unittest.TestCase):
    def test_every_target_the_skills_name_exists(self) -> None:
        self.assertEqual(sorted(set(NAMED_TARGETS) - _targets()), [])

    def test_an_unknown_target_is_flagged(self) -> None:
        self.assertEqual(
            sorted({"runner-release", *NAMED_TARGETS} - _targets()),
            ["runner-release"],
        )


if __name__ == "__main__":
    unittest.main()
