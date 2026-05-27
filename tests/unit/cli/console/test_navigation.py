import unittest

from cli.console import navigation
from cli.console.constants import PROMPT_PREFIX

DOTDOT = ".."  # nocheck: project-root-import  REPL nav segment, not path construction
DOTDOT_DOTDOT = (
    "../.."  # nocheck: project-root-import  REPL nav segment, not path construction
)


class TestNormalize(unittest.TestCase):
    def test_empty_argv_becomes_help(self):
        self.assertEqual(navigation.normalize([]), ["--help"])

    def test_strips_cli_prefix(self):
        self.assertEqual(
            navigation.normalize(["cli", "build", "tree"]), ["build", "tree"]
        )

    def test_help_alias_lowercase(self):
        self.assertEqual(navigation.normalize(["help"]), ["--help"])

    def test_help_alias_question_mark(self):
        self.assertEqual(navigation.normalize(["?"]), ["--help"])

    def test_help_alias_h(self):
        self.assertEqual(navigation.normalize(["h"]), ["--help"])

    def test_help_alias_preserves_following_args(self):
        self.assertEqual(navigation.normalize(["help", "meta"]), ["--help", "meta"])

    def test_pass_through_unknown(self):
        self.assertEqual(navigation.normalize(["meta", "env"]), ["meta", "env"])


class TestIsCategory(unittest.TestCase):
    def test_empty_path_is_root_category(self):
        self.assertTrue(navigation.is_category([]))

    def test_known_top_level_category(self):
        self.assertTrue(navigation.is_category(["administration"]))

    def test_reserved_core_dir_is_not_category(self):
        self.assertFalse(navigation.is_category(["core"]))

    def test_unknown_path_is_not_category(self):
        self.assertFalse(navigation.is_category(["does-not-exist"]))

    def test_leaf_command_is_not_category(self):
        # cli/meta/env has __main__.py so it executes; cd-ing into it is
        # not allowed.
        self.assertFalse(navigation.is_category(["meta", "env"]))


class TestResolveCd(unittest.TestCase):
    def test_empty_target_resolves_to_root(self):
        self.assertEqual(navigation.resolve_cd(["administration"], ""), [])

    def test_slash_resolves_to_root(self):
        self.assertEqual(navigation.resolve_cd(["administration"], "/"), [])

    def test_absolute_target(self):
        self.assertEqual(
            navigation.resolve_cd(["meta"], "/administration"), ["administration"]
        )

    def test_relative_segment_appends(self):
        self.assertEqual(
            navigation.resolve_cd([], "administration"), ["administration"]
        )

    def test_dotdot_pops_one_level(self):
        self.assertEqual(navigation.resolve_cd(["administration"], DOTDOT), [])

    def test_dotdot_at_root_stays_at_root(self):
        self.assertEqual(navigation.resolve_cd([], DOTDOT), [])

    def test_dotdot_chain_pops_multiple_levels(self):
        self.assertEqual(
            navigation.resolve_cd(["administration", "deploy"], DOTDOT_DOTDOT), []
        )

    def test_invalid_segment_returns_none(self):
        self.assertIsNone(navigation.resolve_cd([], "does-not-exist"))


class TestPrompt(unittest.TestCase):
    def test_root_prompt(self):
        self.assertEqual(navigation.prompt([]), f"{PROMPT_PREFIX}infinito> ")

    def test_nested_prompt(self):
        self.assertEqual(
            navigation.prompt(["administration", "deploy"]),
            f"{PROMPT_PREFIX}infinito administration deploy> ",
        )


class TestIsNavigationToken(unittest.TestCase):
    def test_slash_alone(self):
        self.assertTrue(navigation.is_navigation_token("/"))

    def test_dotdot_alone(self):
        self.assertTrue(navigation.is_navigation_token(DOTDOT))

    def test_absolute_path(self):
        self.assertTrue(navigation.is_navigation_token("/administration"))

    def test_relative_with_dotdot_prefix(self):
        self.assertTrue(navigation.is_navigation_token("../meta"))

    def test_path_with_slash(self):
        self.assertTrue(navigation.is_navigation_token("administration/deploy"))

    def test_plain_token_is_not_nav(self):
        self.assertFalse(navigation.is_navigation_token("administration"))

    def test_empty_is_not_nav(self):
        self.assertFalse(navigation.is_navigation_token(""))


class TestResolveArgv(unittest.TestCase):
    def test_relative_when_command_exists_under_current(self):
        self.assertEqual(
            navigation.resolve_argv(["administration"], ["deploy"]),
            ["administration", "deploy"],
        )

    def test_absolute_fallback_when_command_missing_under_current(self):
        self.assertEqual(
            navigation.resolve_argv(["administration"], ["meta", "env"]),
            ["meta", "env"],
        )

    def test_flag_first_always_prepends_current(self):
        self.assertEqual(
            navigation.resolve_argv(["administration"], ["--help"]),
            ["administration", "--help"],
        )

    def test_root_passes_through(self):
        self.assertEqual(
            navigation.resolve_argv([], ["meta", "env"]),
            ["meta", "env"],
        )


class TestCommandExists(unittest.TestCase):
    def test_known_subpackage(self):
        self.assertTrue(navigation.command_exists([], "administration"))

    def test_unknown_token(self):
        self.assertFalse(navigation.command_exists([], "does-not-exist"))

    def test_reserved_at_root_rejected(self):
        self.assertFalse(navigation.command_exists([], "core"))


if __name__ == "__main__":
    unittest.main()
