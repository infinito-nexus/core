"""Main-loop integration tests for the console REPL.

Per-module concerns live in their own test files:
  - test_navigation.py — path resolve, normalize, prompt, category checks
  - test_runner.py     — subprocess dispatch + clear_screen
  - test_ls.py         — `ls` rendering + truncate
"""

import io
import unittest
from unittest.mock import patch

from cli.console import repl
from cli.console.constants import PROMPT_PREFIX

DOTDOT = ".."  # nocheck: project-root-import  REPL nav segment, not path construction
DOTDOT_DOTDOT = (
    "../.."  # nocheck: project-root-import  REPL nav segment, not path construction
)


class _MainLoopHarness:
    def _run_with_inputs(self, inputs):
        captured_calls = []
        captured_prompts = []

        def fake_input(prompt):
            captured_prompts.append(prompt)
            if not inputs:
                raise EOFError
            value = inputs.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

        def fake_run_cli(argv, *, current=None):
            captured_calls.append(argv)
            return 0

        with (
            patch("builtins.input", side_effect=fake_input),
            patch("cli.console.repl._run_cli", side_effect=fake_run_cli),
            patch("sys.stdout", new_callable=io.StringIO) as out,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            rc = repl.main()
        return rc, captured_calls, captured_prompts, out.getvalue()


class TestExitPaths(_MainLoopHarness, unittest.TestCase):
    def test_eof_exits_cleanly(self):
        rc, calls, _, _ = self._run_with_inputs([])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_exit_token(self):
        rc, calls, _, _ = self._run_with_inputs(["exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_quit_token(self):
        rc, _calls, _, _ = self._run_with_inputs(["quit"])
        self.assertEqual(rc, 0)

    def test_vim_style_quit(self):
        rc, _calls, _, _ = self._run_with_inputs([":q"])
        self.assertEqual(rc, 0)


class TestInputHandling(_MainLoopHarness, unittest.TestCase):
    def test_blank_input_is_skipped(self):
        rc, calls, _, _ = self._run_with_inputs(["", "   ", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_keyboard_interrupt_does_not_exit(self):
        rc, calls, _, _ = self._run_with_inputs([KeyboardInterrupt(), "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_command_is_normalized_and_dispatched(self):
        rc, calls, _, _ = self._run_with_inputs(["cli meta env", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["meta", "env"]])

    def test_help_alias_is_dispatched_as_help_flag(self):
        rc, calls, _, _ = self._run_with_inputs(["help", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["--help"]])

    def test_shlex_parse_error_is_caught(self):
        rc, calls, _, _ = self._run_with_inputs(["echo 'unterminated", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])


class TestBanner(_MainLoopHarness, unittest.TestCase):
    def test_banner_is_printed_once(self):
        _, _, _, out = self._run_with_inputs(["exit"])
        self.assertEqual(out.count("infinito.nexus console"), 1)
        self.assertIn(repl.WEB_URL, out)
        self.assertIn(repl.DOCS_URL, out)
        self.assertIn(repl.LICENSE_NAME, out)
        self.assertIn(repl.LICENSE_URL, out)
        self.assertIn(repl.AUTHOR, out)


class TestNavigation(_MainLoopHarness, unittest.TestCase):
    def test_bare_category_cds_without_dispatch(self):
        rc, calls, prompts, _ = self._run_with_inputs(["administration", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn(f"{PROMPT_PREFIX}infinito administration> ", prompts)

    def test_command_inside_category_prefixes_path(self):
        rc, calls, _, _ = self._run_with_inputs(
            ["administration", "deploy --help", "exit"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["administration", "deploy", "--help"]])

    def test_command_falls_back_to_absolute_when_not_in_current(self):
        rc, calls, _, _ = self._run_with_inputs(["administration", "meta env", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["meta", "env"]])

    def test_slash_jumps_to_root(self):
        rc, calls, prompts, _ = self._run_with_inputs(["administration", "/", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito> ")

    def test_dotdot_pops_one_level(self):
        rc, _, prompts, _ = self._run_with_inputs(["administration", DOTDOT, "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito> ")

    def test_dotdot_chain_pops_multiple_levels(self):
        rc, _, prompts, _ = self._run_with_inputs(
            ["/administration/deploy", DOTDOT_DOTDOT, "exit"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito> ")

    def test_absolute_path_navigates(self):
        rc, _, prompts, _ = self._run_with_inputs(["/administration/deploy", "exit"])
        self.assertEqual(rc, 0)
        self.assertIn(f"{PROMPT_PREFIX}infinito administration deploy> ", prompts)

    def test_relative_path_with_slashes(self):
        rc, _, prompts, _ = self._run_with_inputs(["administration", "../meta", "exit"])
        self.assertEqual(rc, 0)
        self.assertIn(f"{PROMPT_PREFIX}infinito meta> ", prompts)

    def test_executable_leaf_runs_instead_of_cd(self):
        rc, calls, prompts, _ = self._run_with_inputs(["meta", "env", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["meta", "env"]])
        self.assertNotIn(f"{PROMPT_PREFIX}infinito meta env> ", prompts)

    def test_infinito_alone_jumps_to_root(self):
        rc, calls, prompts, _ = self._run_with_inputs(
            ["administration", "infinito", "exit"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito> ")

    def test_infinito_path_jumps_absolute(self):
        rc, calls, prompts, _ = self._run_with_inputs(
            ["meta", "infinito administration deploy", "exit"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn(
            f"{PROMPT_PREFIX}infinito administration deploy> ",
            prompts,
        )

    def test_infinito_invalid_path_stays_put(self):
        rc, calls, prompts, _ = self._run_with_inputs(
            ["administration", "infinito does-not-exist", "exit"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito administration> ")

    def test_invalid_nav_target_stays_put(self):
        rc, _, prompts, _ = self._run_with_inputs(["/does-not-exist", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(prompts[-1], f"{PROMPT_PREFIX}infinito> ")


class TestLs(_MainLoopHarness, unittest.TestCase):
    def test_ls_does_not_dispatch_a_command(self):
        rc, calls, _, out = self._run_with_inputs(["ls", "exit"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("administration", out)


if __name__ == "__main__":
    unittest.main()
