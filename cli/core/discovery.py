from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Command:
    """
    A CLI command is a Python package directory under cli/ that contains __main__.py.

    Example:
      cli/build/tree/__main__.py  -> parts=("build","tree"), module="cli.build.tree"
    """

    parts: tuple[str, ...]  # relative path parts under cli/
    module: str  # python -m module
    main_path: Path  # filesystem path to __main__.py

    @property
    def folder(self) -> str | None:
        if len(self.parts) <= 1:
            return None
        return "/".join(self.parts[:-1])

    @property
    def name(self) -> str:
        return self.parts[-1]

    @property
    def subcommand(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class DirEntry:
    """One-level-deep entry under a cli/ directory.

    `is_command` is True when the directory itself contains ``__main__.py``
    (a runnable subcommand); False for category folders that only group
    further commands and have no entry point of their own.
    """

    name: str
    is_command: bool
    relative_parts: tuple[str, ...]

    @property
    def module(self) -> str:
        return "cli." + ".".join(self.relative_parts)


def _is_valid_package_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return path.name != "__pycache__"


def _has_cli_content(folder: Path) -> bool:
    """A category folder is shown in the overview only when it has at
    least one runnable command somewhere underneath. Empty support
    packages (e.g. ``cli/core``) stay hidden."""
    if (folder / "__main__.py").is_file():
        return True
    for path in folder.rglob("__main__.py"):
        if "__pycache__" in path.parts:
            continue
        return True
    return False


def iter_dir_entries(cli_dir: Path, parts: tuple[str, ...]) -> list[DirEntry]:
    """Return the immediate subdirectories of ``cli/<parts>/``, split into
    runnable commands (``__main__.py`` present) and category folders.
    Empty support packages (no command anywhere underneath) are skipped."""
    base = cli_dir.joinpath(*parts) if parts else cli_dir
    if not base.is_dir():
        return []
    entries: list[DirEntry] = []
    for child in sorted(base.iterdir()):
        if not _is_valid_package_dir(child):
            continue
        if child.name.startswith("__"):
            continue
        if not _has_cli_content(child):
            continue
        entries.append(
            DirEntry(
                name=child.name,
                is_command=(child / "__main__.py").is_file(),
                relative_parts=(*parts, child.name),
            )
        )
    return entries


def discover_commands(cli_dir: Path) -> list[Command]:
    """
    Recursively find all packages under cli_dir that contain __main__.py.
    """
    commands: list[Command] = []

    for root, dirnames, filenames in os.walk(cli_dir):
        # prune __pycache__ eagerly
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]

        if "__main__.py" not in filenames:
            continue

        root_path = Path(root)
        if not _is_valid_package_dir(root_path):
            continue

        rel = root_path.relative_to(cli_dir)
        if rel.parts == ():
            # cli/ itself is NOT a command; cli/__main__.py is the dispatcher
            continue

        parts = tuple(rel.parts)
        module = "cli." + ".".join(parts)
        commands.append(
            Command(parts=parts, module=module, main_path=root_path / "__main__.py")
        )

    commands.sort(key=lambda c: (c.folder or "", c.name))
    return commands


def resolve_command_module(
    cli_dir: Path, argv_parts: list[str]
) -> tuple[str | None, list[str]]:
    """
    Resolve the longest argv prefix that matches a discovered command module.

    Returns:
      (module, remaining_args)

    Example:
      argv_parts=["deploy","container","--foo","bar"]
      -> ("cli.administration.deploy.container", ["--foo","bar"])
    """
    # Subcommand path is always BEFORE the first flag (CLI convention) and
    # cannot contain absolute paths or path separators. Capping the search
    # window at the first "non-subcommand-shaped" arg keeps the loop from
    # building paths that contain huge `--vars` JSON or absolute `--vars-file`
    # values, which previously triggered ENAMETOOLONG inside `is_dir()`.
    max_prefix = len(argv_parts)
    for i, part in enumerate(argv_parts):
        if not part or part.startswith("-") or "/" in part or "\\" in part:
            max_prefix = i
            break

    # We resolve by checking for cli/<prefix>/__main__.py existing.
    for n in range(max_prefix, 0, -1):
        candidate_dir = cli_dir.joinpath(*argv_parts[:n])
        try:
            if candidate_dir.is_dir() and (candidate_dir / "__main__.py").is_file():
                module = "cli." + ".".join(argv_parts[:n])
                return module, argv_parts[n:]
        except OSError:
            # stat() may legitimately fail (ENAMETOOLONG, ENOENT on broken
            # symlinks, EACCES, ...); none of these mean "this is the
            # command", so just keep trying shorter prefixes.
            continue
    return None, argv_parts
