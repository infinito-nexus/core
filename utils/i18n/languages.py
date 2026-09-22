"""The language list of ``meta/languages.yml``."""

from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import load_yaml

SOURCE_LANGUAGE = "en"
LANGUAGES_FILE = Path("meta") / "languages.yml"
DOMAINS = ("core", "docs")


def load_languages(root: Path) -> dict[str, dict]:
    """Return every language of ``meta/languages.yml`` keyed by ISO 639-1 code.

    Args:
        root: repository root.
    """
    return load_yaml(root / LANGUAGES_FILE)


def domain_languages(languages: dict[str, dict], domain: str) -> list[str]:
    """Return the codes that carry a catalog of ``domain``.

    Args:
        languages: the mapping returned by ``load_languages``.
        domain: ``core`` for every language but the source language, ``docs``
            for the languages LibreTranslate supports.
    """
    if domain == "core":
        return sorted(code for code in languages if code != SOURCE_LANGUAGE)
    if domain == "docs":
        return sorted(
            code for code, entry in languages.items() if entry["libretranslate"]
        )
    raise ValueError(f"unknown domain: {domain}")


def translatable(languages: dict[str, dict], domain: str) -> list[str]:
    """Return the codes of ``domain`` LibreTranslate can machine-translate.

    Args:
        languages: the mapping returned by ``load_languages``.
        domain: gettext domain.
    """
    return [
        code
        for code in domain_languages(languages, domain)
        if languages[code]["libretranslate"]
    ]
