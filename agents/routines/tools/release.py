"""Release brief, investor outline and channel check of the release routine.

Pure functions over the changelog entries, the brief and the channel texts a
release run writes: the brief carries the changelog lines once, the outline
keeps only the investor sections the brief or the operator's facts prove, and
the check names every leftover placeholder, em dash, length outside the
channel's bounds and number the evidence does not hold.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from agents.routines.tools.numbers import unbacked_numbers

ARTICLE_LINK = "https://s.infinito.nexus/infinito{major}"
CHANGELOG_LINK = "https://s.infinito.nexus/changelog"
REPOSITORY_LINK = "https://github.com/infinito-nexus/core"
DEFAULT_LANGUAGES = ("en",)
BRIEF_GROUPS = {
    "Upgrade notes": "upgrade_notes",
    "Version jumps": "updated_applications",
    "Contributors": "contributors",
}
BENEFITS = (3, 5)
MASTODON_URL_LENGTH = 23
EM_DASH = "—"
TEXT_SUFFIXES = (".txt", ".md", ".html", ".svg")
_LABEL = re.compile(r"^([A-Z][^:(]*?)\s*(?:\([^)]*\))?:\s*$")
_ITEM = re.compile(r"^- (.+?)\s*$")
_FILE = re.compile(r"^(?P<stem>[a-z-]+)\.(?P<lang>[a-z]{2})\.(?P<ext>txt|md|html|svg)$")
_PLACEHOLDER = re.compile(
    r"\{\{[^{}]*\}\}|\b(?:TODO|TBD|FIXME)\b|lorem ipsum", re.IGNORECASE
)
_BLOCK = re.compile(r"<(style|script|svg)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
_WORD = re.compile(r"[^\W_][\w'’.-]*")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Bound:
    """A length bound on one part of a channel text.

    Args:
        unit: ``words``, ``characters``, ``sentences`` or ``mastodon``
            (characters with every URL counted as 23).
        low: The smallest allowed length.
        high: The largest allowed length.
        part: ``all``, ``first_line``, ``subject``, ``preheader`` or
            ``body``.
    """

    unit: str
    low: int
    high: int
    part: str = "all"


@dataclass(frozen=True)
class Channel:
    """The bounds and the fixed language of one channel file stem.

    Args:
        bounds: The length bounds; empty for an image template.
        language: The one language the file is written in, or ``None`` when
            it follows the languages of the brief.
    """

    bounds: tuple[Bound, ...]
    language: str | None = None


_NEWSLETTER = Channel(
    (
        Bound("characters", 1, 60, "subject"),
        Bound("characters", 1, 130, "preheader"),
        Bound("words", 1, 600, "body"),
    )
)
CHANNELS = {
    "article": Channel((Bound("words", 500, 600),)),
    "article-meta": Channel(()),
    "banner": Channel(()),
    "banner-alt": Channel((Bound("sentences", 1, 3),)),
    "linkedin-article": Channel((Bound("words", 500, 600),)),
    "linkedin-post": Channel(
        (Bound("characters", 1000, 1600), Bound("characters", 1, 200, "first_line"))
    ),
    "mastodon": Channel((Bound("mastodon", 470, 500),)),
    "whatsapp-channel": Channel((Bound("characters", 1, 500),), "en"),
    "whatsapp-message": Channel((Bound("characters", 1, 500),), "de"),
    "newsletter-investors": _NEWSLETTER,
    "newsletter-customers": _NEWSLETTER,
    "newsletter-developers": _NEWSLETTER,
    "instagram": Channel(()),
    "instagram-caption": Channel(
        (Bound("characters", 1, 2200), Bound("characters", 1, 125, "first_line"))
    ),
}
INVESTOR_STEM = "newsletter-investors"


@dataclass(frozen=True)
class Section:
    """One investor newsletter section and the evidence it needs.

    Args:
        title: The section heading.
        source: ``brief`` or ``facts``, the file the evidence comes from.
        key: The top-level key that must hold a non-empty value there.
    """

    title: str
    source: str
    key: str


INVESTOR_SECTIONS = (
    Section("The Release", "brief", "headline"),
    Section("Product Progress", "brief", "benefits"),
    Section("Ecosystem", "brief", "updated_applications"),
    Section("Community", "brief", "contributors"),
    Section("Adoption", "facts", "adoption"),
    Section("Revenue", "facts", "revenue"),
    Section("Funding", "facts", "funding"),
    Section("Outlook", "facts", "outlook"),
)


def since_last_tag(
    entries: list[tuple[str, str, str]], version: str, tags: set[str]
) -> list[tuple[str, str, str]]:
    """Return the entry of ``version`` and every older one not yet tagged.

    When the ``.0`` tag of a release was never published, the patch entries
    before the first published tag belong to the same release.

    Args:
        entries: ``(version, date, body)`` newest first.
        version: The release version, without ``v``.
        tags: The repository's tag names.

    Raises:
        ValueError: The changelog has no entry for ``version``.
    """
    versions = [entry[0] for entry in entries]
    if version not in versions:
        raise ValueError(f"CHANGELOG.md has no entry for {version}")
    start = versions.index(version)
    picked = [entries[start]]
    for entry in entries[start + 1 :]:
        if f"v{entry[0]}" in tags:
            break
        picked.append(entry)
    return picked


def groups(body: str) -> dict[str, list[str]]:
    """Group the list items of an entry body under their ``Label:`` lines.

    Args:
        body: The entry text below its header.
    """
    found: dict[str, list[str]] = {}
    label = None
    for line in body.splitlines():
        if match := _LABEL.match(line.strip()):
            label = match.group(1)
            found.setdefault(label, [])
        elif (match := _ITEM.match(line.strip())) and label:
            found[label].append(match.group(1))
    return found


def base_of(
    entries: list[tuple[str, str, str]], version: str, tags: set[str]
) -> str | None:
    """Return the tag the release counts from: the first tagged older entry.

    Args:
        entries: ``(version, date, body)`` newest first.
        version: The release version, without ``v``.
        tags: The repository's tag names.
    """
    versions = [entry[0] for entry in entries]
    older = versions[versions.index(version) + 1 :]
    return next((f"v{v}" for v in older if f"v{v}" in tags), None)


def skeleton(picked: list[tuple[str, str, str]], base: str | None) -> dict:
    """Return the brief a release run starts from.

    The changelog lines are copied verbatim; ``headline`` and ``benefits``
    stay empty for the model step, ``languages`` holds the default until the
    operator answers.

    Args:
        picked: The entries ``since_last_tag`` returned.
        base: The tag the release counts from.
    """
    version, date, _ = picked[0]
    merged: dict[str, list[str]] = {}
    for _, _, body in picked:
        for label, items in groups(body).items():
            merged.setdefault(label, []).extend(items)
    brief: dict = {
        "version": version,
        "date": date,
        "base": base,
        "languages": list(DEFAULT_LANGUAGES),
        "headline": "",
        "benefits": [],
    }
    for label, key in BRIEF_GROUPS.items():
        brief[key] = merged.pop(label, [])
    brief["changelog"] = merged
    brief["links"] = {
        "article": ARTICLE_LINK.format(major=version.split(".", 1)[0]),
        "changelog": CHANGELOG_LINK,
        "repository": REPOSITORY_LINK,
    }
    return brief


def outline(brief: dict, facts: dict) -> list[str]:
    """Return the investor section titles the evidence proves, in order.

    A section whose key is empty or absent in its source is left out, never
    filled with a placeholder.

    Args:
        brief: The parsed brief.
        facts: The parsed facts file the operator passed, ``{}`` without one.
    """
    sources = {"brief": brief, "facts": facts}
    return [
        section.title
        for section in INVESTOR_SECTIONS
        if sources[section.source].get(section.key)
    ]


def brief_problems(brief: dict) -> list[str]:
    """Return what the model step left open in the brief.

    Args:
        brief: The parsed brief.
    """
    lines = {item for items in brief.get("changelog", {}).values() for item in items}
    problems = [] if brief.get("headline") else ["brief.yml: no headline"]
    benefits = brief.get("benefits") or []
    low, high = BENEFITS
    if not low <= len(benefits) <= high:
        problems.append(f"brief.yml: {len(benefits)} benefits, needs {low} to {high}")
    for index, benefit in enumerate(benefits, start=1):
        cited = benefit.get("changelog") or []
        if not cited or any(line not in lines for line in cited):
            problems.append(
                f"brief.yml: benefit {index} cites no changelog line verbatim"
            )
    return problems


def visible(name: str, text: str) -> str:
    """Return the text a reader sees: tags, styles, scripts and icons removed.

    Args:
        name: The file name; ``.html`` and ``.svg`` are stripped of markup.
        text: The file text.
    """
    if name.endswith(".html"):
        text = _BLOCK.sub(" ", text)
    if name.endswith((".html", ".svg")):
        text = html.unescape(_TAG.sub(" ", text))
    return text


def _part(text: str, part: str) -> str:
    lines = text.strip().splitlines()
    if part == "first_line":
        return lines[0] if lines else ""
    if part in {"subject", "preheader"}:
        prefix = f"{part.capitalize()}:"
        return next(
            (line[len(prefix) :].strip() for line in lines if line.startswith(prefix)),
            "",
        )
    if part == "body":
        return text.strip().partition("\n\n")[2]
    return text.strip()


def measure(text: str, unit: str) -> int:
    """Return the length of a text in a bound's unit.

    Args:
        text: The text.
        unit: ``words``, ``characters``, ``sentences`` or ``mastodon``.
    """
    if unit == "words":
        return len(_WORD.findall(text))
    if unit == "sentences":
        return len(_SENTENCE_END.findall(text))
    if unit == "mastodon":
        return len(_URL.sub("x" * MASTODON_URL_LENGTH, text))
    return len(text)


def problems(
    files: dict[str, str], brief: dict, evidence: str, sections: list[str]
) -> list[str]:
    """Return every finding of the deterministic channel check.

    Args:
        files: ``{file name: text}`` of the channel texts of a release run.
        brief: The parsed brief; its ``languages`` bind every channel without
            a fixed language.
        evidence: The brief text plus the facts file text; every number of a
            visible text must occur in it.
        sections: The investor titles ``outline`` returned.
    """
    found: list[str] = []
    languages = set(brief.get("languages") or DEFAULT_LANGUAGES)
    for name, text in sorted(files.items()):
        match = _FILE.match(name)
        channel = CHANNELS.get(match.group("stem")) if match else None
        if channel is None:
            found.append(
                f"{name}: not a channel file; name it <channel>.<language>.<ext>"
            )
            continue
        language = match.group("lang")
        if language not in ({channel.language} if channel.language else languages):
            found.append(f"{name}: language {language} is not asked for")
        shown = visible(name, text)
        found.extend(
            f"{name}: leftover placeholder {hit!r}"
            for hit in _PLACEHOLDER.findall(text)
        )
        if EM_DASH in shown:
            found.append(f"{name}: em dash")
        for bound in channel.bounds:
            size = measure(_part(shown, bound.part), bound.unit)
            if not bound.low <= size <= bound.high:
                found.append(
                    f"{name}: {bound.part} is {size} {bound.unit}, "
                    f"needs {bound.low} to {bound.high}"
                )
        found.extend(
            f"{name}: number {number} is not in the brief"
            for number in unbacked_numbers(shown, evidence)
        )
        if match.group("stem") == INVESTOR_STEM:
            found.extend(
                f"{name}: section {title!r} has no evidence"
                for title in _HEADING.findall(shown)
                if title not in sections
            )
    return found
