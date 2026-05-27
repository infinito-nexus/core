from __future__ import annotations

from cli.core.colors import Fore, Style, color_text

from .constants import (
    AUTHOR,
    AUTHOR_URL,
    DOCS_URL,
    LICENSE_NAME,
    LICENSE_URL,
    WEB_URL,
)


def print_banner() -> None:
    print(color_text("infinito.nexus console 🦫🖥️", Fore.CYAN + Style.BRIGHT))
    print(
        color_text(
            "Type 'exit', 'quit', or Ctrl+D to leave. Ctrl+C cancels the current line.",
            Style.DIM,
        )
    )
    print()
    print(color_text("  Help:    type 'help' or '<command> --help'", Fore.YELLOW))
    print(
        color_text(
            # nocheck: project-root-import  `..` in REPL nav help text, not path construction
            "  Nav:     '<category>' enter, '/' root, '..' up, '/abs/path' or '../rel/path' to jump, 'infinito [path]' absolute, 'ls' list",
            Fore.YELLOW,
        )
    )
    print(color_text(f"  Web:     {WEB_URL}", Fore.YELLOW))
    print(color_text(f"  Docs:    {DOCS_URL}", Fore.YELLOW))
    print(color_text(f"  Author:  {AUTHOR} - {AUTHOR_URL}", Style.DIM))
    print(
        color_text(
            f"  License: {LICENSE_NAME} - {LICENSE_URL}",
            Style.DIM,
        )
    )
    print()
