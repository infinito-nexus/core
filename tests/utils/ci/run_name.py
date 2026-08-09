"""Render a manual CI run name from its workflow source of truth.

Single point of truth for test fixtures, for the same reason
``utils.github.run_name`` parses rather than hard-codes the format: a
hand-typed title drifts the moment ``entry-manual-steer.yml`` changes its
``run-name``, and the retrigger that reads configuration back out of it
would silently start recovering nothing.
"""

from __future__ import annotations

from utils.github import run_name

_GLYPH_OF = {value: glyph for glyph, value in run_name.VALUE_GLYPHS.items()}


def render(config: dict[str, str]) -> str:
    """The run name ``entry-manual-steer.yml`` builds for *config*.

    Args:
        config: dispatch inputs that deviate from their workflow default,
            keyed by input name. An input on its default renders no segment,
            so passing it here would produce a title the workflow never emits.

    Returns:
        The rendered title, segments in the order the run name declares them.
    """
    literals, _expressions = run_name._split(run_name.template())
    parts = [literals[0]]
    for name, literal, marker in run_name.segments():
        value = config.get(name)
        if marker:
            parts.append(f"{literal} " if value == "true" else "")
        elif value:
            parts.append(f"{literal}{_GLYPH_OF.get(value, value)} ")
    return "".join(parts).rstrip()
