"""Catalogues keyed by name, as browser code reads them, built from the ``core`` domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.i18n.catalog import catalog_path, read_catalog, translations
from utils.i18n.languages import SOURCE_LANGUAGE, domain_languages, load_languages

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def keyed_catalogue(
    root: Path, context: Callable[[str], str], source: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Return ``source`` in English and every language that translates any of it.

    Args:
        root: repository root.
        context: maps a key to the ``msgctxt`` of its message.
        source: key mapped to its English text.

    Returns:
        ISO 639-1 code mapped to ``{key: text, "dir": direction}``; a key a
        language leaves untranslated keeps its English text.
    """
    languages = load_languages(root)
    catalogue = {
        SOURCE_LANGUAGE: {**source, "dir": languages[SOURCE_LANGUAGE]["direction"]}
    }
    for code in domain_languages(languages, "core"):
        path = catalog_path(root, code, "core")
        if not path.is_file():
            continue
        found = translations(read_catalog(path))
        texts = {key: found.get((context(key), text)) for key, text in source.items()}
        if any(texts.values()):
            catalogue[code] = {
                **{key: texts[key] or source[key] for key in source},
                "dir": languages[code]["direction"],
            }
    return catalogue


def source_keyed_catalogues(
    root: Path, prefixes: tuple[str, ...]
) -> dict[str, dict[str, str]]:
    """Return catalogues keyed by the English source text, as port-ui reads them.

    Args:
        root: repository root.
        prefixes: ``msgctxt`` prefixes of the messages to include, e.g. ``role:``.

    Returns:
        ISO 639-1 code mapped to ``{english: translation}`` for every language
        that translates at least one included message.
    """
    catalogues = {}
    for code in domain_languages(load_languages(root), "core"):
        path = catalog_path(root, code, "core")
        if not path.is_file():
            continue
        entries: dict[str, str] = {}
        for (context, msgid), msgstr in sorted(
            translations(read_catalog(path)).items()
        ):
            if context and context.startswith(prefixes):
                entries.setdefault(msgid, msgstr)
        if entries:
            catalogues[code] = entries
    return catalogues
