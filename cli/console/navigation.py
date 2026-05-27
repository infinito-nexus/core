from __future__ import annotations

import sys

from cli.core.colors import Fore, color_text

from .constants import (
    CLI_ROOT,
    HELP_ALIASES,
    PROMPT_PREFIX,
    RESERVED_DIRS,
    STRIPPABLE_PREFIXES,
)


def is_category(segments: list[str]) -> bool:
    # A category is a sub-package without its own `__main__.py`; once a
    # package becomes directly executable it is a leaf command and the
    # console runs it instead of cd-ing into it.
    if not segments:
        return True
    candidate = CLI_ROOT.joinpath(*segments)
    if not candidate.is_dir():
        return False
    if not (candidate / "__init__.py").exists():
        return False
    if (candidate / "__main__.py").exists():
        return False
    return segments[0] not in RESERVED_DIRS


def command_exists(segments: list[str], token: str) -> bool:
    base = CLI_ROOT.joinpath(*segments) if segments else CLI_ROOT
    package = base / token
    if package.is_dir() and (package / "__init__.py").exists():
        return segments != [] or token not in RESERVED_DIRS
    return (base / f"{token}.py").is_file()


def resolve_argv(current: list[str], normalized: list[str]) -> list[str]:
    if not current or not normalized:
        return current + normalized
    head = normalized[0]
    if head.startswith("-"):
        return current + normalized
    if command_exists(current, head):
        return current + normalized
    if command_exists([], head):
        return normalized
    return current + normalized


def is_navigation_token(token: str) -> bool:
    if not token:
        return False
    # nocheck: project-root-import  `..` is a REPL nav token, not a path-construction call.
    if token in {"/", ".."}:
        return True
    # nocheck: project-root-import  same as above; classifies user input shape.
    return token.startswith(("/", "../")) or "/" in token


def resolve_cd(current: list[str], target: str) -> list[str] | None:
    if target in ("", "/"):
        return []
    new_path = [] if target.startswith("/") else list(current)
    for raw in target.split("/"):
        seg = raw.strip()
        if seg in ("", "."):
            continue
        # nocheck: project-root-import  `..` is a REPL nav segment.
        if seg == "..":
            if new_path:
                new_path.pop()
            continue
        if not is_category([*new_path, seg]):
            print(
                color_text(f"cd: not a category: {seg}", Fore.RED),
                file=sys.stderr,
            )
            return None
        new_path.append(seg)
    return new_path


def prompt(current: list[str]) -> str:
    suffix = (" " + " ".join(current)) if current else ""
    return f"{PROMPT_PREFIX}infinito{suffix}> "


def normalize(argv: list[str]) -> list[str]:
    if argv and argv[0] in STRIPPABLE_PREFIXES:
        argv = argv[1:]
    if not argv:
        return ["--help"]
    if argv[0] in HELP_ALIASES:
        return ["--help", *argv[1:]]
    return argv
