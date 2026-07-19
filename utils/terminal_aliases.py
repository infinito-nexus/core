"""Fetch-once cache and parser for the operator's terminal aliases.

Configuration comes exclusively from the generated ``.env``
(``make dotenv``), which already folds in ``default.env``, every
handler, and the operator's ``custom.env`` overrides. The alias
repository (INFINITO_ALIAS_REPOSITORY) holds one
``alias <name>='<command>'`` line per shortcut in an ``aliases`` file at
its root; the agent shortcut table lives at INFINITO_ALIAS_MD.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.request
from pathlib import Path

from utils import PROJECT_ROOT as REPO_ROOT
from utils.cache.files import read_text

GENERATED_ENV = REPO_ROOT / ".env"
LOCAL_ALIASES = REPO_ROOT / "aliases"
CACHE_DIR = Path("/tmp/infinito-terminal-aliases")  # noqa: S108 - pinned to match alias.sh's hardcoded /tmp cache path

_ALIAS_RE = re.compile(r"^alias\s+([^=\s]+)=")


def _generated_env_value(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    if GENERATED_ENV.is_file():
        pattern = re.compile(rf"^{re.escape(key)}=(\S+)\s*$")
        for line in GENERATED_ENV.read_text(
            encoding="utf-8"
        ).splitlines():  # nocheck: cache-read
            match = pattern.match(line)
            if match:
                return match.group(1)
    raise KeyError(f"{key} not set; run `make dotenv` to generate {GENERATED_ENV}")


def alias_repository() -> str:
    """Effective terminal alias repository from the generated .env."""
    return _generated_env_value("INFINITO_ALIAS_REPOSITORY")


def alias_md_file() -> Path:
    """Effective agent shortcut markdown file from the generated .env.

    Relative values resolve against the repository root.
    """
    path = Path(_generated_env_value("INFINITO_ALIAS_MD"))
    return path if path.is_absolute() else REPO_ROOT / path


def raw_aliases_url(repository: str) -> str:
    """Raw download URL of the repository's root ``aliases`` file.

    Args:
        repository: git repository URL (GitHub-style raw path layout).
    """
    return f"{repository.rstrip('/')}/raw/main/aliases"


def fetch_cached(repository: str, timeout: int = 15) -> str:
    """Return the aliases file content, downloading once per repository.

    Args:
        repository: git repository URL to fetch the ``aliases`` file from.
        timeout: socket timeout in seconds for the one-time download.
    """
    digest = hashlib.sha256(repository.encode("utf-8")).hexdigest()[:12]
    cache_file = CACHE_DIR / f"aliases-{digest}"
    if cache_file.is_file():
        return cache_file.read_text(encoding="utf-8")  # nocheck: cache-read
    url = raw_aliases_url(repository)
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed https git-host URL from config, not user input
        text = resp.read().decode("utf-8")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(text, encoding="utf-8")
    return text


def parse_alias_names(text: str) -> list[str]:
    """Alias names in file order.

    Args:
        text: raw content of an aliases file.
    """
    return [
        match.group(1) for line in text.splitlines() if (match := _ALIAS_RE.match(line))
    ]


def local_alias_names() -> list[str]:
    """Infinito.Nexus-specific alias names from the repo's ``aliases`` file."""
    if not LOCAL_ALIASES.is_file():
        return []
    return parse_alias_names(read_text(str(LOCAL_ALIASES)))
