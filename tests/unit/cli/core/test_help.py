import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cli.core.discovery import Command
from cli.core.help import (
    extract_description_via_help,
    format_command_help,
    print_dir_overview,
    print_tree,
    read_folder_description,
    read_folder_title,
    show_full_help_for_all,
    show_help_for_directory,
)


class TestHelp(unittest.TestCase):
    def test_format_command_help_basic(self):
        output = format_command_help(
            name="cmd",
            description="A basic description",
            indent=2,
            col_width=20,
            width=40,
        )
        self.assertTrue(output.startswith("  cmd"))
        self.assertIn("A basic description", output)

    @patch("cli.core.help.subprocess.run", side_effect=Exception("mocked error"))
    def test_extract_description_via_help_returns_dash_on_exception(self, _mock_run):
        self.assertEqual(extract_description_via_help("cli.fake.module"), "-")

    @patch("cli.core.help.subprocess.run")
    def test_extract_description_via_help_with_description(self, mock_run):
        mock_stdout = "usage: dummy [options]\n\nThis is a help description.\n"
        mock_run.return_value = Mock(stdout=mock_stdout, stderr="")
        self.assertEqual(
            extract_description_via_help("cli.some.cmd"),
            "This is a help description.",
        )

    @patch("cli.core.help.subprocess.run")
    def test_extract_description_via_help_without_description(self, mock_run):
        mock_stdout = "usage: empty [options]\n"
        mock_run.return_value = Mock(stdout=mock_stdout, stderr="")
        self.assertEqual(extract_description_via_help("cli.some.cmd"), "-")

    @patch("cli.core.help.discover_commands")
    @patch("cli.core.help.subprocess.run")
    def test_show_full_help_for_all_invokes_help_for_each_command(
        self, mock_run, mock_discover
    ):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)

            cmds = [
                Command(
                    parts=("deploy",),
                    module="cli.administration.deploy",
                    main_path=cli_dir / "deploy" / "__main__.py",
                ),
                Command(
                    parts=("meta", "applications", "all"),
                    module="cli.meta.roles.applications.all",
                    main_path=cli_dir / "meta" / "applications" / "all" / "__main__.py",
                ),
            ]
            mock_discover.return_value = cmds

            show_full_help_for_all(cli_dir)

            invoked_modules = {call.args[0][2] for call in mock_run.call_args_list}
            self.assertEqual(
                {"cli.administration.deploy", "cli.meta.roles.applications.all"},
                invoked_modules,
            )

            for call in mock_run.call_args_list:
                args, kwargs = call
                cmd = args[0]
                self.assertGreaterEqual(len(cmd), 4)
                self.assertEqual(cmd[1], "-m")
                self.assertEqual(cmd[3], "--help")
                self.assertEqual(kwargs.get("capture_output"), True)
                self.assertEqual(kwargs.get("text"), True)
                self.assertEqual(kwargs.get("check"), False)

    @patch("cli.core.help.discover_commands")
    @patch("cli.core.help.extract_description_via_help", return_value="DESC")
    @patch("builtins.print")
    def test_show_help_for_directory_lists_only_direct_children(
        self, _mock_print, _mock_extract, mock_discover
    ):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)
            (cli_dir / "meta" / "j2").mkdir(parents=True, exist_ok=True)

            mock_discover.return_value = [
                Command(
                    parts=("meta", "j2", "compiler"),
                    module="cli.meta.j2.compiler",
                    main_path=cli_dir / "meta" / "j2" / "compiler" / "__main__.py",
                ),
                Command(
                    parts=("meta", "applications", "all"),
                    module="cli.meta.roles.applications.all",
                    main_path=cli_dir / "meta" / "applications" / "all" / "__main__.py",
                ),
            ]

            ok = show_help_for_directory(cli_dir, ["meta", "j2"])
            self.assertTrue(ok)


class TestReadFolderDescription(unittest.TestCase):
    def _touch_readme(self, folder: Path, content: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(content, encoding="utf-8")

    def test_returns_dash_when_readme_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(read_folder_description(Path(td)), "-")

    def test_returns_first_paragraph_below_h1(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self._touch_readme(
                folder,
                "# Meta Tools 🧰\n\nFirst paragraph.\n\nSecond paragraph that should be ignored.\n",
            )
            self.assertEqual(read_folder_description(folder), "First paragraph.")

    def test_collapses_multi_line_paragraph(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self._touch_readme(
                folder,
                "# Title 🛠️\n\nLine one\nline two still in same paragraph.\n\nNext paragraph.\n",
            )
            self.assertEqual(
                read_folder_description(folder),
                "Line one line two still in same paragraph.",
            )

    def test_handles_readme_without_h1(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self._touch_readme(folder, "Just a description.\n\nMore stuff.\n")
            self.assertEqual(read_folder_description(folder), "Just a description.")


class TestReadFolderTitle(unittest.TestCase):
    def _touch_readme(self, folder: Path, content: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(content, encoding="utf-8")

    def test_returns_h1_text_with_trailing_emoji(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self._touch_readme(folder, "# Meta 🧬\n\nDescription.\n")
            self.assertEqual(read_folder_title(folder), "Meta 🧬")

    def test_returns_none_when_readme_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(read_folder_title(Path(td)))

    def test_returns_none_when_first_non_blank_line_is_not_h1(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            self._touch_readme(folder, "Just a paragraph, no H1.\n")
            self.assertIsNone(read_folder_title(folder))


class TestPrintDirOverview(unittest.TestCase):
    def _touch(self, path: Path, content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @patch("cli.core.help.extract_description_via_help", return_value="CMD-DESC")
    @patch("builtins.print")
    def test_prints_categories_and_commands_with_readme_descriptions(
        self, mock_print, _mock_extract
    ):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)
            # `meta` is a category folder with README.
            self._touch(
                cli_dir / "meta" / "README.md",
                "# Meta 🧬\n\nMeta operations folder.\n",
            )
            self._touch(cli_dir / "meta" / "j2" / "__main__.py", "# cmd\n")
            self._touch(cli_dir / "meta" / "roles" / "all" / "__main__.py", "# cmd\n")

            print_dir_overview(cli_dir, ["meta"])

            joined = "\n".join(
                str(call.args[0]) for call in mock_print.call_args_list if call.args
            )
            # Title is taken from the README's H1; invocation path
            # appears as the dim subtitle underneath.
            self.assertIn("Meta 🧬", joined)
            self.assertIn("infinito meta", joined)
            self.assertIn("Meta operations folder.", joined)
            self.assertIn("Categories:", joined)
            # Full invocation form, no trailing slash on category folders.
            self.assertIn("infinito meta roles", joined)
            self.assertNotIn("roles/", joined)
            self.assertIn("Commands:", joined)
            self.assertIn("infinito meta j2", joined)
            self.assertIn("CMD-DESC", joined)
            # Help-hint surfaces below the commands list.
            self.assertIn("--help", joined)


class TestPrintTree(unittest.TestCase):
    def _touch(self, path: Path, content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @patch("cli.core.help.extract_description_via_help", return_value="-")
    @patch("builtins.print")
    def test_unbounded_walks_full_tree(self, mock_print, _mock_extract):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            self._touch(cli_dir / "meta" / "j2" / "compiler" / "__main__.py", "# cmd\n")
            print_tree(cli_dir, [], max_depth=None)
            joined = "\n".join(
                str(call.args[0]) for call in mock_print.call_args_list if call.args
            )
            self.assertIn("meta", joined)
            self.assertIn("j2", joined)
            self.assertIn("compiler", joined)

    @patch("cli.core.help.extract_description_via_help", return_value="-")
    @patch("builtins.print")
    def test_max_depth_truncates_below_limit(self, mock_print, _mock_extract):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            self._touch(cli_dir / "meta" / "j2" / "compiler" / "__main__.py", "# cmd\n")
            print_tree(cli_dir, [], max_depth=1)
            joined = "\n".join(
                str(call.args[0]) for call in mock_print.call_args_list if call.args
            )
            self.assertIn("meta", joined)
            self.assertNotIn("j2", joined)
            self.assertNotIn("compiler", joined)


if __name__ == "__main__":
    unittest.main()
