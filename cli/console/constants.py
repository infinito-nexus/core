from __future__ import annotations

from pathlib import Path

WEB_URL = "https://infinito.nexus"
DOCS_URL = "https://docs.infinito.nexus"
LICENSE_NAME = "Infinito.Nexus Community License (Non-Commercial)"
LICENSE_URL = "https://s.infinito.nexus/license"
AUTHOR = "Kevin Veen-Birkenbach"
AUTHOR_URL = "https://cybermaster.space"

EXIT_TOKENS = frozenset({"exit", "quit", ":q"})
STRIPPABLE_PREFIXES = ("cli",)
ROOT_NAV_TOKEN = "infinito"  # noqa: S105  not a credential; REPL keyword
LS_TOKEN = "ls"  # noqa: S105  not a credential; REPL keyword
LS_DESC_LIMIT = 30
HELP_ALIASES = frozenset({"help", "?", "h"})
PROMPT_PREFIX = "🖥️  "

# REPL needs the on-disk cli/ root to resolve category/command paths.
# nocheck: project-root-import  not a project-root walk; resolves cli/ for category dispatch
CLI_ROOT = Path(__file__).resolve().parents[1]
RESERVED_DIRS = frozenset({"core", "__pycache__"})
