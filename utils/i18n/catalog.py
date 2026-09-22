"""Reading, merging and writing the gettext catalogs under ``locale/``."""

from __future__ import annotations

import datetime
import io
from pathlib import Path
from typing import TYPE_CHECKING

from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

if TYPE_CHECKING:
    from collections.abc import Iterable

LOCALE_DIR = Path("locale")
PROJECT = "infinito-nexus"
MACHINE_TRANSLATION = "libretranslate"
STAMP = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def catalog_path(root: Path, code: str, domain: str) -> Path:
    """Return the path of the ``domain`` catalog of language ``code``.

    Args:
        root: repository root.
        code: ISO 639-1 code.
        domain: gettext domain.
    """
    return root / LOCALE_DIR / code / "LC_MESSAGES" / f"{domain}.po"


def new_catalog(domain: str, code: str | None = None) -> Catalog:
    """Return an empty catalog.

    Args:
        domain: gettext domain.
        code: ISO 639-1 code, ``None`` for a template.
    """
    return Catalog(
        locale=code,
        domain=domain,
        project=PROJECT,
        creation_date=STAMP,
        revision_date=STAMP,
        fuzzy=False,
    )


def build_template(messages: Iterable[tuple[str, str]], domain: str) -> Catalog:
    """Return a template catalog holding ``messages``.

    Args:
        messages: ``(msgctxt, msgid)`` pairs; ``msgctxt`` may be ``None``.
        domain: gettext domain.
    """
    template = new_catalog(domain)
    for context, msgid in messages:
        template.add(msgid, context=context)
    return template


def read_catalog(path: Path) -> Catalog:
    """Return the catalog stored at ``path``.

    Args:
        path: ``.po`` or ``.pot`` file.
    """
    with path.open("rb") as handle:
        return read_po(handle)


def merge(template: Catalog, existing: Catalog | None, code: str) -> Catalog:
    """Return ``existing`` updated to the messages of ``template``.

    A changed source keeps its previous translation as a fuzzy entry, a removed
    source disappears.

    Args:
        template: catalog of the current sources.
        existing: the language's catalog, ``None`` when it does not exist yet.
        code: ISO 639-1 code of the language.
    """
    catalog = existing if existing is not None else new_catalog(template.domain, code)
    catalog.update(template)
    catalog.obsolete.clear()
    return catalog


def render(catalog: Catalog) -> bytes:
    """Return the deterministic ``.po`` serialisation of ``catalog``.

    Args:
        catalog: the catalog to serialise.
    """
    catalog.creation_date = STAMP
    catalog.revision_date = STAMP
    catalog.fuzzy = False
    buffer = io.BytesIO()
    write_po(buffer, catalog, width=0, sort_output=True, ignore_obsolete=True)
    return buffer.getvalue()


def write_catalog(path: Path, catalog: Catalog) -> bool:
    """Write ``catalog`` to ``path`` unless the file already holds it.

    Args:
        path: target ``.po`` file.
        catalog: the catalog to write.

    Returns:
        ``True`` when the file changed.
    """
    content = render(catalog)
    if path.is_file():
        with path.open("rb") as handle:
            if handle.read() == content:
                return False
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    staging.write_bytes(content)
    staging.replace(path)
    return True


def translations(catalog: Catalog) -> dict[tuple[str | None, str], str]:
    """Return every usable translation of ``catalog``.

    Args:
        catalog: a language catalog.

    Returns:
        ``(msgctxt, msgid)`` mapped to ``msgstr``; empty and fuzzy entries are
        left out, so their source text stands in.
    """
    return {
        (message.context, message.id): message.string
        for message in catalog
        if message.id
        and isinstance(message.id, str)
        and message.string
        and not message.fuzzy
    }
