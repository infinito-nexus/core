from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

from cli.core.colors import Fore, Style, color_text
from cli.core.discovery import (
    DirEntry,
    discover_commands,
    iter_dir_entries,
)
from utils.cache.files import read_text

if TYPE_CHECKING:
    from pathlib import Path


def format_command_help(
    name: str, description: str, indent: int = 2, col_width: int = 36, width: int = 80
) -> str:
    """Two-column help line: name, then the description in DIM.

    Reserves at least two spaces between the columns; a name that would
    crowd into the description column drops the description onto the
    next line so the two never collide.
    """
    prefix = " " * indent + name
    desc_indent = " " * col_width
    if len(prefix) + 2 > col_width:
        wrapper = textwrap.TextWrapper(
            width=width, initial_indent=desc_indent, subsequent_indent=desc_indent
        )
        return prefix + "\n\n" + color_text(wrapper.fill(description), Style.DIM)

    prefix_padded = f"{prefix:<{col_width}}"
    wrapper = textwrap.TextWrapper(
        width=width, initial_indent=desc_indent, subsequent_indent=desc_indent
    )
    wrapped = wrapper.fill(description)
    head, _, rest = wrapped.partition("\n")
    head_desc = head[col_width:]
    first_line = prefix_padded + color_text(head_desc, Style.DIM)
    if rest:
        return first_line + "\n" + color_text(rest, Style.DIM)
    return first_line


def extract_description_via_help(module: str) -> str:
    """
    Best-effort: run "python -m <module> --help" and extract the first paragraph after usage.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        out = (result.stdout or "").splitlines()

        seen_usage = False
        for i, line in enumerate(out):
            if line.strip().startswith("usage:"):
                seen_usage = True
                continue
            if not seen_usage:
                continue
            if not line.strip():
                for j in range(i + 1, len(out)):
                    desc = out[j].strip()
                    if desc:
                        return desc
                break
    except Exception:
        return "-"
    return "-"


def read_folder_title(folder: Path) -> str | None:
    """Return the H1 heading text of ``<folder>/README.md`` with any
    trailing emoji preserved. Returns ``None`` when the file is missing
    or its first non-blank line is not an H1 heading."""
    readme = folder / "README.md"
    if not readme.is_file():
        return None
    try:
        text = read_text(str(readme))
    except Exception:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            return stripped[2:].strip()
        return None
    return None


def read_folder_description(folder: Path) -> str:
    """Return the first paragraph below the H1 heading in
    ``<folder>/README.md``. Headings, leading blank lines, and trailing
    paragraphs are skipped. Returns ``"-"`` when no readable description
    is available."""
    readme = folder / "README.md"
    if not readme.is_file():
        return "-"
    try:
        text = read_text(str(readme))
    except Exception:
        return "-"

    paragraph: list[str] = []
    started_paragraph = False
    for line in text.splitlines():
        stripped = line.strip()
        if not started_paragraph:
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            started_paragraph = True
        if not stripped:
            break
        paragraph.append(stripped)

    if not paragraph:
        return "-"
    return " ".join(paragraph)


def _entry_description(cli_dir: Path, entry: DirEntry) -> str:
    """Pick the right description source for an entry: argparse help for
    runnable commands, README.md for category folders."""
    if entry.is_command:
        return extract_description_via_help(entry.module)
    folder_path = cli_dir.joinpath(*entry.relative_parts)
    return read_folder_description(folder_path)


def _full_invocation(entry: DirEntry) -> str:
    """Return the copy-pasteable invocation for an entry, e.g.
    ``infinito meta roles order run`` instead of just ``run``."""
    return "infinito " + " ".join(entry.relative_parts)


def _print_dir_body(cli_dir: Path, parts: list[str]) -> None:
    """Print the one-level-deep index of cli/<parts>/. Each entry is
    shown with its full invocation (``infinito <path>``) so the line is
    copy-pasteable. Category folders and runnable commands share the
    same line shape; the ``Categories:`` / ``Commands:`` headings tell
    them apart."""
    entries = iter_dir_entries(cli_dir, tuple(parts))
    if not entries:
        print(color_text("No commands or sub-folders here.", Fore.YELLOW))
        return

    folders = [e for e in entries if not e.is_command]
    commands = [e for e in entries if e.is_command]

    if folders:
        print()
        print(color_text("🗂️  Categories:", Style.BRIGHT))
        print()
        for entry in folders:
            desc = _entry_description(cli_dir, entry)
            print(color_text(format_command_help(_full_invocation(entry), desc), ""))
            print()

    if commands:
        print()
        print(color_text("⚙️  Commands:", Style.BRIGHT))
        print()
        for entry in commands:
            desc = _entry_description(cli_dir, entry)
            print(color_text(format_command_help(_full_invocation(entry), desc), ""))
            print()
        print(
            color_text(
                "💡  Tip: append --help to any command above for usage details.",
                Fore.CYAN,
            )
        )
        print()


def print_global_help(cli_dir: Path) -> None:
    print(color_text("Infinito.Nexus CLI 🦫🌐🖥️", Fore.CYAN + Style.BRIGHT))
    print()
    print(color_text("Your Gateway to Automated IT Infrastructure Setup", Style.DIM))
    print()
    print(
        color_text(
            "Usage: infinito "
            "[--log <LOG_DIR>] "
            "[--git-clean] "
            "[--infinite] "
            "[--help-all] "
            "[--tree [N]] "
            "[-h|--help] "
            "<command> [options]",
            Fore.GREEN,
        )
    )
    print()
    print(color_text("Options:", Style.BRIGHT))
    print(
        color_text(
            "  --log <LOG_DIR>   Log all proxied command output to <LOG_DIR>/<timestamp>.log",
            Fore.YELLOW,
        )
    )
    print(
        color_text(
            "  --git-clean       Remove all Git-ignored files before running",
            Fore.YELLOW,
        )
    )
    print(
        color_text(
            "  --infinite        Run the proxied command in an infinite loop",
            Fore.YELLOW,
        )
    )
    print(
        color_text(
            "  --help-all        Show full --help for all CLI commands", Fore.YELLOW
        )
    )
    print(
        color_text(
            "  --tree [N]        List sub-folders / commands recursively (depth N, "
            "unbounded if N omitted)",
            Fore.YELLOW,
        )
    )
    print(
        color_text("  -h, --help        Show this help message and exit", Fore.YELLOW)
    )
    print()
    _print_dir_body(cli_dir, [])

    print(
        color_text(
            "🔗  You can chain subcommands by specifying nested directories,", Fore.CYAN
        )
    )
    print(color_text("    e.g. infinito build tree", Fore.CYAN))
    print(color_text("    corresponds to cli/build/tree/__main__.py.", Fore.CYAN))
    print()
    print(color_text("More help:", Style.BRIGHT))
    print(
        color_text(
            "  make help                    List all Make targets with descriptions",
            Fore.YELLOW,
        )
    )
    print(
        color_text(
            "  https://docs.infinito.nexus  Full project documentation",
            Fore.YELLOW,
        )
    )
    print()
    print(
        color_text(
            "Infinito.Nexus is a product of Kevin Veen-Birkenbach, https://cybermaster.space .\n",
            Style.DIM,
        )
    )
    print(
        color_text("Test and use productively on https://infinito.nexus .\n", Style.DIM)
    )
    print(
        color_text(
            "For commercial use, a license agreement with Kevin Veen-Birkenbach is required. \n",
            Style.DIM,
        )
    )
    print(color_text("License: https://s.infinito.nexus/license", Style.DIM))
    print()
    print(
        color_text(
            "🎉🌈 Happy IT Infrastructuring! 🚀🔧✨", Fore.MAGENTA + Style.BRIGHT
        )
    )
    print()


def print_dir_overview(cli_dir: Path, parts: list[str]) -> None:
    """Print a category-folder overview. The H1 title from the folder's
    README.md is used as the heading (with the invocation path shown
    underneath as a dim subtitle); a fallback to the bare invocation
    path is used when the README is absent. The README description
    paragraph follows, then the one-level-deep index of immediate
    sub-folders and commands."""
    base = cli_dir.joinpath(*parts) if parts else cli_dir
    title = read_folder_title(base)
    invocation = "infinito" if not parts else "infinito " + " ".join(parts)

    if title:
        print(color_text(title, Fore.CYAN + Style.BRIGHT))
        print()
        print(color_text(invocation, Style.ITALIC))
    else:
        print(color_text(invocation, Fore.CYAN + Style.BRIGHT))
    print()

    desc = read_folder_description(base)
    if desc != "-":
        print(color_text(desc, Style.DIM))

    _print_dir_body(cli_dir, parts)


_TREE_LINE_WIDTH = 100
_FOLDER_EMOJI = "🗂️"
_COMMAND_EMOJI = "⚙️"


def _entry_emoji(entry: DirEntry) -> str:
    return _COMMAND_EMOJI if entry.is_command else _FOLDER_EMOJI


def print_tree(cli_dir: Path, parts: list[str], max_depth: int | None = None) -> None:
    """Recursive tree listing under ``cli/<parts>/`` with Unicode tree
    connectors, per-entry emoji glyphs, and multi-line wrapped
    descriptions aligned to a single description column. ``max_depth``
    is 1-based: ``None`` (default) walks the full tree, ``1`` shows
    only the immediate children."""
    base = cli_dir.joinpath(*parts) if parts else cli_dir
    title = read_folder_title(base)
    invocation = "infinito" if not parts else "infinito " + " ".join(parts)

    if title:
        print(color_text(title, Fore.CYAN + Style.BRIGHT))
        print()
        print(color_text(invocation, Style.ITALIC))
    else:
        print(color_text(invocation, Fore.CYAN + Style.BRIGHT))
    desc = read_folder_description(base)
    if desc != "-":
        print(color_text(desc, Style.DIM))
    print()

    items: list[dict] = []

    def _collect(current_parts: tuple[str, ...], prefix: str, depth: int) -> None:
        if max_depth is not None and depth > max_depth:
            return
        entries = iter_dir_entries(cli_dir, current_parts)
        for index, entry in enumerate(entries):
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            emoji = _entry_emoji(entry)
            head_plain = f"{prefix}{connector}{emoji}  {entry.name}"
            items.append(
                {
                    "entry": entry,
                    "prefix": prefix,
                    "is_last": is_last,
                    "head_plain": head_plain,
                }
            )
            if not entry.is_command:
                child_prefix = prefix + ("    " if is_last else "│   ")
                _collect(entry.relative_parts, child_prefix, depth + 1)

    _collect(tuple(parts), "", 1)
    if not items:
        return

    desc_col = max(len(it["head_plain"]) for it in items) + 2
    desc_avail = max(20, _TREE_LINE_WIDTH - desc_col)

    last_index = len(items) - 1
    for index, item in enumerate(items):
        entry: DirEntry = item["entry"]
        prefix: str = item["prefix"]
        is_last: bool = item["is_last"]
        head_plain: str = item["head_plain"]

        connector = "└── " if is_last else "├── "
        emoji = _entry_emoji(entry)
        name_colored = (
            color_text(entry.name, Fore.MAGENTA) if not entry.is_command else entry.name
        )
        head_colored = f"{prefix}{connector}{emoji}  {name_colored}"

        description = _entry_description(cli_dir, entry)
        if description == "-":
            print(head_colored)
        else:
            wrapper = textwrap.TextWrapper(
                width=desc_avail,
                break_long_words=False,
                break_on_hyphens=False,
            )
            wrapped = wrapper.wrap(description) or [description]

            head_padding = " " * max(1, desc_col - len(head_plain))
            print(f"{head_colored}{head_padding}{color_text(wrapped[0], Style.DIM)}")

            cont_lead = prefix + ("│" if not is_last else " ")
            cont_padding = " " * max(1, desc_col - len(cont_lead))
            for line in wrapped[1:]:
                print(f"{cont_lead}{cont_padding}{color_text(line, Style.DIM)}")

        if index != last_index:
            print(prefix + ("│" if not is_last else ""))


def show_full_help_for_all(cli_dir: Path) -> None:
    commands = discover_commands(cli_dir)

    print(
        color_text("Infinito.Nexus CLI – Full Help Overview", Fore.CYAN + Style.BRIGHT)
    )
    print()

    for cmd in commands:
        file_path = str(cmd.main_path.relative_to(cli_dir.parent))
        print(color_text("=" * 80, Fore.BLUE + Style.BRIGHT))
        print(color_text(f"Subcommand: {cmd.subcommand}", Fore.YELLOW + Style.BRIGHT))
        print(color_text(f"File: {file_path}", Fore.CYAN))
        print(color_text("-" * 80, Fore.BLUE))

        try:
            result = subprocess.run(
                [sys.executable, "-m", cmd.module, "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(color_text(result.stderr.rstrip(), Fore.RED))
        except Exception as e:
            print(color_text(f"Failed to get help for {file_path}: {e}", Fore.RED))

        print()


def show_help_for_directory(cli_dir: Path, dir_parts: list[str]) -> bool:
    """Backwards-compat shim: defer to :func:`print_dir_overview`. Returns
    True when the directory exists, False otherwise."""
    candidate_dir = cli_dir.joinpath(*dir_parts)
    if not candidate_dir.is_dir():
        return False
    print_dir_overview(cli_dir, dir_parts)
    return True
