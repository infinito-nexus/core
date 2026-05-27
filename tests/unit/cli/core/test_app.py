import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.core.app import main as app_main
from cli.core.app import parse_flags


class TestApp(unittest.TestCase):
    def test_parse_flags_log_only_for_deploy(self):
        # --log is ignored for non-deploy commands; it is removed from argv
        argv = ["infinito", "--log", "/tmp/infinito-logs", "build", "tree"]
        flags = parse_flags(argv)
        self.assertIsNone(flags.log_dir)
        self.assertNotIn("--log", argv)
        self.assertNotIn("/tmp/infinito-logs", argv)

        # --log is accepted for deploy; it is removed from argv and stored in flags
        argv2 = ["infinito", "--log", "/tmp/infinito-logs", "deploy", "container"]
        flags2 = parse_flags(argv2)
        self.assertEqual(flags2.log_dir, Path("/tmp/infinito-logs"))
        self.assertNotIn("--log", argv2)
        self.assertNotIn("/tmp/infinito-logs", argv2)

    def test_parse_flags_log_requires_argument(self):
        # Missing argument: '--log' is followed by another flag (or end of argv)
        argv = ["infinito", "--log", "--git-clean", "deploy", "container"]
        with self.assertRaises(SystemExit) as cm:
            parse_flags(argv)
        self.assertEqual(cm.exception.code, 1)

        argv2 = ["infinito", "--log"]
        with self.assertRaises(SystemExit) as cm2:
            parse_flags(argv2)
        self.assertEqual(cm2.exception.code, 1)

    @patch(
        "cli.core.app.resolve_command_module",
        return_value=("cli.administration.deploy.container.command.command", ["--x"]),
    )
    @patch("cli.core.app.run_command_once", return_value=True)
    def test_app_main_dispatches_to_resolved_module(self, _mock_run, _mock_resolve):
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "administration", "deploy", "container", "--x"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.argv = old_argv

    @patch("cli.core.app.resolve_command_module", return_value=(None, ["nope"]))
    def test_app_main_unknown_command_exits_1(self, _mock_resolve):
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "nope"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.argv = old_argv

    @patch("cli.core.app.print_global_help")
    def test_app_main_global_help(self, mock_help):
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "--help"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 0)
            self.assertTrue(mock_help.called)
        finally:
            sys.argv = old_argv

    def test_parse_flags_tree_unbounded(self):
        argv = ["infinito", "--tree", "meta"]
        flags = parse_flags(argv)
        self.assertTrue(flags.tree)
        self.assertIsNone(flags.tree_depth)
        self.assertEqual(argv, ["infinito", "meta"])

    def test_parse_flags_tree_with_depth(self):
        argv = ["infinito", "--tree", "2", "meta"]
        flags = parse_flags(argv)
        self.assertTrue(flags.tree)
        self.assertEqual(flags.tree_depth, 2)
        self.assertEqual(argv, ["infinito", "meta"])

    def test_parse_flags_tree_non_integer_token_kept_as_arg(self):
        argv = ["infinito", "--tree", "meta"]
        flags = parse_flags(argv)
        self.assertTrue(flags.tree)
        self.assertIsNone(flags.tree_depth)
        # `meta` is preserved as a regular argument.
        self.assertEqual(argv, ["infinito", "meta"])

    @patch("cli.core.app.print_tree")
    def test_app_main_tree_flag_dispatches_to_print_tree(self, mock_tree):
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "--tree"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 0)
            self.assertTrue(mock_tree.called)
            kwargs = mock_tree.call_args.kwargs
            self.assertIsNone(kwargs.get("max_depth"))
        finally:
            sys.argv = old_argv

    @patch("cli.core.app.print_tree")
    def test_app_main_tree_flag_with_depth(self, mock_tree):
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "--tree", "3"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 0)
            kwargs = mock_tree.call_args.kwargs
            self.assertEqual(kwargs.get("max_depth"), 3)
        finally:
            sys.argv = old_argv

    @patch("cli.core.app.print_dir_overview")
    def test_app_main_navigates_into_category_folder(self, mock_overview):
        # `cli/administration/` is a real category folder (no __main__.py)
        # with sub-commands underneath. `infinito administration` MUST
        # show its overview rather than failing.
        old_argv = sys.argv
        try:
            sys.argv = ["infinito", "administration"]
            with self.assertRaises(SystemExit) as cm:
                app_main()
            self.assertEqual(cm.exception.code, 0)
            self.assertTrue(mock_overview.called)
            args = mock_overview.call_args.args
            self.assertEqual(args[1], ["administration"])
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
