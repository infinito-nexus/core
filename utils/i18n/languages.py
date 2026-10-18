"""The language list of ``meta/languages.yml``.

The file is the one place that names the languages this repository supports,
and it carries nothing but their identity: name, endonym and writing
direction. Every language it names gets a catalog in every domain.

Which engine renders into a language is deliberately not written here. The
translation gateway offers each backend that serves the pair, falls through to
the next one when an engine refuses or mangles the answer, drops an engine
whose failures pile up, and settles a language on the engine that wins its
comparisons. A static table beside that would be a second opinion that goes
stale the moment the router learns something. What a single engine can do is
declared with that engine instead: ``services.libretranslate-engine.serves``
of ``roles/svc-ai-libretranslate-engine`` states the codes its models cover,
because the lane prefetches those models before any engine can be asked.
"""

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
        domain: a name of :data:`DOMAINS`.
    """
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain: {domain}")
    return sorted(code for code in languages if code != SOURCE_LANGUAGE)
