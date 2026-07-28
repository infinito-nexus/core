"""Stdlib reader for the block-YAML subset the bootstrap SPOT files use.

This is a deliberate second YAML touchpoint outside ``utils.cache.yaml``:
the modules that read the distro SPOT must import on the bare bootstrap
python, which runs the ``.env`` generator before any dependency is
installed, so they cannot reach the PyYAML-backed cache.

Supported: nested block mappings, block sequences of scalars, plain and
double-quoted string scalars, full-line and trailing comments, a single
leading document marker. Every other construct raises
:class:`BootstrapYamlError`, so ``load_block(text)`` either equals
``yaml.safe_load(text)`` or fails loud.

The plain-scalar rule is deliberately narrower than YAML's: a plain scalar
must start with a letter, an underscore or a slash, and may then carry only
``[A-Za-z0-9_./+@:-]`` and spaces. That excludes every leading character
PyYAML's implicit resolvers key off, so no accepted plain scalar can come
back as an int, float, bool, timestamp or null.
"""

from __future__ import annotations

import re

_PLAIN = re.compile(r"^[A-Za-z_/][A-Za-z0-9_./+@:\- ]*$")
_RESERVED = re.compile(r"^(?:true|false|yes|no|on|off|y|n|null)$", re.IGNORECASE)


class BootstrapYamlError(ValueError):
    """Raised for a construct outside the supported block subset."""


def _plain(text: str, lineno: int) -> str:
    if not _PLAIN.match(text) or ": " in text or text.endswith(":"):
        raise BootstrapYamlError(f"line {lineno}: unsupported plain scalar {text!r}")
    if _RESERVED.match(text):
        raise BootstrapYamlError(f"line {lineno}: {text!r} is not a string, quote it")
    return text


def _scalar(raw: str, lineno: int) -> str:
    if raw.startswith('"'):
        end = raw.find('"', 1)
        if end < 0 or "\\" in raw[1:end]:
            raise BootstrapYamlError(
                f"line {lineno}: unsupported quoted scalar {raw!r}"
            )
        trailer = raw[end + 1 :].strip()
        if trailer and not trailer.startswith("#"):
            raise BootstrapYamlError(f"line {lineno}: trailing text after {raw!r}")
        return raw[1:end]
    return _plain(raw.split(" #", 1)[0].strip(), lineno)


def load_block(text: str) -> dict:
    """Parse *text* as a block mapping and return it.

    Args:
        text: YAML source restricted to the supported block subset.

    Returns:
        The root mapping, with every scalar as a ``str``.

    Raises:
        BootstrapYamlError: for any construct outside the subset.
    """
    root: dict = {}
    stack: list[tuple[int, object]] = [(0, root)]
    pending: tuple[dict, str, int] | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if "\t" in line:
            raise BootstrapYamlError(f"line {lineno}: tab indentation")
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        if body == "---":
            if lineno != 1:
                raise BootstrapYamlError(f"line {lineno}: second document")
            continue
        indent = len(line) - len(line.lstrip(" "))
        if pending is not None:
            parent, key, parent_indent = pending
            if indent <= parent_indent:
                raise BootstrapYamlError(
                    f"line {lineno}: {key!r} has neither a value nor a block"
                )
            child: object = [] if body.startswith("- ") else {}
            parent[key] = child
            stack.append((indent, child))
            pending = None
        else:
            while indent < stack[-1][0]:
                stack.pop()
            if indent != stack[-1][0]:
                raise BootstrapYamlError(f"line {lineno}: unexpected indent")
        container = stack[-1][1]
        if body.startswith("- "):
            if not isinstance(container, list):
                raise BootstrapYamlError(f"line {lineno}: sequence entry in a mapping")
            container.append(_scalar(body[2:], lineno))
            continue
        if isinstance(container, list):
            raise BootstrapYamlError(f"line {lineno}: mapping entry in a sequence")
        key, sep, rest = body.partition(": ")
        if not sep:
            if not body.endswith(":"):
                raise BootstrapYamlError(
                    f"line {lineno}: not a mapping entry: {body!r}"
                )
            key, rest = body[:-1], ""
        if key != key.strip():
            raise BootstrapYamlError(f"line {lineno}: not a mapping entry: {body!r}")
        _plain(key, lineno)
        if key in container:
            raise BootstrapYamlError(f"line {lineno}: duplicate key {key!r}")
        rest = rest.strip()
        if not rest or rest.startswith("#"):
            pending = (container, key, indent)
            continue
        container[key] = _scalar(rest, lineno)
    if pending is not None:
        raise BootstrapYamlError(f"{pending[1]!r} has neither a value nor a block")
    if not root:
        raise BootstrapYamlError("empty document")
    return root
