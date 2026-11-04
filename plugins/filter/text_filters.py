import json
import re

from ansible.errors import AnsibleFilterError

_INLINE_JS_ESCAPES = str.maketrans(
    {"<": "\\u003c", "/": "\\u002f", "=": "\\u003d", " ": "\\u0020"}
)


def to_one_liner(s):
    """
    Collapse any multi-line string into a single line,
    trim extra whitespace, and remove JavaScript comments.
    Supports removal of both '//' line comments and '/*...*/' block comments,
    but preserves '//' inside string literals and templating expressions.
    """
    if not isinstance(s, str):
        raise AnsibleFilterError("to_one_liner() expects a string")

    no_block_comments = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)

    string_pattern = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
    literals = []

    def _extract(match):
        idx = len(literals)
        literals.append(match.group(0))
        return f"__STR{idx}__"

    temp = string_pattern.sub(_extract, no_block_comments)

    temp = re.sub(r"//.*$", "", temp, flags=re.MULTILINE)

    for idx, lit in enumerate(literals):
        temp = temp.replace(f"__STR{idx}__", lit)

    return re.sub(r"\s+", " ", temp).strip()


def to_inline_js(value):
    """Return ``value`` as a JSON literal for a script the injector inlines.

    Args:
        value: any JSON-serialisable value.

    Returns:
        compact ASCII JSON with every ``<``, ``/``, ``=`` and space written as
        a unicode escape, so the literal cannot close the ``<script>``
        element, cannot read as a comment to ``to_one_liner``, cannot end the
        Lua ``[=[ ]=]`` string ``body_filter.lua.j2`` embeds the script in,
        and keeps a run of spaces inside a string that ``to_one_liner``
        collapses everywhere else.
    """
    try:
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    except TypeError as exc:
        raise AnsibleFilterError(f"to_inline_js() cannot serialise: {exc}") from exc
    return text.translate(_INLINE_JS_ESCAPES)


class FilterModule:
    def filters(self):
        return {
            "to_one_liner": to_one_liner,
            "to_inline_js": to_inline_js,
        }
