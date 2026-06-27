# Dotenv-safe quoting for .env files.
#
# Behaviour is mode-aware:
#
# * Compose: wraps value in double quotes, escapes ``$`` as ``$$`` (compose
#   parses interpolation), escapes ``\\`` and ``"``. Compose then strips
#   the outer quotes back off when loading the env-file.
#
# * Swarm: ``docker stack deploy`` does NOT strip outer quotes and does NOT
#   apply ``$$`` interpolation - the value is passed verbatim to the
#   container. Wrapping the value would leak literal quotes into
#   ``$KEY`` ("\"password\""), breaking DB connect strings, URL parsers,
#   and any ``int(os.environ['KEY'])`` consumer.
#   So in swarm mode the filter returns the value unchanged.
#
# The mode is read from ``DEPLOYMENT_MODE`` in the rendering context.
# When the context is missing (e.g. unit tests calling the filter
# directly), the compose-style quote is used as a safe default - the same
# behaviour the filter had before the swarm split.
from __future__ import annotations

from typing import Any

import jinja2

_MISSING: Any = object()


def _quote_compose_style(value: Any) -> str:
    if value is None:
        return '""'

    s = str(value)

    # Compose interpolates $VAR; $$ becomes literal $.
    s = s.replace("$", "$$")

    # Escape backslash first, then double quotes.
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')

    return f'"{s}"'


def _passthrough_swarm(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


@jinja2.pass_context
def dotenv_quote(ctx: jinja2.runtime.Context, value: Any = _MISSING) -> str:
    """Dotenv-safe quote, switched on DEPLOYMENT_MODE from the render context.

    Also callable directly from Python (unit tests, helpers) without a
    Jinja context: in that case the only positional argument is the
    value and compose-style quoting is used.
    """
    if value is _MISSING:
        # Called as `dotenv_quote(value)` outside a Jinja render.
        return _quote_compose_style(ctx)

    mode = ""
    try:
        mode = str(ctx.resolve("DEPLOYMENT_MODE") or "").strip()
    except Exception:  # pragma: no cover
        mode = ""

    if mode == "swarm":
        return _passthrough_swarm(value)
    return _quote_compose_style(value)


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "dotenv_quote": dotenv_quote,
        }
