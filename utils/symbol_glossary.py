"""Single source of truth mapping short words to display emojis, and back.

Every emoji used as a STRUCTURED marker across the project (complexity-matrix
columns, lifecycle stages, deploy modes, boolean/state cells) is defined here
exactly once, so a glyph means the same thing everywhere it appears. Emojis are
unique: the module fails to import if two words share a glyph.

Look up with :func:`to_emoji` (word -> emoji) and :func:`to_word` (emoji ->
canonical word); both pass unknown input through unchanged.
"""

from __future__ import annotations

SYMBOLS: dict[str, str] = {
    "enabled": "✅",
    "disabled": "❌",
    "skip": "⏭️",
    "priority": "⭐",
    "distros": "🐧",
    "unavailable": "➖",
    "integrated": "🧩",
    "role_dependency": "⚙️",
    "compose": "🐳",
    "swarm": "🐝",
    "stack": "🥞",
    "host": "💻",
    "row": "🔢",
    "id": "🆔",
    "name": "📛",
    "lifecycle": "🌱",
    "variant": "🎯",
    "variants": "🔀",
    "bundles": "📦",
    "jobs": "👷",
    "test_compose": "🐋",
    "test_swarm": "🍯",
    "test_host": "🏠",
    "embeds_direct": "⏩",
    "embeds": "📥",
    "consumers_direct": "⏪",
    "consumers": "📤",
    "weight": "📊",
    "random": "🎲",
    "dna": "🧬",
    "clone": "🐑",
    "siblings": "👯",
    "covered_by": "🔰",
    "planned": "🧭",
    "pre-alpha": "🧪",
    "alpha": "🐣",
    "beta": "🌿",
    "rc": "🚦",
    "stable": "🟢",
    "maintenance": "🔧",
    "deprecated": "🚫",
    "eol": "🪦",
}

_BY_EMOJI: dict[str, str] = {emoji: word for word, emoji in SYMBOLS.items()}
if len(_BY_EMOJI) != len(SYMBOLS):
    raise ValueError("symbol_glossary: every emoji MUST be unique across words")


def to_emoji(word: str) -> str:
    """Return the emoji mapped to *word*, or *word* itself when unmapped."""
    return SYMBOLS.get(word, word)


def to_word(emoji: str) -> str:
    """Return the canonical word for *emoji*, or *emoji* itself when unmapped."""
    return _BY_EMOJI.get(emoji, emoji)
