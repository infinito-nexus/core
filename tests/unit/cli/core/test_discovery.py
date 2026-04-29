import tempfile
import unittest
from pathlib import Path

from cli.core.discovery import discover_commands, resolve_command_module


class TestDiscovery(unittest.TestCase):
    def _touch(self, path: Path, content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_discover_commands_finds_packages_with_main(self):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)

            # Dispatcher exists but must NOT be treated as a command
            self._touch(cli_dir / "__main__.py", "# dispatcher\n")

            # commands
            self._touch(cli_dir / "deploy" / "container" / "__main__.py", "# cmd\n")
            self._touch(cli_dir / "build" / "tree" / "__main__.py", "# cmd\n")
            self._touch(cli_dir / "make" / "__main__.py", "# cmd\n")

            cmds = discover_commands(cli_dir)
            modules = {c.module for c in cmds}

            self.assertIn("cli.deploy.container", modules)
            self.assertIn("cli.build.tree", modules)
            self.assertIn("cli.make", modules)
            self.assertNotIn("cli", modules)  # root must not be a command

    def test_discover_commands_ignores_pycache(self):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)

            self._touch(cli_dir / "__main__.py", "# dispatcher\n")
            pycache = cli_dir / "x" / "__pycache__"
            self._touch(pycache / "__main__.py", "# should be ignored\n")

            cmds = discover_commands(cli_dir)
            modules = {c.module for c in cmds}
            self.assertNotIn("cli.x.__pycache__", modules)

    def test_resolve_command_module_longest_prefix_wins(self):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)

            # Both deploy and deploy/container exist -> prefer deploy/container
            self._touch(cli_dir / "__main__.py", "# dispatcher\n")
            self._touch(cli_dir / "deploy" / "__main__.py", "# cmd\n")
            self._touch(cli_dir / "deploy" / "container" / "__main__.py", "# cmd\n")

            module, remaining = resolve_command_module(
                cli_dir, ["deploy", "container", "--foo", "bar"]
            )
            self.assertEqual(module, "cli.deploy.container")
            self.assertEqual(remaining, ["--foo", "bar"])

    def test_resolve_command_module_returns_none_when_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)
            self._touch(cli_dir / "__main__.py", "# dispatcher\n")

            module, remaining = resolve_command_module(cli_dir, ["nope", "--x"])
            self.assertIsNone(module)
            self.assertEqual(remaining, ["nope", "--x"])

    def test_resolve_command_module_stops_at_first_flag(self):
        # `infinito create inventory <abs-path> --host localhost ...`: the
        # subcommand is `create inventory`; the absolute positional arg
        # MUST NOT be tried as a sub-package, otherwise pathlib resets
        # the search root and downstream args (huge `--vars` JSON) end
        # up concatenated as a single path that hits ENAMETOOLONG.
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)
            self._touch(cli_dir / "__main__.py", "# dispatcher\n")
            self._touch(cli_dir / "create" / "inventory" / "__main__.py", "# cmd\n")

            argv = [
                "create",
                "inventory",
                "/home/user/inventories/localhost-0",
                "--host",
                "localhost",
                "--vars",
                '{"a": 1, "b": 2}',
            ]
            module, remaining = resolve_command_module(cli_dir, argv)
            self.assertEqual(module, "cli.create.inventory")
            self.assertEqual(remaining, argv[2:])

    def test_resolve_command_module_survives_oserror_on_long_path(self):
        # Defence in depth: even if a freshly-introduced positional arg
        # somehow slips past the flag-stop heuristic and produces a path
        # that stat() refuses (ENAMETOOLONG, ENOENT, EACCES), the
        # dispatcher MUST keep trying shorter prefixes instead of crashing.
        with tempfile.TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            cli_dir.mkdir(parents=True, exist_ok=True)
            self._touch(cli_dir / "__main__.py", "# dispatcher\n")
            self._touch(cli_dir / "build" / "tree" / "__main__.py", "# cmd\n")

            # 5000-char arg blows past most filesystem name-length limits.
            blob = "x" * 5000
            argv = ["build", "tree", blob]
            module, remaining = resolve_command_module(cli_dir, argv)
            self.assertEqual(module, "cli.build.tree")
            self.assertEqual(remaining, [blob])


if __name__ == "__main__":
    unittest.main()
