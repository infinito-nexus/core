"""What may reach the knowledge index, and what is masked before it does.

Only Markdown documents outside every inventory, variable and secret path are
read at all. Their text then passes the repository's own secret patterns
(``utils/agents/redact.py``, staged beside this package), an Ansible Vault
block filter and an e-mail filter, so a credential, an inventory secret or a
person's address in a document is masked before it is embedded.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from utils.agents.redact import MASK, redact

INDEXED_SUFFIXES = frozenset({".md"})
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        "credentials",
        "group_vars",
        "host_vars",
        "inventories",
        "inventory",
        "secrets",
        "vault",
    }
)
EXCLUDED_NAMES = frozenset({".env", "secrets.yml", "vault.yml"})

_VAULT = re.compile(r"\$ANSIBLE_VAULT;[^\n]*(?:\n[ \t]*[0-9a-fA-F]+)*")
_EMAIL = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
)


def indexable(path: str) -> bool:
    """Return whether a document path may be read into the index.

    Args:
        path: the document path relative to its source root.
    """
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in INDEXED_SUFFIXES:
        return False
    if pure.name.lower() in EXCLUDED_NAMES:
        return False
    return not any(part.lower() in EXCLUDED_PARTS for part in pure.parts[:-1])


def scrub(text: str) -> str:
    """Return *text* with every recognised secret and e-mail address masked.

    Args:
        text: a document passage about to be embedded, or a model reply.
    """
    return _EMAIL.sub(MASK, redact(_VAULT.sub(MASK, text)))


def leaks(text: str) -> bool:
    """Return whether *text* still carries something :func:`scrub` would mask.

    Args:
        text: a passage as it would be stored.
    """
    return scrub(text) != text
