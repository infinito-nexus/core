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
WORKTREE_DOWN_SKILL = "i8-worktree-down"
WORKTREE_DOWN_STATEMENTS = (
    "`make runner-status`",
    "`make runner-release job=<id>`",
    "never stops the\nmachine-wide infra runner",
)
TEST_SKILL = "i8-test"
RUNNER_STATEMENTS = (
    "shared test runner `infinito-test-<hash>`",
    "`make test-runner-status`",
    "`make runner-release job=<id>`",
)
ROUTINE_FILES = ("testing.py", "iterate/compose.py")
ROUTINE_STATEMENTS = (
    "shared test runner infinito-test-<hash>",
    "make test-runner-status",
    "make runner-release job=<id>",
)
COMPOSE_DOC = ("docs", "contributing", "artefact", "files", "compose.yml.md")
COMPOSE_DOC_STATEMENTS = (
    "`make test-runner-status`",
    "`INFINITO_STACK_NAME=<name>`",
    "`make runner-release job=<id>`",
    "`make runner-status`",
    "`make runner-cleanup-report`",
    "`make runner-count`",
    "always-on",
    "long-lived",
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
    "runner-status",
    "runner-release",
    "runner-count",
    "test-runner-down",
)
UNKNOWN_TARGET = "no-such-target"


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


class TestWorktreeDownReleasesHeldJobs(unittest.TestCase):
    def test_it_names_the_release_and_spares_the_runners(self) -> None:
        text = _skill(WORKTREE_DOWN_SKILL)
        self.assertEqual(missing(text, WORKTREE_DOWN_STATEMENTS), [])

    def test_a_skill_without_the_release_is_flagged(self) -> None:
        text = _skill(WORKTREE_DOWN_SKILL).replace(WORKTREE_DOWN_STATEMENTS[1], "")
        self.assertEqual(
            missing(text, WORKTREE_DOWN_STATEMENTS), [WORKTREE_DOWN_STATEMENTS[1]]
        )


class TestTestingGuidanceNamesTheRunnerAndRelease(unittest.TestCase):
    def test_the_test_skill_names_the_runner_and_the_release(self) -> None:
        self.assertEqual(missing(_skill(TEST_SKILL), RUNNER_STATEMENTS), [])

    def test_the_routines_hand_the_agent_the_runner_and_the_release(self) -> None:
        joined = "".join(
            read_text(str(PROJECT_ROOT / "agents" / "routines" / name))
            for name in ROUTINE_FILES
        )
        self.assertEqual(missing(joined, ROUTINE_STATEMENTS), [])

    def test_a_routine_without_the_release_is_flagged(self) -> None:
        text = read_text(str(PROJECT_ROOT / "agents" / "routines" / ROUTINE_FILES[1]))
        self.assertEqual(
            missing(text.replace(ROUTINE_STATEMENTS[2], ""), ROUTINE_STATEMENTS[2:]),
            [ROUTINE_STATEMENTS[2]],
        )

    def test_compose_doc_names_stack_kinds_pool_targets_and_override(self) -> None:
        text = read_text(str(PROJECT_ROOT.joinpath(*COMPOSE_DOC)))
        self.assertEqual(missing(text, COMPOSE_DOC_STATEMENTS), [])

    def test_a_compose_doc_without_the_override_is_flagged(self) -> None:
        text = read_text(str(PROJECT_ROOT.joinpath(*COMPOSE_DOC)))
        self.assertEqual(
            missing(
                text.replace(COMPOSE_DOC_STATEMENTS[1], ""), COMPOSE_DOC_STATEMENTS
            ),
            [COMPOSE_DOC_STATEMENTS[1]],
        )


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
            sorted({UNKNOWN_TARGET, *NAMED_TARGETS} - _targets()),
            [UNKNOWN_TARGET],
        )


if __name__ == "__main__":
    unittest.main()
