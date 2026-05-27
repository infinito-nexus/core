from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cli.core.colors import Fore, Style, color_text
from cli.core.discovery import resolve_command_module
from cli.core.git import git_clean_repo
from cli.core.help import (
    print_dir_overview,
    print_global_help,
    print_tree,
    show_full_help_for_all,
)
from cli.core.run import RunConfig, open_log_file, run_command_once

from . import PROJECT_ROOT


@dataclass
class Flags:
    log_dir: Path | None = None
    git_clean: bool = False
    infinite: bool = False
    help_all: bool = False
    tree: bool = False
    tree_depth: int | None = None  # None = unbounded


def _first_non_flag_token(argv: list[str]) -> str | None:
    """
    Return the first non-flag token after argv[0], but treat '--log <ARG>' as a flag
    with a required argument (skip both tokens).
    """
    i = 1
    while i < len(argv):
        token = argv[i]

        # Skip flags and their args
        if token == "--log":  # noqa: S105  `token` is a CLI argv element, not a credential
            # Skip '--log' and its argument if present
            i += 2
            continue

        if token.startswith("-"):
            i += 1
            continue

        return token

    return None


def _parse_log_dir(argv: list[str]) -> Path | None:
    """
    Parse and remove '--log <LOG_DIR>' from argv.

    - The log path argument is mandatory when --log is present.
    - Logging is only allowed for `deploy` commands. If used with a different
      top-level command, it is silently ignored (but still removed from argv).
    """
    if "--log" not in argv:
        return None

    i = argv.index("--log")
    if i + 1 >= len(argv):
        print(
            color_text(
                "Error: --log requires a path argument (e.g. --log /tmp/infinito-logs).",
                Fore.RED,
            )
        )
        raise SystemExit(1)

    raw = argv[i + 1]
    if raw.startswith("-"):
        print(
            color_text(
                "Error: --log requires a path argument (e.g. --log /tmp/infinito-logs).",
                Fore.RED,
            )
        )
        raise SystemExit(1)

    # Determine the first command token (skipping '--log <ARG>' properly)
    first_cmd = _first_non_flag_token(argv)

    # Always remove '--log <ARG>' from argv
    del argv[i : i + 2]

    # Keep previous behavior: only enable logging for "deploy"
    if first_cmd != "deploy":
        return None

    return Path(raw).expanduser()


def _parse_tree_flag(argv: list[str]) -> tuple[bool, int | None]:
    """Strip ``--tree [N]`` from argv. Returns ``(enabled, depth)`` where
    ``depth`` is the optional integer after ``--tree`` (``None`` means
    unbounded). A non-integer following token is treated as a normal
    argument and left in argv."""
    if "--tree" not in argv:
        return False, None
    i = argv.index("--tree")
    depth: int | None = None
    if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
        try:
            depth = int(argv[i + 1])
        except ValueError:
            depth = None
    if depth is not None:
        del argv[i : i + 2]
    else:
        del argv[i]
    return True, depth


def parse_flags(argv: list[str]) -> Flags:
    flags = Flags()
    flags.log_dir = _parse_log_dir(argv)

    flags.git_clean = "--git-clean" in argv and (argv.remove("--git-clean") or True)
    flags.infinite = "--infinite" in argv and (argv.remove("--infinite") or True)
    flags.help_all = "--help-all" in argv and (argv.remove("--help-all") or True)
    flags.tree, flags.tree_depth = _parse_tree_flag(argv)

    return flags


def main() -> None:
    argv = sys.argv[:]  # keep sys.argv for external tools, but parse on a copy
    flags = parse_flags(argv)
    args = argv[1:]

    cli_dir = PROJECT_ROOT / "cli"
    # sanity: cli_dir should contain __init__.py and __main__.py of dispatcher
    # but we do not hard-fail here

    if flags.git_clean:
        git_clean_repo()

    # Global "show help for all commands" mode
    if flags.help_all:
        print_global_help(cli_dir)
        print(color_text("Full detailed help for all subcommands:", Style.BRIGHT))
        print()
        show_full_help_for_all(cli_dir)
        raise SystemExit(0)

    # Tree view: optional path prefix + optional depth limit
    if flags.tree:
        tree_path_args = [a for a in args if a not in ("-h", "--help")]
        candidate = cli_dir.joinpath(*tree_path_args) if tree_path_args else cli_dir
        if not candidate.is_dir():
            print(
                color_text(
                    f"Error: '{' '.join(tree_path_args)}' is not a CLI directory.",
                    Fore.RED,
                )
            )
            raise SystemExit(1)
        print_tree(cli_dir, tree_path_args, max_depth=flags.tree_depth)
        raise SystemExit(0)

    # Global help: no args or top-level help flag
    if not args or args[0] in ("-h", "--help"):
        print_global_help(cli_dir)
        raise SystemExit(0)

    # Directory-specific help: "<path> -h" / "<path> --help"
    if len(args) > 1 and args[-1] in ("-h", "--help"):
        # First: if "<path>" is a real command, forward help to its argparse.
        module, remaining = resolve_command_module(cli_dir, args[:-1])
        if module and not remaining:
            subprocess.run([sys.executable, "-m", module, "--help"], check=False)
            raise SystemExit(0)

        # Otherwise: category-folder overview if the path exists on disk.
        dir_parts = args[:-1]
        candidate = cli_dir.joinpath(*dir_parts)
        if candidate.is_dir():
            print_dir_overview(cli_dir, dir_parts)
            raise SystemExit(0)

    # Resolve command module by package folders with __main__.py
    module, remaining = resolve_command_module(cli_dir, args)
    if not module:
        # If the literal argv path exists on disk as a category folder
        # (no __main__.py), navigate into it instead of failing.
        candidate = cli_dir.joinpath(*args)
        if candidate.is_dir():
            print_dir_overview(cli_dir, args)
            raise SystemExit(0)
        print(color_text(f"Error: command '{' '.join(args)}' not found.", Fore.RED))
        raise SystemExit(1)

    # If user requested help for the resolved command, forward directly
    if remaining and remaining[0] in ("-h", "--help"):
        subprocess.run([sys.executable, "-m", module, remaining[0]], check=False)
        raise SystemExit(0)

    log_file = None
    if flags.log_dir is not None:
        log_file, log_path = open_log_file(flags.log_dir)
        print(color_text(f"Tip: Log file created at {log_path}", Fore.GREEN))

    full_cmd = [sys.executable, "-m", module, *remaining]

    cfg = RunConfig(
        log_enabled=flags.log_dir is not None,
    )

    try:
        if flags.infinite:
            print(color_text("Starting infinite execution mode...", Fore.CYAN))
            count = 1
            while True:
                print(color_text(f"Run #{count}", Style.BRIGHT))
                run_command_once(full_cmd, cfg, log_file)
                count += 1
        else:
            run_command_once(full_cmd, cfg, log_file)
            raise SystemExit(0)
    except KeyboardInterrupt:
        print()
        print(color_text("Execution interrupted by user (Ctrl+C).", Fore.YELLOW))
        raise SystemExit(130) from None
    finally:
        if log_file:
            log_file.close()
