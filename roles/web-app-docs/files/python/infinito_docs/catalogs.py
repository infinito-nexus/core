"""Which languages a documented checkout declares, and which it translates."""

from __future__ import annotations

from babel.messages.pofile import read_po

from utils.cache.yaml import load_yaml_str


def known_languages(src):
    """Return every language of ``meta/languages.yml`` mapped to its native name.

    Args:
        src: checkout of the version to document.
    """
    languages_file = src / "meta" / "languages.yml"
    if not languages_file.is_file():
        return {}
    return {
        str(code): str((entry or {}).get("native", code))
        for code, entry in (
            load_yaml_str(languages_file.read_text(encoding="utf-8")) or {}
        ).items()
    }


def catalog_translates(src, code):
    """Return whether the ``docs`` catalog of ``code`` holds at least one translation.

    Args:
        src: checkout of the version to document.
        code: ISO 639-1 code.
    """
    catalog = src / "locale" / code / "LC_MESSAGES" / "docs.po"
    if not catalog.is_file():
        return False
    with catalog.open("rb") as handle:
        return any(m.id and m.string and not m.fuzzy for m in read_po(handle))


def translated_languages(src):
    """Return the languages of ``src`` and those its ``docs`` catalogs translate.

    Args:
        src: checkout of the version to document.

    Returns:
        ``(known, translated)``: every language of ``meta/languages.yml``
        mapped to its native name, and the codes whose ``docs.po`` holds at
        least one translation.
    """
    known = known_languages(src)
    return known, [code for code in sorted(known) if catalog_translates(src, code)]
