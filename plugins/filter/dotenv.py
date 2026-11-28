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
#   So in swarm mode the filter returns the value unchanged, including a
#   value carrying spaces: quoting one produced ``AGENT_PLATFORMS="{...}"``
#   in the broker's container, which ``json.loads`` then read as a string
#   rather than a mapping. A shell-sourced file needs the opposite and must
#   not contain a space at all - join such a value on a comma.
#
# The mode is read from ``DEPLOYMENT_MODE`` in the rendering context.
# When the context is missing (e.g. unit tests calling the filter
# directly), the compose-style quote is used as a safe default - the same
# behaviour the filter had before the swarm split.
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import jinja2
from ansible.errors import AnsibleFilterError

from utils.roles.applications.form_schema import ENV_NAME

_MISSING: Any = object()
_SNAKE = re.compile(r"[a-z][a-z0-9_]*")


def _quote_compose_style(value: Any) -> str:
    if value is None:
        return '""'

    s = str(value)

    s = s.replace("$", "$$")

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
        return _quote_compose_style(ctx)

    mode = ""
    try:
        mode = str(ctx.resolve("DEPLOYMENT_MODE") or "").strip()
    except Exception:  # pragma: no cover
        mode = ""

    if mode == "swarm":
        return _passthrough_swarm(value)
    return _quote_compose_style(value)


def _unquote_compose_style(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    value = value.replace('\\"', '"')
    value = value.replace("\\\\", "\\")
    return value.replace("$$", "$")


@jinja2.pass_context
def dotenv_unquote(ctx: jinja2.runtime.Context, value: Any = _MISSING) -> str:
    """Inverse of :func:`dotenv_quote`, for reading a value back out of a
    rendered ``.env`` file.

    Switched on the same ``DEPLOYMENT_MODE`` as the forward direction, so a
    value written in one mode is read back in that mode. Without a context
    the compose-style unquote applies, matching the forward default.
    """
    if value is _MISSING:
        return _unquote_compose_style(str(ctx))

    text = "" if value is None else str(value)

    mode = ""
    try:
        mode = str(ctx.resolve("DEPLOYMENT_MODE") or "").strip()
    except Exception:  # pragma: no cover
        mode = ""

    if mode == "swarm":
        return text
    return _unquote_compose_style(text)


def _assignment(content: Any, key: Any) -> str | None:
    prefix = f"{key}="
    for line in str(content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :]
    return None


def dotenv_value(content: Any, key: Any) -> str:
    """Return the raw right-hand side of ``key`` in a rendered ``.env``.

    Args:
        content: the file's text.
        key: the variable name to read.

    Returns:
        The value still quoted the way the file holds it, or an empty string
        when the file carries no such assignment. The caller unquotes it with
        :func:`dotenv_unquote`, which knows the mode the file was written in.
    """
    value = _assignment(content, key)
    return "" if value is None else value


def _name(field: str, specs: Any) -> str:
    spec = specs.get(field) if isinstance(specs, Mapping) else None
    env = spec.get("env") if isinstance(spec, Mapping) else None
    if env is not None:
        if not (isinstance(env, str) and ENV_NAME.fullmatch(env)):
            raise AnsibleFilterError(
                f"dotenv_names: env form field {field!r} names no variable"
            )
        return env
    if not _SNAKE.fullmatch(field):
        raise AnsibleFilterError(
            f"dotenv_names: env form field {field!r} is not lower snake_case"
        )
    return field.upper()


def dotenv_names(fields: Any, specs: Any = None) -> list[str]:
    """Return the env variable each field of an env form names.

    Args:
        fields: form field names.
        specs: the form's ``fields`` of ``meta/forms.yml``; a field whose spec
            declares ``env`` names that variable, every other field the
            upper-cased form of its key, which must then be lower snake_case.

    Returns:
        The variable names, in the fields' order.

    Raises:
        AnsibleFilterError: for an ``env`` that is no variable name, a field
            without ``env`` that is not lower snake_case, whose upper-cased
            name would read another variable, and two fields that name one
            variable.
    """
    names = [_name(str(field), specs) for field in fields or ()]
    if len(set(names)) != len(names):
        raise AnsibleFilterError("dotenv_names: two env form fields name one variable")
    return names


@jinja2.pass_context
def dotenv_fields(
    ctx: jinja2.runtime.Context, content: Any, fields: Any, specs: Any = None
) -> dict:
    """Return what a rendered ``.env`` holds for each field of a form.

    Args:
        content: the file's text.
        fields: form field names.
        specs: the form's ``fields`` of ``meta/forms.yml``, which name each
            field's variable as for :func:`dotenv_names`.

    Returns:
        Each field whose variable the file assigns, mapped to the value
        :func:`dotenv_unquote` reads back in the render's deployment mode; a
        field the file does not assign is left out.

    Raises:
        AnsibleFilterError: as :func:`dotenv_names`.
    """
    fields = list(fields or ())
    held = {}
    for field, name in zip(fields, dotenv_names(fields, specs), strict=True):
        value = _assignment(content, name)
        if value is not None:
            held[str(field)] = dotenv_unquote(ctx, value)
    return held


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "dotenv_fields": dotenv_fields,
            "dotenv_names": dotenv_names,
            "dotenv_quote": dotenv_quote,
            "dotenv_unquote": dotenv_unquote,
            "dotenv_value": dotenv_value,
        }
