"""The documents a deployment's knowledge index is built from.

The role stages every source into one knowledge directory and writes a
manifest beside it: the platform documentation, the README of every role
deployed on the host, and each document source a tenant names in its
inventory. Each manifest entry names the source, the directory it was staged
to and the public URL a reader follows to it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from assistant.scrub import indexable

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST = "sources.json"
_TITLE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Source:
    """One staged document source.

    Args:
        name: the source's label, shown beside its links.
        root: the directory the source was staged to, relative to the knowledge root.
        url: the public URL the source's root is published under.
    """

    name: str
    root: str
    url: str


@dataclass(frozen=True)
class Document:
    """One document of a source.

    Args:
        source: the source's name.
        title: the document's first H1, else its file name.
        url: the public URL of the document.
        text: the document's content.
    """

    source: str
    title: str
    url: str
    text: str


def load_manifest(knowledge: Path) -> list[Source]:
    """Return the sources the role staged under *knowledge*.

    Args:
        knowledge: the knowledge root directory.
    """
    entries = json.loads((knowledge / MANIFEST).read_text(encoding="utf-8"))
    return [Source(str(e["name"]), str(e["root"]), str(e["url"])) for e in entries]


def _title(text: str, fallback: str) -> str:
    match = _TITLE.search(text)
    return match.group(1) if match else fallback


def documents(knowledge: Path, sources: list[Source]) -> list[Document]:
    """Return every indexable document of *sources*, in a stable order.

    A path that leaves its source root, through ``..`` or a symlink, is skipped,
    so a tenant source cannot pull in a file staged for another source.

    Args:
        knowledge: the knowledge root directory.
        sources: the sources to read.
    """
    found: list[Document] = []
    for source in sources:
        root = (knowledge / source.root).resolve()
        if not root.is_dir() or knowledge.resolve() not in (root, *root.parents):
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file() or not indexable(relative):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found.append(
                Document(
                    source=source.name,
                    title=_title(text, path.stem),
                    url=f"{source.url.rstrip('/')}/{relative}",
                    text=text,
                )
            )
    return found
